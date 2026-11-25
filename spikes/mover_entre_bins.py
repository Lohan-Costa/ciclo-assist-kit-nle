"""Mover um item de uma bin para outra — dá, e por onde?

    python spikes/mover_entre_bins.py           # só o que o pyavb diz, NÃO toca no MC
    python spikes/mover_entre_bins.py --abrir   # põe o Media Composer a julgar

⛔ **Não existe comando.** `DoCommand` é sem-parâmetro (não diz qual item nem para onde) e
`SetMobInfo` só edita COLUNA de bin, não a pertença — banco,
`plugins/avid-panel-sdk/dados/docommand-comandos.md` §A FRONTEIRA. Premiere tem
`item_move_to_bin`, Resolve tem `MediaPool.MoveClips`; o Media Composer, nada.

Sobra a autoria de `.avb`, e o gesto tem DOIS lados com riscos diferentes:

| lado | o que era sabido antes deste spike |
|---|---|
| **PÔR** numa bin que já existe | ✅ `CloseBin` → pyavb → `os.replace` → `OpenBin` (2026-09-11) |
| **TIRAR** da bin de origem | ⛔ nunca medido — buraco 12 de `transversal/operacoes-de-nle.md` |

⛔⛔ **E o que torna isto mais que um `add_mob`:** a timeline desta bin aponta TRÊS
subclipes, e subclipe é objeto de BIN, não de mídia — não está no `msmMMOB.mdb` e não há
por onde resolvê-lo fora da bin. Entregar a timeline pelada derruba o Media Composer com
`ACCESS_VIOLATION` ao CARREGAR (a bin abre e lista tudo certo antes de cair; medido
2026-08-30, `protocolos/avb/escrita.md`). Mover é mover o **fecho**, oculto.

⚠️ As bins de trabalho são CÓPIAS com `Bin.uid` novo. As três bins de fixture do editor
não são escritas em momento nenhum — uid preservado só vale para ATUALIZAR a bin dele.

## O QUE ISTO MEDIU (2026-09-12, MC 2025.6.58781)

| | |
|---|---|
| **TIRAR** o `BinItem` | ✅ 96 → 95 itens, o MobID some, o resto relê intacto |
| **PÔR** numa bin nova (clone + poda) | ✅ 40 itens, 1 visível, fecho inteiro |
| **PÔR** numa bin existente | ✅ `AVBObject.copy(root)`; o `add_mob` cru é recusado no WRITE |
| **o veredito na TELA** | ⛔ bloqueado — ver abaixo |

⚠️⚠️ **CORRIGIDO em 2026-09-13** (`spikes/a_bin_ama_regravada.py`): o culpado não é o mob
AMA, é o caminho UTF-8 NULO (`ff ff`) nos dois `WinFileLocator` desta fixture, que o pyavb
regravava como vazio (`00 00`). Bins AMA de caminho preenchido regravam e abrem. O conserto
está em `cicloassist/avid/avb_fiel.py`, e com ele esta fixture passa a abrir. O texto
abaixo fica como estava, porque foi o que se mediu naquele dia.

⛔⛔ **E o achado que valeu mais que o spike:** nenhuma bin derivada desta fixture abre no
Media Composer, com uid novo OU preservado, com a mesa vazia. Bisseção em 11 tentativas: o
culpado é **um `SourceMob` de fita com `locator = WinFileLocator`** (mob AMA — os *sound
rolls* dos WAV). Só os 2 → recusa; os outros 94 → abre. A cópia CRUA do arquivo abre.

⇒ `FILE_OPEN_FAILURE` tem **três** causas conhecidas agora, com a mesma frase — e a
primeira hipótese que alguém testar vai "explicar" o sintoma e parar a investigação.

⭐ O produto não tropeça nisso porque a bin dele (`CENAS/C07.avb`) tem 19 mobs de fita e
**nenhum com locator**: mídia gerenciada não tem. Antes de escrever numa bin do editor,
pergunte — é o que `tem_mob_ama()` faz aqui embaixo.
"""

