/*
 * Servidor do ARO — passo 2: LER A SELEÇÃO da timeline do Media Composer por dentro (De Lá Pra Cá,
 * 2026-10-25, só laboratório). Sucede a sonda do passo 1.5 (aro_sonda.c, servidor-escuta).
 *
 * A tese (banco, avid-panel-sdk/arrastar.md §"O contrato do ARO"): o MC carrega esta dylib em toda
 * abertura (dlopen de um caminho fixo) e, quando ARO_Init aceita, DIRIGE o nosso objeto-servidor —
 * Start, RegisterClass de cada classe. As 591 funções do ARO (TLW_GetSelComponents etc.) são C puras
 * com assinatura f(AROincoming*, AROserver*, AROoutgoing*); não usam estado global, só essas três
 * interfaces. Então NÓS implementamos as três interfaces e CHAMAMOS a função direto, por dentro do
 * processo, na THREAD PRINCIPAL — sem depender do ProcessPendingRequest (o nó do passo 1.5).
 *
 * O encadeamento para ler a seleção (medido no binário, MC 25.12.0 arm64 — ver PASSO2.md):
 *   MCapp_Timeline            -> registra a TimelineWindow, devolve o objectID
 *   TLW_GetNumSelComponents   -> obj->vtable[158]()            = a contagem
 *   TLW_GetSelComponents      -> obj->vtable[157](i,0) p/ cada = o i-ésimo AComponent selecionado
 *   AComponent_GetName/Type/IsSegment/GetParent  -> a identidade de cada segmento
 *
 * As três interfaces, os slots que as funções chamam (índice = offset/8):
 *   in  (AROincoming):  [35]=GetAlvoID  [38]=FimDaLeitura
 *   srv (AROserver):    [2]=Start [9]=RegisterClass [14]=RegisterObject [15]=LookupObject [32]=Pending
 *   out (AROoutgoing):  [2]=AddBool [3]=AddInt [11]=AddString(const char* UTF-8) [13]=AddObjectID
 *                       [14]=AddEnum(tabela,val) [17]=Finish [20]=AddError
 *
 * Resolução das funções POR NOME (robusto entre versões): a tabela de RegisterClass é pares
 * {const char* nome, void* fn} terminados em {0,0}; o nome é SEM prefixo ("GetSelComponents"). Guardamos
 * (classe -> tabela) no RegisterClass e varremos por (classe, método). Fallback: vmaddr fixo + slide (só 25.12).
 *
 * Transporte: um socket TCP em 127.0.0.1 (porta ARO_PORT, padrão 17890). Comandos de linha: PING, SELECTION.
 * A thread do socket DESPACHA o trabalho para a main (dispatch_async_f) e espera por um semáforo — tudo o que
 * toca objeto do MC roda na main (Qt/AObject não são thread-safe).
 *
 * Log: ~/Library/Logs/DeLaPraCa/aro_servidor.log.  Compilar: tools/aro/compilar.sh.
 */

#include <arpa/inet.h>
#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <netinet/in.h>
#include <CoreFoundation/CoreFoundation.h>
#include <fcntl.h>
#include <pthread.h>
#include <setjmp.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#define ARO_VERSAO 2025
#define N_SRV 128
#define N_IN 64
#define N_OUT 64

/* ---------------------------------------------------------------- log ------ */

static FILE *g_log = NULL;
static pthread_mutex_t g_log_mx = PTHREAD_MUTEX_INITIALIZER;
static long g_slide = 0;

static void registrar(const char *fmt, ...) {
    pthread_mutex_lock(&g_log_mx);
    if (!g_log) {
        char caminho[1024];
        const char *lar = getenv("HOME");
        snprintf(caminho, sizeof caminho, "%s/Library/Logs/DeLaPraCa/aro_servidor.log", lar ? lar : "/tmp");
        g_log = fopen(caminho, "a");
        /* o log não vaza para os filhos do MC (o "e" do fopen NÃO vale no macOS — medido 2026-10-28) */
        if (g_log) fcntl(fileno(g_log), F_SETFD, FD_CLOEXEC);
        if (!g_log) g_log = stderr;
    }
    char hora[32];
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    strftime(hora, sizeof hora, "%H:%M:%S", &tm);
    fprintf(g_log, "%s ", hora);
    va_list ap;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
    pthread_mutex_unlock(&g_log_mx);
}

static int parece_ponteiro(long v) { return v > 0x100000000L && v < 0x280000000L; }

static long calcular_slide(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++)
        if (_dyld_get_image_header(i)->filetype == 2 /* MH_EXECUTE */)
            return _dyld_get_image_vmaddr_slide(i);
    return 0;
}

/* ----------------------------------------------- mapa de objetos id<->ptr -- */
/* Acessado só na main thread (durante a cadeia). id é 1-based. */

#define MAX_OBJ 8192
static void *g_objmap[MAX_OBJ];
static int g_objn = 0;

/* ----------------------------------------------- classes registradas ------ */

typedef struct {
    char *nome;
    void **metodos; /* array plano {nome0, fn0, nome1, fn1, ..., 0, 0} */
} Classe;
static Classe g_classes[128];
static int g_nclasses = 0;

/* -------------------------------------------------------- o servidor ------- */

static struct {
    void *vtable;
    char resto[0x400];
} g_servidor;

/* vtables (preenchidas com escutas por aro_stubs.h; os slots reais são sobrescritos no constructor) */
long srv_log(int idx, long a0, long a1, long a2, long a3, void *ra);
long in_log(int idx, long a0, long a1, long a2, long a3, void *ra);
long out_log(int idx, long a0, long a1, long a2, long a3, void *ra);
#include "aro_stubs.h" /* gera srv_vtable[128], in_vtable[64], out_vtable[64] + as escutas */

/* As escutas: registram índice+args e devolvem 0 (o servidor precisa segurar o registro do MC). */
long srv_log(int idx, long a0, long a1, long a2, long a3, void *ra) {
    static int cont[N_SRV];
    long off = g_slide ? ((long)ra - g_slide) : (long)ra;
    int n = (idx >= 0 && idx < N_SRV) ? cont[idx]++ : 99;
    if (n < 2) registrar("srv[%d](%#lx,%#lx,%#lx,%#lx)  [+%#lx]  (escuta)", idx, a0, a1, a2, a3, off);
    return 0;
}
long in_log(int idx, long a0, long a1, long a2, long a3, void *ra) {
    (void)a0; (void)a1; (void)a2; (void)a3; (void)ra;
    registrar("in[%d] INESPERADO -> 0", idx);
    return 0;
}
long out_log(int idx, long a0, long a1, long a2, long a3, void *ra) {
    (void)a0; (void)a1; (void)a2; (void)a3; (void)ra;
    registrar("out[%d] INESPERADO -> 0", idx);
    return 0;
}

