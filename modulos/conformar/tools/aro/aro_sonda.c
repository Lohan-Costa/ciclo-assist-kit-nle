/*
 * Sonda do ARO — passo 1.5: o SERVIDOR-ESCUTA (De Lá Pra Cá, 2026-10-25, só laboratório).
 *
 * Contexto: o Media Composer tem um servidor interno de automação de testes (ARO, "AvidRemoteObjects"), usado pela
 * própria Avid (o harness AvidSatin). O transporte é uma biblioteca que a Avid não distribui, carregada por um
 * caminho fixo em toda abertura do MC. Esta é a nossa, escrita para o nosso app ler da timeline o que a API pública
 * (gRPC 9100) não dá — a SELEÇÃO de segmentos. É interoperabilidade com o mecanismo de teste do próprio MC, no
 * projeto de laboratório.
 *
 * Passo 1 (provado): o MC carrega a dylib e chama ARO_VersionNumber / ARO_Init / ARO_Release.
 * Passo 1.5 (aqui): ARO_Init ACEITA e devolve um objeto-servidor cujo vtable é feito de ESCUTAS — cada método só
 *   registra o índice chamado e os argumentos, e devolve 0. Assim o MC dirige o servidor e CONFIRMA em execução os
 *   índices lidos no binário (banco, avid-panel-sdk/arrastar.md §"O contrato do ARO"):
 *     vtable[2]  Start(porta, flag)           0 = sucesso → o MC segue
 *     vtable[9]  RegisterClass(nome, mãe, métodos)   chamado uma vez por classe (TimelineWindow, Bin, …)
 *     vtable[14] RegisterObject · [15] LookupObject
 *     vtable[32] ProcessPendingRequest        no QTimer de 10 ms (silenciado após as primeiras)
 *   NADA de comportamento real ainda — só a confirmação do contrato. O servidor de verdade vem depois.
 *
 * Log: ~/Library/Logs/DeLaPraCa/aro_sonda.log. Compilar: tools/aro/compilar.sh (gera aro_stubs.h).
 */

#include <mach-o/dyld.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define ARO_VERSAO 2025
#define N_SLOTS 128

static FILE *g_log = NULL;
static pthread_mutex_t g_log_mx = PTHREAD_MUTEX_INITIALIZER;
static long g_slide = 0;        /* deslocamento do executável principal (ASLR): RA_real = offset_do_arquivo + slide */

static void registrar(const char *fmt, ...) {
    pthread_mutex_lock(&g_log_mx);
    if (!g_log) {
        char caminho[1024];
        const char *lar = getenv("HOME");
        snprintf(caminho, sizeof caminho, "%s/Library/Logs/DeLaPraCa/aro_sonda.log", lar ? lar : "/tmp");
        g_log = fopen(caminho, "a");
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

/* Um ponteiro parece estar no espaço de código/dados carregado? (evita tratar um inteiro, como a porta, como texto) */
static int parece_ponteiro(long v) {
    return v > 0x100000000L && v < 0x280000000L;
}

/* O endereço do executável PRINCIPAL (índice 0) menos o vmaddr base (0x100000000): o slide de ASLR. */
static long calcular_slide(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        if (_dyld_get_image_header(i)->filetype == 2 /* MH_EXECUTE */)
            return _dyld_get_image_vmaddr_slide(i);
    }
    return 0;
}

static int g_contagem[N_SLOTS];

/* O coração da escuta: todo método do vtable do servidor cai aqui, com o seu índice. */
long aro_escuta(int idx, long a0, long a1, long a2, long a3, void *ra) {
    long off = g_slide ? ((long)ra - g_slide) : (long)ra;   /* offset no arquivo do MC (p/ cruzar com a desmontagem) */
    int n = (idx >= 0 && idx < N_SLOTS) ? g_contagem[idx]++ : 99;

    if (idx == 2) {                       /* Start(this, porta, flag) */
        registrar("vtable[2] Start(porta=%ld, flag=%ld)  [chamado de +%#lx] -> devolvo 0 (sucesso)", a1, a2, off);
    } else if (idx == 9) {                /* RegisterClass(this, nome, mãe, métodos) */
        const char *nome = parece_ponteiro(a1) ? (const char *)a1 : "?";
        const char *mae = parece_ponteiro(a2) ? (const char *)a2 : "?";
        registrar("vtable[9] RegisterClass(nome=\"%s\", mae=\"%s\", metodos=%#lx)", nome, mae, a3);
    } else if (idx == 32) {               /* ProcessPendingRequest — no timer; só as primeiras */
        if (n < 3) registrar("vtable[32] ProcessPendingRequest()  [+%#lx]%s", off, n == 2 ? "  (silenciando as próximas)" : "");
    } else if (n < 3) {                   /* os demais: as 3 primeiras de cada índice, com os argumentos crus */
        registrar("vtable[%d](%#lx, %#lx, %#lx, %#lx)  [+%#lx]", idx, a0, a1, a2, a3, off);
    }
    return 0;
}

#include "aro_stubs.h"   /* gerado por compilar.sh: aro_slot_0..127 e aro_vtable[128] */

/* O objeto-servidor: [0] = ponteiro para o vtable; o resto é espaço para os campos que o MC lê/escreve
 * (ex.: os dois ponteiros de printf em +0x8/+0x10). Zerado — o MC acha 0 e deixa 0. */
static struct {
    void *vtable;
    char resto[0x400];
} g_servidor;

__attribute__((constructor))
static void ao_carregar(void) {
    g_slide = calcular_slide();
    g_servidor.vtable = aro_vtable;
    registrar("================ sonda do ARO carregada (passo 1.5: servidor-escuta; slide=%#lx) ================", g_slide);
}

__attribute__((visibility("default")))
int ARO_VersionNumber(void) {
    registrar("ARO_VersionNumber() -> %d", ARO_VERSAO);
    return ARO_VERSAO;
}

__attribute__((visibility("default")))
int ARO_Init(void **servidor_saida) {
    registrar("ARO_Init(%p) -> 0 (ACEITA; devolvo o servidor-escuta %p)", (void *)servidor_saida, (void *)&g_servidor);
    if (servidor_saida) *servidor_saida = &g_servidor;
    return 0;
}

__attribute__((visibility("default")))
int ARO_Release(void *servidor) {
    registrar("ARO_Release(%p)", servidor);
    return 0;
}