from __future__ import annotations

import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402
from avb.core import walk_references  # noqa: E402

from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR")

#: As fixtures do editor (2026-09-12, 22:47). ⛔ SOMENTE LEITURA.
FIXTURE_ORIGEM = PROJETO / "BIN ORIGEM.avb"
FIXTURE_DESTINO = PROJETO / "BIN DESTINO - com arquivo.avb"

#: As bins de trabalho, que este spike escreve e reescreve à vontade.
ORIGEM = PROJETO / "_MOVER ORIGEM.avb"
DESTINO_NOVO = PROJETO / "_MOVER DESTINO NOVO.avb"
DESTINO_EXISTENTE = PROJETO / "_MOVER DESTINO EXISTENTE.avb"

#: O item a mover: uma timeline que aponta subclipes — o caso que derruba o MC se o fecho
#: ficar para trás. Mover um masterclipe seria o caso FÁCIL (master resolve pelo banco de
#: mídia), e um spike que mede o caso fácil não mede nada.
ITEM = "C07_F03 - opcoes (Personagem G - Alem disso)"

#: O que já estava na bin de destino — é nele que uma colisão de `instance_id` apareceria.
JA_ESTAVA = "C04_P03-T001"


def e_nulo(mob_id: str) -> bool:
    """⚠️ CONTROLE MEDIDO: o fecho da timeline na fixture INTOCADA já aponta um MobID de
    material number todo zero (`…060e2b34.7f7f2a80.00000000.00000000`). Não é referência
    quebrada — é o idioma AVB para "a cadeia acaba aqui", e contá-la como falta faria toda
    medição reprovar por um defeito que não existe. Quem for medir integridade de bin
    precisa deste controle ANTES de acreditar no próprio verificador.
    """
    return mob_id.endswith("00000000.00000000")


def sem_dono(indice: dict, raiz) -> list[str]:
    return [k for k, v in fecho(indice, raiz).items() if v is None and not e_nulo(k)]


def tem_mob_ama(f) -> list[str]:
    """Os mobs que fazem o `write()` do pyavb condenar a bin inteira.

    ⛔⛔ Um único deles basta: o `OpenBin` recusa com `FILE_OPEN_FAILURE`, que é a MESMA
    frase de `Bin.uid` repetido e de bin aberta reescrita por baixo. Três causas, uma
    mensagem — por isso a conferência tem de ser explícita, e ANTES de escrever.
    """
    fora = []
    for i in f.content.items:
        d = getattr(i.mob, "descriptor", None)
        if type(getattr(d, "locator", None)).__name__ == "WinFileLocator":
            fora.append(i.mob.name or "(sem nome)")
    return fora


def visiveis(f) -> list[str]:
    return [i.mob.name or "(sem nome)" for i in f.content.items if i.user_placed]


def indexar(f) -> dict:
    return {str(i.mob.mob_id): i.mob for i in f.content.items}


def fecho(indice: dict, raiz) -> dict:
    """Todo mob que `raiz` precisa, transitivamente, pelos `SourceClip`.

    ⚠️ `SourceClip` aponta por **MobID**, que é VALOR, não referência de objeto: o
    `walk_references` do pyavb não atravessa isso. Quem não resolver o MobID à mão acha
    que a timeline não depende de nada — e escreve uma bin que abre e derruba o MC depois.
    """
    pendentes, achados = [raiz], {}
    while pendentes:
        atual = pendentes.pop()
        for o in walk_references(atual):
            if type(o).__name__ != "SourceClip":
                continue
            mid = str(o.mob_id)
            if mid in achados:
                continue
            alvo = indice.get(mid)
            achados[mid] = alvo
            if alvo is not None:
                pendentes.append(alvo)
    return achados