/* --------------------------------- slots reais do servidor (srv) ----------- */

static long srv_Start(void *self, long porta, long flag) {
    (void)self;
    registrar("srv[2] Start(porta=%ld, flag=%ld) -> 0 (sucesso)", porta, flag);
    return 0;
}
static long srv_RegisterClass(void *self, const char *nome, const char *mae, void **metodos) {
    (void)self;
    if (g_nclasses < (int)(sizeof g_classes / sizeof g_classes[0]) && parece_ponteiro((long)nome)) {
        g_classes[g_nclasses].nome = strdup(nome);
        g_classes[g_nclasses].metodos = metodos;
        g_nclasses++;
    }
    registrar("srv[9] RegisterClass(\"%s\", mae=\"%s\", metodos=%p)",
              parece_ponteiro((long)nome) ? nome : "?", parece_ponteiro((long)mae) ? mae : "?", (void *)metodos);
    return 0;
}
static long srv_RegisterObject(void *self, const char *classe, void *obj, int *outId) {
    (void)self; (void)classe;
    int id = 0;
    if (g_objn + 1 < MAX_OBJ) { id = ++g_objn; g_objmap[id] = obj; }
    if (outId) *outId = id;
    return 0;
}
static long srv_LookupObject(void *self, int id, void **outObj) {
    (void)self;
    void *o = (id > 0 && id <= g_objn) ? g_objmap[id] : NULL;
    if (outObj) *outObj = o;
    return 0;
}
static long srv_ProcessPending(void *self) { (void)self; return 0; }

/* ------------------------------------ as três interfaces que criamos ------- */

typedef struct { void *vtable; long alvo; } In;
typedef struct { void *vtable; void *resp; } Out;

/* o acumulador de resultado de UMA chamada ARO */
typedef struct {
    int objids[256]; int n_obj;
    long ints[64];   int n_int; /* AddInt / AddBool / AddEnum */
    char *strs[64];  int n_str;
    int finished;
    char erro[256];
} Resp;

static long in_GetAlvo(void *self) { return ((In *)self)->alvo; }
static long in_Fim(void *self) { (void)self; return 0; }
/* protocolo de ARGUMENTOS do GetMobProperty: in[2]()=quantas chaves, in[15](i)=a i-ésima chave (código).
 * No modo sonda, pedimos os códigos 0..g_probe_nkeys-1 para descobrir empiricamente quais dão nome/MobID. */
static int g_probe_nkeys = 0;
static long in_NumArgs(void *self) { (void)self; return g_probe_nkeys; }
static long in_GetKey(void *self, long i) { (void)self; return i; }
/* in[14]: lê um argumento BOOLEANO por nome (x1=nome). GetTracks pede "source"; TLP_GetAllLines pede
 * "SelectedItemsOnly". Devolvemos 1 só para "SelectedItemsOnly" (queremos só os selecionados). */
static long in_BoolArg(void *self, const char *nome) {
    (void)self;
    if (parece_ponteiro((long)nome) && strcmp(nome, "SelectedItemsOnly") == 0) return 1;
    return 0;
}

static long out_AddBool(void *self, int val, const char *nome) {
    (void)nome; Resp *r = ((Out *)self)->resp;
    if (r->n_int < 64) r->ints[r->n_int++] = val ? 1 : 0;
    return 0;
}
static long out_AddInt(void *self, int val, const char *nome) {
    (void)nome; Resp *r = ((Out *)self)->resp;
    if (r->n_int < 64) r->ints[r->n_int++] = val;
    return 0;
}
static long out_AddString(void *self, const char *s, const char *nome) {
    (void)nome; Resp *r = ((Out *)self)->resp;
    if (r->n_str < 64) r->strs[r->n_str++] = strdup(s ? s : "");
    return 0;
}
static long out_AddObjID(void *self, int id, const char *nome) {
    (void)nome; Resp *r = ((Out *)self)->resp;
    if (r->n_obj < 256) r->objids[r->n_obj++] = id;
    return 0;
}
static long out_AddEnum(void *self, void *tabela, long val, const char *nome) {
    (void)tabela; (void)nome; Resp *r = ((Out *)self)->resp;
    if (r->n_int < 64) r->ints[r->n_int++] = val;
    return 0;
}
static long out_Finish(void *self) { ((Resp *)((Out *)self)->resp)->finished = 1; return 0; }
static long out_AddError(void *self, const char *msg) {
    Resp *r = ((Out *)self)->resp;
    snprintf(r->erro, sizeof r->erro, "%s", parece_ponteiro((long)msg) ? msg : "?");
    return 0;
}

static void resp_limpar(Resp *r) {
    for (int i = 0; i < r->n_str; i++) free(r->strs[i]);
    memset(r, 0, sizeof *r);
}

/* ------------------------------------------ resolução das funções ---------- */

typedef long (*aro_fn)(void *in, void *srv, void *out);

static void *buscar_na_classe(const char *classe, const char *metodo) {
    for (int c = 0; c < g_nclasses; c++) {
        if (classe && g_classes[c].nome && strcmp(g_classes[c].nome, classe) != 0) continue;
        void **m = g_classes[c].metodos;
        if (!m) continue;
        for (int k = 0; k < 1024 && m[2 * k]; k++)
            if (strcmp((const char *)m[2 * k], metodo) == 0) return m[2 * k + 1];
    }
    return NULL;
}

/* Os vmaddr fixos (abaixo) só valem no build em que foram medidos. ⚠️ (revisão 2026-10-28) O `Timeline` e o
 * `GetSelComponent` SÓ se acham por vmaddr (o log mostra "vmaddr+slide") — noutro build do MC a dylib chamaria código
 * qualquer na thread principal ANTES de o auto-teste do Python (`/mc/selecao-aro`) ter como recusar. Então: fora do
 * build medido, nenhum vmaddr — o comando responde ERR e o painel cai no Cmd+C. Multiversão = um mapa por build. */
#define BUILD_MEDIDO "25.12.0.58863"
static int g_build_ok = -1;  /* -1 = não conferido */
static int build_medido(void) {
    if (g_build_ok >= 0) return g_build_ok;
    g_build_ok = 0;
    char versao[64] = "";
    CFBundleRef b = CFBundleGetMainBundle();
    CFTypeRef v = b ? CFBundleGetValueForInfoDictionaryKey(b, CFSTR("CFBundleShortVersionString")) : NULL;
    if (v && CFGetTypeID(v) == CFStringGetTypeID())
        CFStringGetCString((CFStringRef)v, versao, sizeof versao, kCFStringEncodingUTF8);
    g_build_ok = strcmp(versao, BUILD_MEDIDO) == 0;
    registrar("build do MC \"%s\" %s o medido (%s)", versao, g_build_ok ? "==" : "!=", BUILD_MEDIDO);
    return g_build_ok;
}

/* Resolve (classe, método); se não achar na classe, varre todas; se não achar, usa o vmaddr do 25.12 + slide. */
static aro_fn resolver(const char *classe, const char *metodo, unsigned long vmaddr) {
    void *fn = buscar_na_classe(classe, metodo);
    const char *via = "nome/classe";
    if (!fn) { fn = buscar_na_classe(NULL, metodo); via = "nome/qualquer"; }
    if (!fn && vmaddr && build_medido()) { fn = (void *)((long)vmaddr + g_slide); via = "vmaddr+slide"; }
    registrar("resolver %s.%s -> %p (%s)", classe ? classe : "*", metodo, fn, fn ? via : "NAO ACHOU");
    return (aro_fn)fn;
}

/* vmaddr estáticos (MC 25.12.0 arm64) — só fallback; o primário é por nome */
#define VM_TIMELINE 0x101ebd0bcUL
#define VM_NUMSEL 0x101eb2120UL
#define VM_GETSEL 0x101eb21c8UL
#define VM_NAME 0x101ea5758UL
#define VM_TYPE 0x101ea53f0UL
#define VM_ISSEG 0x101ea5b00UL
#define VM_PARENT 0x101ea5894UL
#define VM_LENGTH 0x101ea56acUL
#define VM_ISTG 0x101ea5c78UL
#define VM_TRACKS 0x101eb1408UL
#define VM_MOBPROP 0x101ea67acUL
#define VM_MOBTYPE 0x101ea651cUL
#define VM_TLPALL 0x101ef4b7cUL  /* TLP_GetAllLines (não está em classe registrada -> fallback vmaddr) */
#define VM_TLPLINE 0x101ef4a94UL /* TLP_GetLine */
/* TimelineWindow::GetSelComponent(short i, int* out) -> AComponent* — MÉTODO DE CLASSE (símbolo local `t`, não
 * dá dlsym): endereço por vmaddr+slide. 1-based (i=1..N devolve o i-ésimo; i=0 só vale com 1 selecionado). Chamamos
 * DIRETO para contornar o off-by-one do laço 0..N-1 do TLW_GetSelComponents (MC 25.12.0 arm64; 2026-10-26, RE). */
#define VM_TW_GETSELCOMP 0x101e51be8UL
static int coletar_selecionados(int idtl, int *cids, int max);  /* def. adiante (usa protegido_gsc) */

/* Captura de falha (SIGSEGV/SIGBUS) só na janela de UMA chamada ARO — transforma o crash em dado.
 * macOS: a Avid converte o fault num std::exception por um handler POSIX; sobrepomos o dela durante a
 * chamada (salvando a antiga) e a devolvemos logo depois. Se a falha for entregue por porta Mach, este
 * handler pode não disparar — então o LOG (gravado e descarregado ANTES de cada chamada) é o diagnóstico.
 * ⚠️ (revisão 2026-10-28) O sigaction vale para o PROCESSO inteiro, mas o g_jb é da pilha da MAIN: uma falha de
 * OUTRA thread do MC dentro da janela pularia para a pilha da main (indefinido). Só a main pula; as outras recebem
 * de volta o tratador da Avid e a falha se repete nele, como se não estivéssemos aqui. */
static sigjmp_buf g_jb;
static volatile sig_atomic_t g_armado = 0;
static struct sigaction g_velho_segv, g_velho_bus;
static void ao_falhar(int sig) {
    if (g_armado && pthread_main_np()) { g_armado = 0; siglongjmp(g_jb, sig); }
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
}

/* chama uma função ARO de alvo `alvo`; devolve 0 ok, -1 nao resolvida, -2 FALHA capturada (quem chama limpa) */
static int chamar(aro_fn fn, long alvo, Resp *r, const char *rotulo) {
    memset(r, 0, sizeof *r);
    if (!fn) { snprintf(r->erro, sizeof r->erro, "funcao nao resolvida"); return -1; }
    In in = { .vtable = in_vtable, .alvo = alvo };
    Out out = { .vtable = out_vtable, .resp = r };

    struct sigaction nova;
    memset(&nova, 0, sizeof nova);
    nova.sa_handler = ao_falhar;
    sigemptyset(&nova.sa_mask);
    nova.sa_flags = 0;

    if (sigsetjmp(g_jb, 1) == 0) {
        g_armado = 1;
        sigaction(SIGSEGV, &nova, &g_velho_segv);
        sigaction(SIGBUS, &nova, &g_velho_bus);
        fn(&in, &g_servidor, &out);
        g_armado = 0;
        sigaction(SIGSEGV, &g_velho_segv, NULL);
        sigaction(SIGBUS, &g_velho_bus, NULL);
        return 0;
    }
    /* voltou de uma falha */
    g_armado = 0;
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
    snprintf(r->erro, sizeof r->erro, "FALHA (SIGSEGV/BUS) em %s", rotulo ? rotulo : "?");
    registrar("!! FALHA capturada em %s (alvo=%ld)", rotulo ? rotulo : "?", alvo);
    return -2;
}

/* ------------------------------------------- a tarefa na main thread ------- */

typedef struct {
    int tipo; /* 0=PING 1=SELECTION */
    char buf[256 * 1024];
    size_t len;
    dispatch_semaphore_t sem;
} Tarefa;

static void anexar(Tarefa *t, const char *fmt, ...) {
    if (t->len >= sizeof t->buf - 1) return;
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(t->buf + t->len, sizeof t->buf - t->len, fmt, ap);
    va_end(ap);
    if (n > 0) t->len += (size_t)n;
}

/* descreve um cid (nome/tipo/seg/trackgroup/len) numa linha do relatório */
static void descreve(Tarefa *t, const char *rotulo, int indice, int cid,
                     aro_fn Name, aro_fn Type, aro_fn IsSeg, aro_fn IsTG, aro_fn Length) {
    Resp r;
    char nome[512] = "";
    long tipo = -1, seg = -1, tg = -1, len = -1;
    if (chamar(Name, cid, &r, "GetName") == 0 && r.n_str > 0) snprintf(nome, sizeof nome, "%s", r.strs[0]);
    resp_limpar(&r);
    if (chamar(IsSeg, cid, &r, "IsSegment") == 0 && r.n_int > 0) seg = r.ints[0];
    resp_limpar(&r);
    if (chamar(IsTG, cid, &r, "IsTrackGroup") == 0 && r.n_int > 0) tg = r.ints[0];
    resp_limpar(&r);
    if (chamar(Type, cid, &r, "GetType") == 0 && r.n_int > 0) tipo = r.ints[0];
    resp_limpar(&r);
    if (chamar(Length, cid, &r, "GetLength") == 0 && r.n_int > 0) len = r.ints[0];
    resp_limpar(&r);
    anexar(t, "%s %d cid=%d seg=%ld tg=%ld type=%ld len=%ld name=\"%s\"\n",
           rotulo, indice, cid, seg, tg, tipo, len, nome);
}