def copiar_com_uid_novo(fixture: Path, trabalho: Path) -> None:
    """Cópia de trabalho. ⭐ `Bin.uid` NOVO: é bin DERIVADA, não a bin do editor.

    Com o uid da origem, o `OpenBin` de uma segunda bin igual devolve `FILE_OPEN_FAILURE`
    enquanto a primeira estiver aberta na sessão — e a mensagem não fala de uid nenhum
    (banco, 2026-08-16).
    """
    shutil.copy2(fixture, trabalho)
    lado = trabalho.with_suffix(".avb.novo")
    with avb.open(str(trabalho)) as f:
        f.content.uid = random.getrandbits(63)
        f.write(str(lado))
    lado.replace(trabalho)


def medicao_1_tirar():
    """Tirar o `BinItem` e o arquivo continuar coerente."""
    print("\n" + "=" * 78)
    print("MEDIÇÃO 1 — TIRAR o item da bin de origem (o buraco 12)")
    print("=" * 78)

    copiar_com_uid_novo(FIXTURE_ORIGEM, ORIGEM)
    with avb.open(str(ORIGEM)) as f:
        antes_itens, antes_vis = len(f.content.items), visiveis(f)
    print(f"antes ....... {antes_itens} itens, {len(antes_vis)} visíveis")

    lado = ORIGEM.with_suffix(".avb.novo")
    with avb.open(str(ORIGEM)) as f:
        alvo = [i for i in f.content.items if (i.mob.name or "") == ITEM]
        if not alvo:
            return False, f"não achei {ITEM!r} na bin de origem"
        mob_id_removido = str(alvo[0].mob.mob_id)
        # ⭐ É só isto: `content.items` é lista comum e `add_mob` só faz append. O mob em si
        #   deixa de ser alcançável a partir do `content`, e o writer — que escreve andando
        #   pelas referências — simplesmente não o grava.
        f.content.items.remove(alvo[0])
        f.write(str(lado))
    lado.replace(ORIGEM)

    with avb.open(str(ORIGEM)) as f:
        depois_itens, depois_vis = len(f.content.items), visiveis(f)
        ainda_la = mob_id_removido in indexar(f)
    print(f"depois ...... {depois_itens} itens, {len(depois_vis)} visíveis")
    print(f"            - {antes_itens - depois_itens} item(ns), "
          f"{ORIGEM.stat().st_size} bytes")
    print(f"o mob saiu .. {not ainda_la}")
    sumiu = set(antes_vis) - set(depois_vis)
    print(f"deixou de aparecer: {sorted(sumiu)}")

    ok = depois_itens == antes_itens - 1 and not ainda_la and sumiu == {ITEM}
    return ok, ("pyavb relê sem o item e com o resto no lugar" if ok
                else "a bin saiu diferente do esperado")