static void fazer_selection(Tarefa *t) {
    g_objn = 0; /* zera o mapa a cada comando */
    Resp r;

    aro_fn Timeline = resolver("MediaComposerApp", "Timeline", VM_TIMELINE);
    if (chamar(Timeline, 0, &r, "Timeline") != 0 || r.n_obj < 1) {
        anexar(t, "ERR timeline %s\nEND\n", r.erro[0] ? r.erro : "sem objectID");
        resp_limpar(&r); return;
    }
    int idtl = r.objids[0];
    resp_limpar(&r);
    registrar("TL id=%d (ptr=%p)", idtl, g_objmap[idtl]);
    anexar(t, "TL id=%d\n", idtl);

    aro_fn NumSel = resolver("TimelineWindow", "GetNumSelComponents", VM_NUMSEL);
    if (chamar(NumSel, idtl, &r, "GetNumSelComponents") != 0) {
        anexar(t, "ERR numsel %s\nEND\n", r.erro); resp_limpar(&r); return;
    }
    int n = (r.n_int > 0) ? (int)r.ints[0] : -1;
    resp_limpar(&r);
    registrar("NUMSEL=%d", n);
    anexar(t, "NUMSEL %d\n", n);

    int cids[256];
    int ncomp = coletar_selecionados(idtl, cids, 256);   /* DIRETO, 1-based (conserta o off-by-one); compara com NUMSEL */
    registrar("GetSel direto: ncomp=%d (NUMSEL cru=%d)", ncomp, n);
    for (int i = 0; i < ncomp; i++)
        registrar("  [%d] cid=%d ptr=%p", i, cids[i], (cids[i] > 0 && cids[i] <= g_objn) ? g_objmap[cids[i]] : NULL);

    aro_fn Name = resolver("AComponent", "GetName", VM_NAME);
    aro_fn Type = resolver("AComponent", "GetType", VM_TYPE);
    aro_fn IsSeg = resolver("AComponent", "IsSegment", VM_ISSEG);
    aro_fn IsTG = resolver("AComponent", "IsTrackGroup", VM_ISTG);
    aro_fn Length = resolver("AComponent", "GetLength", VM_LENGTH);
    aro_fn Parent = resolver("AComponent", "GetParent", VM_PARENT);

    for (int i = 0; i < ncomp; i++) {
        int cid = cids[i];
        void *ptr = (cid > 0 && cid <= g_objn) ? g_objmap[cid] : NULL;
        if (!ptr) { anexar(t, "COMP i=%d cid=%d (ptr NULO, pulado)\n", i, cid); continue; }
        descreve(t, "COMP", i, cid, Name, Type, IsSeg, IsTG, Length);

        /* passeio pela árvore: segmento -> trilha -> sequência, p/ achar onde mora a identidade */
        int atual = cid;
        for (int nivel = 1; nivel <= 6; nivel++) {
            int rc = chamar(Parent, atual, &r, "GetParent");
            int pai = (r.n_obj > 0) ? r.objids[0] : 0;
            resp_limpar(&r);
            if (rc != 0 || pai <= 0) break;
            void *pp = (pai > 0 && pai <= g_objn) ? g_objmap[pai] : NULL;
            if (!pp) { anexar(t, "  PARENT nivel=%d cid=%d (ptr NULO)\n", nivel, pai); break; }
            descreve(t, "  PARENT", nivel, pai, Name, Type, IsSeg, IsTG, Length);
            atual = pai;
        }
    }
    anexar(t, "END\n");
}

/* despeja no relatório o que uma Resp capturou (ints, strings, objectIDs) */
static void dump_resp(Tarefa *t, const char *titulo, int rc, Resp *r) {
    if (rc == -2) { anexar(t, "%s: FALHA (%s)\n", titulo, r->erro); return; }
    if (rc == -1) { anexar(t, "%s: nao resolvida\n", titulo); return; }
    anexar(t, "%s: ints=%d strs=%d objids=%d%s%s\n", titulo, r->n_int, r->n_str, r->n_obj,
           r->erro[0] ? " erro=" : "", r->erro[0] ? r->erro : "");
    for (int i = 0; i < r->n_int; i++) anexar(t, "   int[%d]=%ld\n", i, r->ints[i]);
    for (int i = 0; i < r->n_str; i++) if (r->strs[i] && r->strs[i][0]) anexar(t, "   str[chave=%d]=\"%s\"\n", i, r->strs[i]);
    for (int i = 0; i < r->n_obj; i++) anexar(t, "   obj[%d]=%d\n", i, r->objids[i]);
}

/* experimento: enumerar trilhas e tentar GetMobProperty no segmento e na sequência */
static void fazer_probe(Tarefa *t) {
    g_objn = 0;
    Resp r;
    int rc;

    aro_fn Timeline = resolver("MediaComposerApp", "Timeline", VM_TIMELINE);
    if (chamar(Timeline, 0, &r, "Timeline") != 0 || r.n_obj < 1) { anexar(t, "ERR timeline\nEND\n"); resp_limpar(&r); return; }
    int idtl = r.objids[0];
    resp_limpar(&r);

    /* 1) enumerar as trilhas */
    aro_fn GetTracks = resolver("TimelineWindow", "GetTracks", VM_TRACKS);
    rc = chamar(GetTracks, idtl, &r, "GetTracks");
    dump_resp(t, "GetTracks", rc, &r);
    resp_limpar(&r);

    /* 2) a seleção -> primeiro cid válido + subir até a composição (tg=1) */
    aro_fn GetSel = resolver("TimelineWindow", "GetSelComponents", VM_GETSEL);
    if (chamar(GetSel, idtl, &r, "GetSelComponents") != 0) { anexar(t, "ERR getsel\nEND\n"); resp_limpar(&r); return; }
    int segCid = 0;
    for (int i = 0; i < r.n_obj; i++) {
        int c = r.objids[i];
        if (c > 0 && c <= g_objn && g_objmap[c]) { segCid = c; break; }
    }
    resp_limpar(&r);
    anexar(t, "segCid=%d\n", segCid);

    aro_fn IsTG = resolver("AComponent", "IsTrackGroup", VM_ISTG);
    aro_fn Parent = resolver("AComponent", "GetParent", VM_PARENT);
    int compCid = 0, atual = segCid;
    for (int nivel = 0; nivel < 8 && atual > 0; nivel++) {
        int tg = -1;
        if (chamar(IsTG, atual, &r, "IsTrackGroup") == 0 && r.n_int > 0) tg = r.ints[0];
        resp_limpar(&r);
        if (tg == 1) { compCid = atual; break; }
        rc = chamar(Parent, atual, &r, "GetParent");
        int pai = (r.n_obj > 0) ? r.objids[0] : 0;
        resp_limpar(&r);
        if (rc != 0 || pai <= 0 || pai > g_objn || !g_objmap[pai]) break;
        atual = pai;
    }
    anexar(t, "compCid=%d\n", compCid);

    aro_fn MobProp = resolver("AComposition", "GetMobProperty", VM_MOBPROP);
    aro_fn MobType = resolver("AComposition", "GetMobType", VM_MOBTYPE);

    /* 3) GetMobProperty/GetMobType no SEGMENTO — pedindo as chaves 0..63 (modo sonda) */
    g_probe_nkeys = 64;
    if (segCid > 0) {
        rc = chamar(MobType, segCid, &r, "MobType(seg)"); dump_resp(t, "MobType(seg)", rc, &r); resp_limpar(&r);
        rc = chamar(MobProp, segCid, &r, "MobProp(seg) chaves 0..63"); dump_resp(t, "MobProp(seg)", rc, &r); resp_limpar(&r);
    }
    /* 4) idem na COMPOSIÇÃO (a sequência) */
    if (compCid > 0) {
        rc = chamar(MobType, compCid, &r, "MobType(comp)"); dump_resp(t, "MobType(comp)", rc, &r); resp_limpar(&r);
        rc = chamar(MobProp, compCid, &r, "MobProp(comp) chaves 0..63"); dump_resp(t, "MobProp(comp)", rc, &r); resp_limpar(&r);
    }
    g_probe_nkeys = 0;
    anexar(t, "END\n");
}

/* TLP_GetAllLines com SelectedItemsOnly: o TEXTO de cada linha SELECIONADA da timeline (candidato a nome do clipe) */
static void fazer_tlp(Tarefa *t) {
    g_objn = 0;
    Resp r;
    int rc;
    aro_fn Timeline = resolver("MediaComposerApp", "Timeline", VM_TIMELINE);
    int idtl = 0;
    if (chamar(Timeline, 0, &r, "Timeline") == 0 && r.n_obj > 0) idtl = r.objids[0];
    resp_limpar(&r);
    anexar(t, "idtl=%d\n", idtl);

    aro_fn TLPall = resolver(NULL, "GetAllLines", VM_TLPALL);
    rc = chamar(TLPall, idtl, &r, "TLP_GetAllLines(SelectedItemsOnly)");
    dump_resp(t, "TLP_GetAllLines(selected)", rc, &r);
    resp_limpar(&r);

    /* e todas as linhas (sem filtro) p/ comparar — via TLP_GetLine 0..40 seria caro; deixo só o AllLines filtrado */
    anexar(t, "END\n");
}

/* roda uma função protegida por SIGSEGV/SIGBUS; *ret recebe o retorno int de fn; devolve 0 ok, -2 falha */
typedef int (*cmgmfs_t)(void *comp, void *outMobID, int *outPos, void **outComp);
static int protegido(cmgmfs_t fn, void *a0, void *a1, int *a2, void **a3, int *ret) {
    struct sigaction nova;
    memset(&nova, 0, sizeof nova);
    nova.sa_handler = ao_falhar;
    sigemptyset(&nova.sa_mask);
    nova.sa_flags = 0;
    if (sigsetjmp(g_jb, 1) == 0) {
        g_armado = 1;
        sigaction(SIGSEGV, &nova, &g_velho_segv);
        sigaction(SIGBUS, &nova, &g_velho_bus);
        int rr = fn(a0, a1, a2, a3);
        g_armado = 0;
        sigaction(SIGSEGV, &g_velho_segv, NULL);
        sigaction(SIGBUS, &g_velho_bus, NULL);
        if (ret) *ret = rr;
        return 0;
    }
    g_armado = 0;
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
    return -2;
}

/* AComposition::GetMobID() const -> _aafMCMobID_t por valor (32 bytes, sret); protegido */
typedef struct { unsigned char b[32]; } MobID32;
typedef MobID32 (*getmobid_t)(void *self);
static int protegido_gmid(getmobid_t fn, void *self, MobID32 *out) {
    struct sigaction nova;
    memset(&nova, 0, sizeof nova);
    nova.sa_handler = ao_falhar;
    sigemptyset(&nova.sa_mask);
    nova.sa_flags = 0;
    if (sigsetjmp(g_jb, 1) == 0) {
        g_armado = 1;
        sigaction(SIGSEGV, &nova, &g_velho_segv);
        sigaction(SIGBUS, &nova, &g_velho_bus);
        *out = fn(self);
        g_armado = 0;
        sigaction(SIGSEGV, &g_velho_segv, NULL);
        sigaction(SIGBUS, &g_velho_bus, NULL);
        return 0;
    }
    g_armado = 0;
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
    return -2;
}

/* TimelineWindow::GetSelComponent(short, int*) protegido por SIGSEGV/SIGBUS. */
typedef void *(*getselcomp_t)(void *tlwin, short i, int *out);
static int protegido_gsc(getselcomp_t fn, void *tlwin, short i, void **out) {
    struct sigaction nova;
    memset(&nova, 0, sizeof nova);
    nova.sa_handler = ao_falhar;
    sigemptyset(&nova.sa_mask);
    nova.sa_flags = 0;
    if (sigsetjmp(g_jb, 1) == 0) {
        g_armado = 1;
        sigaction(SIGSEGV, &nova, &g_velho_segv);
        sigaction(SIGBUS, &nova, &g_velho_bus);
        *out = fn(tlwin, i, NULL);
        g_armado = 0;
        sigaction(SIGSEGV, &g_velho_segv, NULL);
        sigaction(SIGBUS, &g_velho_bus, NULL);
        return 0;
    }
    g_armado = 0;
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
    return -2;
}

/* Coleta os AComponents selecionados chamando GetSelComponent(i) DIRETO, 1-based, até dar nulo — e registra
 * cada um (cids do g_objmap). Conserta o off-by-one de TLW_GetSelComponents (laço 0..N-1; i=0 só devolve algo
 * com 1 selecionado -> na multi-seleção perde o último). Devolve quantos coletou. */