def medicao_2_bin_nova():
    """PÔR numa bin NOVA sem copiar objeto entre arquivos: clonar o arquivo e PODAR.

    ⭐⭐ O truque que dispensa a parte perigosa. O fecho da timeline já vive dentro da bin
    de origem, coerente e com os `instance_id` daquele arquivo. Clonando o ARQUIVO e
    apagando os `BinItem` que não interessam, a bin de destino nasce com a timeline e as
    dependências dela — e nada atravessou fronteira de arquivo.
    """
    print("\n" + "=" * 78)
    print("MEDIÇÃO 2 — PÔR numa bin NOVA, por clone + poda (sem cópia entre arquivos)")
    print("=" * 78)

    copiar_com_uid_novo(FIXTURE_ORIGEM, DESTINO_NOVO)
    lado = DESTINO_NOVO.with_suffix(".avb.novo")
    with avb.open(str(DESTINO_NOVO)) as f:
        indice = indexar(f)
        alvo = next((i for i in f.content.items if (i.mob.name or "") == ITEM), None)
        if alvo is None:
            return False, f"não achei {ITEM!r}"
        preciso = {k for k, v in fecho(indice, alvo.mob).items() if v is not None}
        print(f"fecho ....... {len(preciso)} mob(s) que a timeline precisa")

        # ⛔ O que a bin MOSTRA é `user_placed`; o que ela CONTÉM é o item existir. O fecho
        #   viaja OCULTO — e isso não é cosmética: o `matchframe` do editor aponta para a
        #   bin em que o clipe NÃO está oculto, ou seja, a bin onde ele o organizou.
        guardados, jogados = 0, 0
        for i in list(f.content.items):
            mid = str(i.mob.mob_id)
            if i is alvo:
                i.user_placed = True
                guardados += 1
            elif mid in preciso:
                i.user_placed = False
                guardados += 1
            else:
                f.content.items.remove(i)
                jogados += 1
        print(f"mantidos .... {guardados} · jogados fora {jogados}")
        f.write(str(lado))
    lado.replace(DESTINO_NOVO)

    with avb.open(str(DESTINO_NOVO)) as f:
        vis = visiveis(f)
        indice = indexar(f)
        alvo = next((i.mob for i in f.content.items if (i.mob.name or "") == ITEM), None)
        faltando = sem_dono(indice, alvo) if alvo else ["não achei a timeline"]
    print(f"relido ...... {len(indice)} itens, visíveis={vis}")
    print(f"tamanho ..... {DESTINO_NOVO.stat().st_size} bytes")
    print(f"referência sem dono: {len(faltando)}")

    ok = vis == [ITEM] and not faltando
    return ok, ("a bin nova tem a timeline visível e o fecho inteiro, oculto" if ok
                else f"ficou referência sem dono: {faltando}")