static int coletar_selecionados(int idtl, int *cids, int max) {
    void *tlwin = (idtl > 0 && idtl <= g_objn) ? g_objmap[idtl] : NULL;
    if (!tlwin || !build_medido()) return 0;   /* GetSelComponent só tem endereço fixo */
    getselcomp_t GSC = (getselcomp_t)(VM_TW_GETSELCOMP + g_slide);
    int nc = 0;
    for (short i = 1; nc < max && i < (short)max; i++) {
        void *comp = NULL;
        if (protegido_gsc(GSC, tlwin, i, &comp) != 0) break;   /* falha capturada -> para */
        if (!comp) break;                                       /* fim da lista (1-based) */
        int id = 0;
        srv_RegisterObject(&g_servidor, "AComponent", comp, &id);
        if (id > 0) cids[nc++] = id;
    }
    return nc;
}

static void hex32(char *dst, const unsigned char *b) {
    int k = 0;
    for (int i = 0; i < 32; i++) k += sprintf(dst + k, "%02x", b[i]);
}

/* SRC: para cada segmento selecionado, a FONTE (identidade direta) por dois caminhos */
static void fazer_src(Tarefa *t) {
    g_objn = 0;
    Resp r;
    cmgmfs_t CMget = (cmgmfs_t)dlsym(RTLD_DEFAULT,
        "_Z21CMGetMatchFrameSourceP10AComponentP13_aafMCMobID_tPiPP12AComposition");
    getmobid_t GMID = (getmobid_t)dlsym(RTLD_DEFAULT, "_ZNK12AComposition8GetMobIDEv");
    anexar(t, "CMget=%p GetMobID=%p\n", (void *)CMget, (void *)GMID);

    aro_fn Timeline = resolver("MediaComposerApp", "Timeline", VM_TIMELINE);
    if (chamar(Timeline, 0, &r, "Timeline") != 0 || r.n_obj < 1) { anexar(t, "ERR timeline\nEND\n"); resp_limpar(&r); return; }
    int idtl = r.objids[0];
    resp_limpar(&r);

    aro_fn GetSel = resolver("TimelineWindow", "GetSelComponents", VM_GETSEL);
    if (chamar(GetSel, idtl, &r, "GetSelComponents") != 0) { anexar(t, "ERR getsel\nEND\n"); resp_limpar(&r); return; }
    int cids[256], nc = r.n_obj;
    for (int i = 0; i < nc; i++) cids[i] = r.objids[i];
    resp_limpar(&r);

    char hex[80];
    for (int i = 0; i < nc; i++) {
        int cid = cids[i];
        void *comp = (cid > 0 && cid <= g_objn) ? g_objmap[cid] : NULL;
        if (!comp) { anexar(t, "SRC i=%d cid=%d (ptr NULO)\n", i, cid); continue; }

        if (GMID) {
            MobID32 m; memset(&m, 0, sizeof m);
            int rc = protegido_gmid(GMID, comp, &m);
            if (rc == -2) anexar(t, "  GetMobID(seg) cid=%d FALHA\n", cid);
            else { hex32(hex, m.b); anexar(t, "  GetMobID(seg) cid=%d = %s\n", cid, hex); }
        }
        if (CMget) {
            unsigned char mob[64]; memset(mob, 0, sizeof mob);
            int pos = -123456; void *compout = NULL; int ret = -999;
            int rc = protegido(CMget, comp, mob, &pos, &compout, &ret);
            if (rc == -2) anexar(t, "  CMget cid=%d FALHA\n", cid);
            else { hex32(hex, mob); anexar(t, "  CMget cid=%d ret=%d pos=%d comp=%p = %s\n", cid, ret, pos, compout, hex);
                   if (compout && GMID) { MobID32 m2; memset(&m2,0,sizeof m2);
                       if (protegido_gmid(GMID, compout, &m2)==0){ hex32(hex,m2.b); anexar(t,"    GetMobID(compDaFonte)=%s\n",hex); } }
            }
        }
    }
    anexar(t, "END\n");
}

/* valida e emite o MobID CRU de 32 bytes (ordem interna do MC = o `bytes_le` do pyavb): tem de começar com o label
 * SMPTE `060a2b34` e ter material (bytes 16..31) não-zero (senão é título/filler sem fonte). A conversão de
 * endianness p/ a forma externa (URN) fica no Python (aro.py), via pyavb MobID(bytes_le=...). */
static int emite_mobid(const MobID32 *m, char *out64) {
    if (!(m->b[0] == 0x06 && m->b[1] == 0x0a && m->b[2] == 0x2b && m->b[3] == 0x34)) return 0;
    int material_zero = 1;
    for (int i = 16; i < 32; i++) if (m->b[i]) { material_zero = 0; break; }
    if (material_zero) return 0;
    hex32(out64, m->b);
    return 1;
}

/* O MASTER DENTRO DE UM EFEITO (2026-10-28, RE do libameLibrary 25.12 arm64): um segmento com efeito é um ATrackGroup
 * (tg=1) e o GetSrcMobID só vale num ASourceClip. `AComponent::VisitLinks(cb, ctx)` (exportado, por nome) chama o
 * virtual vtable[0x4b0](this, cb, ctx, nível=0, modo=2 = só os links/ASourceClip) e desce pelas trilhas de entrada —
 * efeitos EMPILHADOS inclusive. O callback é cb(ctx, nível, ASourceClip*): devolver 0 CONTINUA, ≠0 PARA (lido do
 * VisitComps1: `blr x21; cbnz w0, fim`). Cada ASourceClip achado dá o master pelo GetSrcMobID, como no segmento simples. */
typedef unsigned char (*visit_cb_t)(void *ctx, unsigned char nivel, void *sc);
typedef void (*visitlinks_t)(void *comp, visit_cb_t cb, void *ctx);
typedef struct { getmobid_t srcid; MobID32 mobs[64]; int n; int visitados; } Links;
static unsigned char ao_visitar_link(void *ctx, unsigned char nivel, void *sc) {
    (void)nivel;
    Links *l = ctx;
    l->visitados++;
    if (sc && l->n < 64) { l->mobs[l->n] = l->srcid(sc); l->n++; }
    return 0;  /* continua */
}
static int protegido_links(visitlinks_t fn, void *comp, Links *l) {
    struct sigaction nova;
    memset(&nova, 0, sizeof nova);
    nova.sa_handler = ao_falhar;
    sigemptyset(&nova.sa_mask);
    nova.sa_flags = 0;
    if (sigsetjmp(g_jb, 1) == 0) {
        g_armado = 1;
        sigaction(SIGSEGV, &nova, &g_velho_segv);
        sigaction(SIGBUS, &nova, &g_velho_bus);
        fn(comp, ao_visitar_link, l);
        g_armado = 0;
        sigaction(SIGSEGV, &g_velho_segv, NULL);
        sigaction(SIGBUS, &g_velho_bus, NULL);
        return 0;
    }
    g_armado = 0;
    sigaction(SIGSEGV, &g_velho_segv, NULL);
    sigaction(SIGBUS, &g_velho_bus, NULL);
    return -2;
}