def medicao_3_bin_existente():
    """PÔR numa bin que JÁ TEM coisa — aqui o objeto atravessa arquivo, e é o risco real.

    ⚠️ Previsão lendo o writer do pyavb (`avb/file.py:348`): ele anda por
    `walk_references(self.content)` e indexa por `instance_id`, que é o índice do objeto
    NAQUELE arquivo. Dois arquivos numeram de 1 a N, então os `instance_id` COLIDEM — e o
    laço tem um `if obj.instance_id in self.ref_mapping: continue`. O segundo objeto com o
    mesmo número não é escrito, e quem o referenciava passa a apontar o primeiro.
    ⇒ Isso não levanta erro. Produz bin plausível e errada.
    """
    print("\n" + "=" * 78)
    print("MEDIÇÃO 3 — PÔR numa bin EXISTENTE (objeto atravessando arquivo)")
    print("=" * 78)

    copiar_com_uid_novo(FIXTURE_DESTINO, DESTINO_EXISTENTE)
    with avb.open(str(DESTINO_EXISTENTE)) as f:
        print(f"destino ..... {len(f.content.items)} itens, visíveis={visiveis(f)}")

    lado = DESTINO_EXISTENTE.with_suffix(".avb.novo")
    erro = ""
    # ⚠️ Leio o item da FIXTURE, não da `_MOVER ORIGEM`: aquela já perdeu a timeline na
    #    medição 1 — que é, afinal, o que "mover" significa.
    with avb.open(str(FIXTURE_ORIGEM)) as origem, \
            avb.open(str(DESTINO_EXISTENTE)) as destino:
        indice = indexar(origem)
        alvo = next((i.mob for i in origem.content.items
                     if (i.mob.name or "") == ITEM), None)
        precisos = {k: v for k, v in fecho(indice, alvo).items() if v is not None}

        usados_destino = {o.instance_id for o in walk_references(destino.content)
                          if hasattr(o, "instance_id")}
        a_copiar = {o.instance_id for o in walk_references(alvo)
                    if hasattr(o, "instance_id")}
        print(f"objetos no destino .. {len(usados_destino)}")
        print(f"objetos da timeline . {len(a_copiar)}")
        print(f"instance_id que COLIDEM: {len(usados_destino & a_copiar)}")

        # ⛔ `add_mob(mob_de_outro_arquivo)` é RECUSADO, e graças a deus: o writer confere
        #    `self.octx != obj.root.octx` e levanta
        #    `ValueError: object is from different file` (`avb/file.py:328`).
        #    ⚠️ Sem essa guarda o estrago seria silencioso — medido aqui: 21 `instance_id`
        #    da timeline COLIDEM com os do destino, e o writer indexa por `instance_id`
        #    com um `continue` em cima do repetido. Bin plausível, referências trocadas.
        #    ⚠️⚠️ E a guarda dispara no **write**, NÃO no `add_mob`: pendurar o mob de outro
        #    arquivo no conteúdo é aceito calado. Quem sondar só o `add_mob` conclui que
        #    funciona.
        sonda = lado.with_suffix(".sonda")
        destino.content.add_mob(alvo)
        try:
            destino.write(str(sonda))
            print("add_mob cru ......... ⚠️ PASSOU — a guarda do pyavb mudou, reconferir")
        except ValueError as e:
            print(f"add_mob cru ......... recusado no WRITE: {e}")
        finally:
            sonda.unlink(missing_ok=True)
            destino.content.items.pop()

        # ⭐⭐ O caminho certo estava no pyavb desde sempre: `AVBObject.copy(root)`
        #    (`avb/core.py:206`) recria o objeto no OUTRO arquivo, recursivamente, e o
        #    `root.create.from_name` dá `instance_id` novo a cada um — que é justamente o
        #    que desarma a colisão. É o *CAPTURE-REUSE* que o banco descrevia como
        #    mecanismo a portar, e não precisa ser portado.
        #    ⚠️ O `mob_id` NÃO é objeto AVB, então o `copy` o preserva por valor: a cópia é
        #    o MESMO clipe morando noutra bin, e não um clipe novo parecido.
        try:
            destino.content.add_mob(alvo.copy(destino)).user_placed = True
            for m in precisos.values():
                destino.content.add_mob(m.copy(destino)).user_placed = False
            destino.write(str(lado))
            print("copy() ............. ESCREVEU sem levantar erro")
        except Exception as e:      # noqa: BLE001 — é exatamente o que se quer medir
            erro = f"{type(e).__name__}: {e}"
            print(f"copy() ............. RECUSOU: {erro}")

    if erro:
        lado.unlink(missing_ok=True)
        return False, f"cópia entre arquivos não passa direto — {erro}"

    lado.replace(DESTINO_EXISTENTE)
    with avb.open(str(DESTINO_EXISTENTE)) as f:
        vis = visiveis(f)
        indice = indexar(f)
        alvo = next((i.mob for i in f.content.items if (i.mob.name or "") == ITEM), None)
        faltando = sem_dono(indice, alvo) if alvo else ["não achei a timeline"]
        # ⛔ O item que JÁ ESTAVA na bin é onde a colisão apareceria: se uma referência
        #   dele passou a apontar objeto de outro mob, ele ficou silenciosamente errado.
        antigo = next((i.mob for i in f.content.items
                       if (i.mob.name or "") == JA_ESTAVA), None)
        antigo_ok = antigo is not None and not sem_dono(indice, antigo)
    print(f"relido ...... {len(indice)} itens, visíveis={vis}")
    print(f"a timeline movida tem o fecho inteiro: {not faltando}")
    print(f"o item que já estava na bin continua coerente: {antigo_ok}")

    ok = not faltando and antigo_ok and ITEM in vis
    return ok, ("escreveu e releu coerente" if ok else "releu INCOERENTE (ver acima)")


#: O segundo item a mover, na medição 4 — a outra timeline da bin.
ITEM_2 = "C07_F04 - opcoes (Personagem F - O que voce pedindo)"


def fechar(mc, caminho: Path) -> None:
    """`CloseBin`, e o erro de bin já fechada é o caso NORMAL — ignorar.

    ⚠️ É operação de ARQUIVO: o MC grava a bin inteira ao fechar. Teto de dezenas de
    segundos, nunca o de consulta (banco: um `DEADLINE_EXCEEDED` aqui já fez um chamador
    concluir "não fecha" e gravar com outro nome — duas bins, nenhum erro).
    """
    try:
        mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S,
                   bin_path=mc.caminho_relativo_da_bin(str(caminho)))
    except Exception:   # noqa: BLE001
        pass