/* SELMOB: a resposta para o app — SEQ (MobID da sequência) + um MOB (64 hex CRU) por segmento selecionado com fonte.
 * O MobID da FONTE do segmento vem de ASourceClip::GetSrcMobID (campo this+0x74, frame certo); o da sequência, de
 * AComposition::GetMobID na composição. Ambos na ordem interna; o Python converte com o pyavb. */
static void fazer_selmob(Tarefa *t) {
    g_objn = 0;
    Resp r;
    getmobid_t GMID = (getmobid_t)dlsym(RTLD_DEFAULT, "_ZNK12AComposition8GetMobIDEv");
    getmobid_t SRCID = (getmobid_t)dlsym(RTLD_DEFAULT, "_ZN11ASourceClip11GetSrcMobIDEv");
    if (!SRCID) { anexar(t, "ERR GetSrcMobID indisponivel\nEND\n"); return; }

    aro_fn Timeline = resolver("MediaComposerApp", "Timeline", VM_TIMELINE);
    if (chamar(Timeline, 0, &r, "Timeline") != 0 || r.n_obj < 1) { anexar(t, "ERR timeline\nEND\n"); resp_limpar(&r); return; }
    int idtl = r.objids[0];
    resp_limpar(&r);

    int cids[256];
    int nc = coletar_selecionados(idtl, cids, 256);   /* DIRETO, 1-based, até nulo — conserta o off-by-one do MC */

    aro_fn IsTG = resolver("AComponent", "IsTrackGroup", VM_ISTG);
    aro_fn Type = resolver("AComponent", "GetType", VM_TYPE);
    aro_fn Parent = resolver("AComponent", "GetParent", VM_PARENT);
    char hex[80];

    int primeiro = 0;
    for (int i = 0; i < nc; i++) { int c = cids[i]; if (c > 0 && c <= g_objn && g_objmap[c]) { primeiro = c; break; } }

    /* SEQ: subir até a SEQUÊNCIA e pegar seu MobID (GetMobID na composição vem no frame certo).
     * ⚠️ (2026-10-28, medido ao vivo) Um EFEITO também é grupo de trilhas (tg=1, type=1/2): parar no 1º tg=1 parava no
     * próprio segmento com efeito e a SEQ não saía. A sequência é o grupo com type=0 (SELECTION: "tg=1 type=0
     * name=PRODC_CORTE02", acima da trilha). */
    if (primeiro && GMID) {
        int atual = primeiro, comp = 0;
        for (int n = 0; n < 8 && atual > 0; n++) {
            int tg = -1, tipo = -1;
            if (chamar(IsTG, atual, &r, "IsTrackGroup") == 0 && r.n_int > 0) tg = r.ints[0];
            resp_limpar(&r);
            if (chamar(Type, atual, &r, "GetType") == 0 && r.n_int > 0) tipo = r.ints[0];
            resp_limpar(&r);
            if (tg == 1 && tipo == 0) { comp = atual; break; }
            int rc = chamar(Parent, atual, &r, "GetParent");
            int pai = (r.n_obj > 0) ? r.objids[0] : 0;
            resp_limpar(&r);
            if (rc != 0 || pai <= 0 || pai > g_objn || !g_objmap[pai]) break;
            atual = pai;
        }
        if (comp) {
            MobID32 m; memset(&m, 0, sizeof m);
            if (protegido_gmid(GMID, g_objmap[comp], &m) == 0 && emite_mobid(&m, hex)) anexar(t, "SEQ %s\n", hex);
        }
    }

    visitlinks_t VLINKS = (visitlinks_t)dlsym(RTLD_DEFAULT, "_ZN10AComponent10VisitLinksEPFhPvhP11ASourceClipES0_");
    int contados = 0;
    for (int i = 0; i < nc; i++) {
        int cid = cids[i];
        void *comp = (cid > 0 && cid <= g_objn) ? g_objmap[cid] : NULL;
        if (!comp) continue;
        int tg = -1;
        if (chamar(IsTG, cid, &r, "IsTrackGroup") == 0 && r.n_int > 0) tg = r.ints[0];
        resp_limpar(&r);
        if (tg != 1) {                                       /* segmento simples: o ASourceClip é ele */
            MobID32 m; memset(&m, 0, sizeof m);
            if (protegido_gmid(SRCID, comp, &m) != 0) continue;  /* ASourceClip::GetSrcMobID */
            if (emite_mobid(&m, hex)) { anexar(t, "MOB %s\n", hex); contados++; }
            continue;
        }
        /* efeito (um ou vários empilhados): os ASourceClip de dentro */
        if (!VLINKS) { anexar(t, "FX i=%d sem VisitLinks\n", i); continue; }
        Links l; memset(&l, 0, sizeof l); l.srcid = SRCID;
        if (protegido_links(VLINKS, comp, &l) != 0) { anexar(t, "FX i=%d FALHA\n", i); continue; }
        int bons = 0;
        for (int k = 0; k < l.n; k++)
            if (emite_mobid(&l.mobs[k], hex)) { anexar(t, "MOB %s\n", hex); contados++; bons++; }
        anexar(t, "FX i=%d links=%d masters=%d\n", i, l.visitados, bons);   /* diagnóstico; o Python ignora */
    }
    anexar(t, "COUNT %d\nEND\n", contados);
}

static void na_main(void *p) {
    Tarefa *t = p;
    if (t->tipo == 5) { registrar("SELMOB na main? %d", pthread_main_np() ? 1 : 0); fazer_selmob(t); dispatch_semaphore_signal(t->sem); return; }
    if (t->tipo == 4) { registrar("SRC na main? %d", pthread_main_np() ? 1 : 0); fazer_src(t); dispatch_semaphore_signal(t->sem); return; }
    if (t->tipo == 3) { registrar("TLP na main? %d", pthread_main_np() ? 1 : 0); fazer_tlp(t); dispatch_semaphore_signal(t->sem); return; }
    if (t->tipo == 2) { registrar("PROBE na main? %d", pthread_main_np() ? 1 : 0); fazer_probe(t); dispatch_semaphore_signal(t->sem); return; }
    if (t->tipo == 0) {
        anexar(t, "PONG main=%d slide=%#lx classes=%d\nEND\n", pthread_main_np() ? 1 : 0, g_slide, g_nclasses);
    } else {
        registrar("SELECTION: na main? %d, classes=%d", pthread_main_np() ? 1 : 0, g_nclasses);
        fazer_selection(t);
    }
    dispatch_semaphore_signal(t->sem);
}

/* ------------------------------------------------------- o socket ---------- */

static int g_port = 17890;

static void atender(int c) {
    char linha[1024];
    ssize_t k = recv(c, linha, sizeof linha - 1, 0);
    if (k <= 0) return;
    linha[k] = 0;
    char *nl = strpbrk(linha, "\r\n");
    if (nl) *nl = 0;
    registrar("comando: \"%s\"", linha);

    Tarefa *t = calloc(1, sizeof *t);
    t->sem = dispatch_semaphore_create(0);
    if (strcmp(linha, "PING") == 0) t->tipo = 0;
    else if (strcmp(linha, "SELECTION") == 0) t->tipo = 1;
    else if (strcmp(linha, "PROBE") == 0) t->tipo = 2;
    else if (strcmp(linha, "TLP") == 0) t->tipo = 3;
    else if (strcmp(linha, "SRC") == 0) t->tipo = 4;
    else if (strcmp(linha, "SELMOB") == 0) t->tipo = 5;
    else { dprintf(c, "ERR comando desconhecido\nEND\n"); dispatch_release(t->sem); free(t); return; }
    /* ⚠️ (revisão 2026-10-28) As SONDAS do laboratório (PROBE/TLP/SRC) chamam função de contexto-do-dispatcher; o TLP
     * pode derrubar o MC (exceção C++ que a captura de SIGSEGV não segura — banco, arrastar.md). Na dylib que o app
     * instala, qualquer programa local as dispararia: só com o MC aberto com ARO_LAB=1 (apps.abrir("avid", {...})). */
    if (t->tipo >= 2 && t->tipo <= 4 && !getenv("ARO_LAB")) {
        dprintf(c, "ERR sonda de laboratorio (abra o MC com ARO_LAB=1)\nEND\n"); dispatch_release(t->sem); free(t); return;
    }

    dispatch_async_f(dispatch_get_main_queue(), t, na_main);
    long esgotou = dispatch_semaphore_wait(t->sem, dispatch_time(DISPATCH_TIME_NOW, 15LL * NSEC_PER_SEC));
    if (esgotou) {
        registrar("TIMEOUT: a main nao respondeu em 15 s (fila principal nao bombeada?)");
        dprintf(c, "ERR timeout main\nEND\n");
        /* o bloco ainda pode rodar depois; o Tarefa vaza de propósito (evita use-after-free) */
        return;
    }
    send(c, t->buf, t->len, 0);
    dispatch_release(t->sem);
    free(t);
}

static void *servir(void *_) {
    (void)_;
    const char *p = getenv("ARO_PORT");
    if (p) g_port = atoi(p);
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) { registrar("socket() falhou"); return NULL; }
    /* ⚠️ (revisão 2026-10-28, medido) Sem FD_CLOEXEC o socket VAZA para os filhos do MC: o `avid-api-gateway` herdou
     * a escuta (e o log), ficou órfão quando o MC fechou e segurou a 17890 por dias sem aceitar ninguém — quem
     * conectava esperava o prazo inteiro. E sem SO_REUSEPORT: com ele, QUALQUER programa local abria a mesma porta
     * depois e levava todas as conexões (no macOS ganha o último a abrir). SO_REUSEADDR basta para o TIME_WAIT. */
    fcntl(s, F_SETFD, FD_CLOEXEC);
    int yes = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof yes);
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    a.sin_port = htons((uint16_t)g_port);
    /* retry: depois de um crash do MC a porta pode ficar em TIME_WAIT por alguns segundos */
    int ok = 0;
    for (int tent = 0; tent < 30; tent++) {
        if (bind(s, (struct sockaddr *)&a, sizeof a) == 0) { ok = 1; break; }
        if (tent == 0) registrar("bind(%d) ocupada; tentando de novo...", g_port);
        sleep(1);
    }
    if (!ok) { registrar("bind(%d) falhou apos 30 tentativas", g_port); close(s); return NULL; }
    listen(s, 4);
    registrar("escutando em 127.0.0.1:%d", g_port);
    for (;;) {
        int c = accept(s, NULL, NULL);
        if (c < 0) continue;
        fcntl(c, F_SETFD, FD_CLOEXEC);
        /* um cliente que conecta e não manda nada não prende o canal (o servidor atende um por vez) */
        struct timeval prazo = { .tv_sec = 2, .tv_usec = 0 };
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &prazo, sizeof prazo);
        atender(c);
        close(c);
    }
    return NULL;
}

/* ----------------------------------------------------- carregamento -------- */

static void sobrescrever_slots(void) {
    srv_vtable[2] = (void *)srv_Start;
    srv_vtable[9] = (void *)srv_RegisterClass;
    srv_vtable[14] = (void *)srv_RegisterObject;
    srv_vtable[15] = (void *)srv_LookupObject;
    srv_vtable[32] = (void *)srv_ProcessPending;

    in_vtable[2] = (void *)in_NumArgs;
    in_vtable[14] = (void *)in_BoolArg;
    in_vtable[15] = (void *)in_GetKey;
    in_vtable[35] = (void *)in_GetAlvo;
    in_vtable[38] = (void *)in_Fim;

    out_vtable[2] = (void *)out_AddBool;
    out_vtable[3] = (void *)out_AddInt;
    out_vtable[11] = (void *)out_AddString;
    out_vtable[13] = (void *)out_AddObjID;
    out_vtable[14] = (void *)out_AddEnum;
    out_vtable[17] = (void *)out_Finish;
    out_vtable[20] = (void *)out_AddError;
}

__attribute__((constructor)) static void ao_carregar(void) {
    g_slide = calcular_slide();
    g_servidor.vtable = srv_vtable;
    sobrescrever_slots();
    pthread_t th;
    pthread_create(&th, NULL, servir, NULL);
    pthread_detach(th);
    registrar("======== servidor do ARO carregado (passo 2; slide=%#lx) ========", g_slide);
}

__attribute__((visibility("default"))) int ARO_VersionNumber(void) {
    registrar("ARO_VersionNumber() -> %d", ARO_VERSAO);
    return ARO_VERSAO;
}
__attribute__((visibility("default"))) int ARO_Init(void **servidor_saida) {
    registrar("ARO_Init(%p) -> 0 (ACEITA; devolvo o servidor %p)", (void *)servidor_saida, (void *)&g_servidor);
    if (servidor_saida) *servidor_saida = &g_servidor;
    return 0;
}
__attribute__((visibility("default"))) int ARO_Release(void *servidor) {
    registrar("ARO_Release(%p)", servidor);
    return 0;
}