def abrir(mc, caminho: Path):
    rel = mc.caminho_relativo_da_bin(str(caminho))
    mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
    return [i.nome for i in mc.itens_da_bin(rel, tipos=("AllTypes",))]


def mover_de_verdade(origem: Path, destino: Path, nome_do_item: str) -> int:
    """O gesto inteiro, pelo caminho do PRODUTO: tirar de uma, pôr na outra, uid
    PRESERVADO nas duas — são as bins do editor sendo atualizadas, não bins novas.

    ⛔⛔ **A ordem não é arbitrária: TIRAR antes de PÔR.** Medido aqui — com o mob ainda
    vivo na bin de origem, o Media Composer trata o que chega como cópia e renomeia para
    `….AutoCopy.NN`. O editor pediu para mover uma timeline e recebe uma com outro nome.
    """
    com_fecho = 0
    for caminho, acao in ((origem, "tirar"), (destino, "por")):
        lado = caminho.with_suffix(".avb.novo")
        if acao == "tirar":
            with avb.open(str(caminho)) as f:
                alvo = next(i for i in f.content.items
                            if (i.mob.name or "") == nome_do_item)
                f.content.items.remove(alvo)
                f.write(str(lado))
        else:
            with avb.open(str(FIXTURE_ORIGEM)) as fonte, avb.open(str(caminho)) as f:
                indice = indexar(fonte)
                mob = next(i.mob for i in fonte.content.items
                           if (i.mob.name or "") == nome_do_item)
                precisos = {k: v for k, v in fecho(indice, mob).items() if v is not None}
                com_fecho = len(precisos)
                ja_tem = set(indexar(f))
                f.content.add_mob(mob.copy(f)).user_placed = True
                # ⚠️ O que o destino JÁ TEM não entra de novo: dois `BinItem` com o mesmo
                #    MobID na mesma bin é dado contraditório dentro de um arquivo só.
                for mid, m in precisos.items():
                    if mid not in ja_tem:
                        f.content.add_mob(m.copy(f)).user_placed = False
                f.write(str(lado))
        lado.replace(caminho)
    return com_fecho


def medicao_4_mover_de_verdade(mc):
    print()
    print("=" * 78)
    print("MEDIÇÃO 4 — o gesto INTEIRO, com CloseBin e uid preservado")
    print("=" * 78)

    # ⭐⭐ A hipótese a testar: o `FILE_OPEN_FAILURE` da `_MOVER ORIGEM` NÃO é uid (os seis
    #    uids são distintos, medido) — é que ela repete 95 dos 96 mobs de uma bin ABERTA.
    #    Se for isso, fechar a fixture faz a mesma bin abrir sem tocar em byte nenhum.
    for f in (FIXTURE_ORIGEM, FIXTURE_DESTINO, PROJETO / "BIN DESTINO - vazia.avb"):
        fechar(mc, f)
    print("fixtures fechadas no MC (nada nelas foi escrito por nós)")

    with avb.open(str(ORIGEM)) as f:
        ama = tem_mob_ama(f)
    if ama:
        # ⛔⛔ MEDIDO: não adianta tentar. Qualquer bin derivada desta fixture é recusada,
        #    e o `OpenBin` acusa `FILE_OPEN_FAILURE` — a mesma frase de `Bin.uid` repetido,
        #    que foi exatamente o que me fez perder duas rodadas culpando o uid.
        print(f"⛔ a bin tem {len(ama)} mob(s) AMA com WinFileLocator: {ama}")
        print("   nenhuma bin escrita pelo pyavb a partir daqui vai ABRIR no MC.")
        return False, "bloqueado pelo WinFileLocator — o gesto fica por julgar na tela"

    try:
        itens = abrir(mc, ORIGEM)
        print(f"_MOVER ORIGEM abriu agora: {len(itens)} itens")
    except Exception as e:      # noqa: BLE001
        print(f"_MOVER ORIGEM continua recusada: {str(e)[:90]}")
        return False, "não abriu a bin de origem; o gesto inteiro fica por medir"

    antes_o = set(abrir(mc, ORIGEM))
    antes_d = set(abrir(mc, DESTINO_EXISTENTE))
    print(f"antes ....... origem {len(antes_o)} · destino {len(antes_d)}")

    fechar(mc, ORIGEM)
    fechar(mc, DESTINO_EXISTENTE)
    com_fecho = mover_de_verdade(ORIGEM, DESTINO_EXISTENTE, ITEM_2)
    print(f"movido ...... {ITEM_2!r} (+{com_fecho} mobs de fecho)")

    depois_o = set(abrir(mc, ORIGEM))
    depois_d = set(abrir(mc, DESTINO_EXISTENTE))
    print(f"depois ...... origem {len(depois_o)} · destino {len(depois_d)}")
    print(f"saiu da origem: {sorted(antes_o - depois_o)}")
    print(f"entrou no destino: {sorted(depois_d - antes_d)}")

    chegou = sorted(depois_d - antes_d)
    ok = (ITEM_2 in antes_o and ITEM_2 not in depois_o and chegou == [ITEM_2])
    return ok, ("saiu de uma e entrou na outra COM O NOME, sem AutoCopy" if ok
                else f"o destino recebeu {chegou!r}")


def julgar_no_mc() -> int:
    """O MC é o único juiz de verdade: a bin abre, e a timeline CARREGA?"""
    print("\n" + "=" * 78)
    print("O MEDIA COMPOSER JULGA")
    print("=" * 78)
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            print("o Media Composer não está aberto — nada a julgar.")
            return 1
        for bin_ in (ORIGEM, DESTINO_NOVO, DESTINO_EXISTENTE):
            if not bin_.exists():
                continue
            rel = mc.caminho_relativo_da_bin(str(bin_))
            try:
                mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
            except Exception as e:      # noqa: BLE001
                print(f"{bin_.name}: OpenBin FALHOU — {e}")
                continue
            itens = mc.itens_da_bin(rel, tipos=("AllTypes",))
            print(f"\n{bin_.name}: {len(itens)} item(ns) na janela")
            for i in itens:
                print(f"   {i.nome}")
        ok, nota = medicao_4_mover_de_verdade(mc)
        print()
        print("=" * 78)
        print(("OK " if ok else "NAO") + " 4 mover de verdade  " + nota)
        print("=" * 78)

    print("\n⚠️ O que SÓ o olho responde: carregue a timeline movida na Record.")
    print("   A bin abrir não prova nada — no defeito de 2026-08-30 ela abria e listava")
    print("   tudo certo, e o MC caía ao CARREGAR (ACCESS_VIOLATION).")
    return 0


def main() -> int:
    for f in (FIXTURE_ORIGEM, FIXTURE_DESTINO):
        if not f.exists():
            sys.exit(f"fixture ausente: {f}")

    placar = []
    for nome, medir in (("1 tirar", medicao_1_tirar),
                        ("2 bin nova", medicao_2_bin_nova),
                        ("3 bin existente", medicao_3_bin_existente)):
        ok, nota = medir()
        placar.append((nome, ok, nota))

    print("\n" + "=" * 78)
    for nome, ok, nota in placar:
        print(f"{'OK ' if ok else 'NAO'} {nome:18s} {nota}")
    print("=" * 78)

    if "--abrir" in sys.argv:
        julgar_no_mc()

    # ⚠️ Sai 0 quando as medições RODARAM. Um spike que exija sucesso em toda medição não
    #    serve para medir o que ainda não funciona — e a medição 3 é justamente a dúvida.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
