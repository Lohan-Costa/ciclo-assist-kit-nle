"""A rota `.avb` do relink: editar a bin do editor, sem AAF.

Irmã de `relink.py`, que continua sendo a rota AAF — validada em escala e em produção.
Esta é a do [ADR 0013](../../docs/adr/0013-a-rota-avb-volta-a-existir.md): em vez de pedir
um AAF ao Media Composer (`ExportFile` + preset) e devolvê-lo por `ImportFile`, edita-se a
**própria bin que ele escreveu**. A composição continua sendo a dele — só as referências
de MobID mudam —, e os efeitos sobrevivem pelo mesmo motivo da rota AAF: não passamos
perto deles.

O que isto elimina: o `ExportFile`, o **preset de export** (e com ele o
[ADR 0009](../../docs/adr/0009-preset-de-export-embarcado.md) do caminho do editor), o
`ImportFile` — e, pelo áudio autorado, o modal `Audio Start-Time Options`, que congela a
API e atingia as duas rotas.

## As oito etapas, e cada uma é uma regra que custou uma rodada de medição

    1. resave da bin de origem com `Bin.uid` NOVO      → bin de trabalho
    2. OpenBin (o MC precisa conhecê-la p/ aceitá-la como destino de LinkFile)
    3. LinkFile do VÍDEO nela   ⭐ áudio NÃO passa aqui — o modal congelaria a API
    4. Save + ESPERAR o arquivo estabilizar
    5. ACHATAR os subclipes
    6. MEDIR quanto a timeline pede de cada master  ⭐ só faz sentido depois do (5)
    7. autorar os masters de ÁUDIO com esse mínimo e mesclá-los na mesma bin
    8. repontar → resave com OUTRO `Bin.uid` novo      → bin final → OpenBin

⚠️ **Masters e timeline na MESMA bin** (etapas 3 e 7): num master AMA o caminho do arquivo
mora na bin, não no banco de mídia. Separá-los dá timeline 100% offline com o `LinkFile`
reportando sucesso e o `OpenBin` reportando OK.

⚠️⚠️ **A ordem 5 → 6 → 7 não é a intuitiva, e inverter custa a timeline inteira.** É o
achatamento que fixa o `start` final de cada clipe, e é `start + length` que diz de
quantos frames o master precisa. Autorar o áudio antes deixa o master 1 frame curto e o
Media Composer recusa **a timeline toda** com `PMM_INSUFFICIENT_MEDIA` — medido em
2026-08-16, com 97 de 98 mídias online e 10 clipes de música estourando por 1 frame.
"""

from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path

from aaf.masters import chave_mob
from avid.acoes import Acoes
from relink import Progresso, Trabalho

log = logging.getLogger("delapraca.relink_avb")


def esperar_bin_estabilizar(caminho: Path, quietos: int = 3,
                            limite_s: float = 120.0) -> None:
    """Espera o `.avb` parar de mudar (tamanho E mtime) antes de lê-lo.

    ⚠️⚠️ **`DoCommand(1004 Save)` NÃO é síncrono.** Ele volta na hora e o Media Composer
    grava depois. Ler antes devolve a versão ANTERIOR **sem erro nenhum**, e o número que
    sai é plausível: medido em 2026-08-16, uma leitura 2 s após o Save pegou a bin **sem
    os 44 masters recém-linkados**, e todo o resto do fluxo reportou sucesso — bin
    entregue, `OpenBin` OK, e o vídeo inteiro offline. É a mesma assincronia que
    `acoes.export_file` já trata para o `ExportFile`.
    """
    anterior, estaveis = None, 0
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim and estaveis < quietos:
        try:
            st = caminho.stat()
        except OSError:
            time.sleep(0.5)
            continue
        atual = (st.st_size, st.st_mtime_ns)
        estaveis = estaveis + 1 if atual == anterior else 0
        anterior = atual
        time.sleep(0.5)


def _record_pela_api(mc) -> bool:
    """A API põe a timeline no RECORD? Não no MC 2024 (24.6): o `LoadMobsIntoViewer` ignora o Record e carrega no
    Source, e não há `MakeViewerActive` nem `DoCommand` (medido 2026-10-18; banco, ativar-no-2021-ftf.md). Decisão do
    autor: lá a timeline vai ao Source e o painel pede o duplo clique na sequência da bin."""
    try:
        return mc.tem("MakeViewerActive")
    except Exception:  # noqa: BLE001 — sem saber, tenta o Record como antes
        return True


def garantir_bin_no_disco(mc, bin_origem: str) -> int:
    """Força o `Save` e espera o arquivo. Devolve quantos mobs a bin tem **no disco**.

    ⚠️⚠️ **Uma bin aberta com alterações não salvas existe SÓ na memória do Media
    Composer.** O arquivo em disco pode ser uma casca: medido em 2026-08-16, a bin de um
    projeto real tinha **53 KB e ZERO mobs** enquanto a timeline inteira estava na sessão
    (o MC marca essas bins com `*` no título). Ler dali devolve 0 masters — e o número 0
    é plausível, então o fluxo seguia até "nada a decidir", culpando o acervo por um
    problema de leitura.

    Por isso a rota `.avb` **sempre** salva antes de ler, e por isso quem chama tem de
    olhar o retorno: `0` significa *não consegui ler esta bin*, nunca *bin vazia*.
    """
    Acoes(mc).salvar(bin_aberta=bin_origem)    # MC 2024 sem DoCommand: fecha e reabre ESTA bin (acoes.salvar)
    esperar_bin_estabilizar(Path(bin_origem))
    from avb_export.reader import topen

    try:
        with topen(str(bin_origem)) as f:
            return len(list(f.content.mobs))
    except Exception as e:  # noqa: BLE001
        log.warning("não consegui ler %s: %s", bin_origem, e)
        return 0


def mobid_pyavb(mob_id_api: str):
    """MobID da API do Media Composer → objeto `MobID` do pyavb.

    ⚠️ As duas representações **não são a mesma** (a da API é um GUID de endianness
    mista). Reusa `avid.mcapi.mob_id_para_pyavb`, já provado, em vez de trocar bytes aqui.
    """
    from avb.mobid import MobID
    from avid.mcapi import mob_id_para_pyavb

    return MobID(bytes_le=bytes.fromhex(mob_id_para_pyavb(mob_id_api)))


def _assinatura(seq) -> tuple:
    """`(nome, nº de trilhas, maior comprimento)` de uma sequência — o que não muda quando o MC a duplica."""
    faixas = list(getattr(seq, "tracks", []) or [])
    comp = max((int(getattr(t.component, "length", 0) or 0) for t in faixas
                if getattr(t, "component", None) is not None), default=0)
    return (seq.name or "", len(faixas), comp)


def _reencontrar(f, mob_id: str, assinatura: tuple):
    """A sequência pedida na bin de trabalho DEPOIS de o MC salvá-la.

    ⛔ Medido 2026-10-12 (MC 25.6, a bin do laboratório aberta e uma cópia dela aberta por cima): o MC trata MobID
    visível repetido entre bins ABERTAS como cópia (banco, protocolos/avb/escrita.md §"TIRAR antes de PÔR") — dá a
    TODAS as sequências da bin de trabalho um MobID novo e o nome `<nome>.AutoCopy.NN`. O MobID pedido some. Vale para
    a bin do próprio editor (aberta, de onde ele arrastou) e para uma bin de fora com os mesmos mobs.
    ⇒ Pelo MobID, se ainda existir; senão a ÚNICA de nome `<nome>` ou `<nome>.AutoCopy.NN` com a mesma assinatura.
    Ambíguo ou ausente: None (o chamador recusa — nunca outra timeline).
    """
    import re
    from avb_bin.segmentos import escolher_sequencia, sequencias
    achada = escolher_sequencia(f, mob_id=mob_id)
    if achada is not None:
        return achada
    nome, trilhas, comp = assinatura
    padrao = re.compile(re.escape(nome) + r"(\.AutoCopy\.\d+)?$")
    candidatas = [s for s in sequencias(f)
                  if padrao.fullmatch(s.name or "") and _assinatura(s)[1:] == (trilhas, comp)]
    return candidatas[0] if len(candidatas) == 1 else None


def _aplicar_bin_unica(mc, trabalho: Trabalho, bin_origem: str, pasta_trabalho: str,
            nome_bin: str, progresso: Progresso | None = None, pasta_saida: str | None = None) -> dict:
    """(A entrega ANTIGA, numa bin só — guardada como referência; o fluxo usa `aplicar`, organizado em pasta.)
    Relinka editando a bin do editor. Devolve o resumo da operação.

    Args:
        bin_origem: a `.avb` que contém a timeline.
        nome_bin: nome-base da bin de entrega. ⚠️ Tem de ser **novo** — `OpenBin` numa bin
            já aberta devolve `Completed` e **não relê o disco**.
    """
    from avb_bin import audio as avb_audio
    from avb_bin import denest as avb_denest
    from avb_bin import masters as avb_masters
    from avb_bin import percurso as avb_percurso
    from avb_bin import remap as avb_remap
    from avb_bin import visibilidade as avb_vis
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen

    p = progresso or Progresso()
    acoes = Acoes(mc)
    decididos = trabalho.decididos()
    if not decididos:
        raise ValueError("nada decidido — não há o que relinkar")

    # ⭐ A entrega mora ao lado da bin do editor — ou, numa bin de FORA (outra máquina, Magic Link), na pasta do
    # projeto aberto (`pasta_saida`): a bin de fora é só LIDA, nunca escrita nem posta no projeto dela.
    raiz = Path(pasta_saida) if pasta_saida else Path(bin_origem).parent
    por_mob = {m.mob_id: m for m in trabalho.masters}
    video = {k: v for k, v in decididos.items() if not avb_audio.e_audio(v)}
    audio = {k: v for k, v in decididos.items() if avb_audio.e_audio(v)}

    # ── 1-2) bin de trabalho, UID novo, conhecida pelo MC ───────────────────
    # ⭐ UMA bin só, do começo ao fim. Ela nasce como destino do `LinkFile` e termina
    # como a bin entregue: no fim é FECHADA, reescrita no mesmo caminho e reaberta.
    # Antes eram duas — uma "(trabalho)" e a final —, e o editor ficava com uma bin de
    # sobra no projeto que não significava nada para ele. (Pedido do usuário, 2026-08-16.)
    p("preparando a bin", 0, 1, nome_bin)
    saida = raiz / f"{nome_bin}.avb"
    with topen(str(bin_origem)) as f:
        # A sequência pedida, ANTES de o MC tocar na bin de trabalho: ao abri-la ele pode trocar o MobID (AutoCopy,
        # ver `_reencontrar`), e a assinatura é o que a acha de novo.
        assinatura = None
        if trabalho.sequence_mob_id:
            from avb_bin.segmentos import escolher_sequencia
            pedida = escolher_sequencia(f, mob_id=trabalho.sequence_mob_id)
            if pedida is None:
                raise RuntimeError("a timeline pedida não está na bin — nada foi alterado")
            assinatura = _assinatura(pedida)
        f.content.uid = random.getrandbits(63)
        f.write(str(saida))
    mc.abrir_bin(str(saida))

    # ── 3) VÍDEO pelo LinkFile — o Media Composer decide o codec ────────────
    mapa: dict[str, object] = {}
    falhas: list[dict] = []
    total = len(video)
    t0 = time.time()
    for i, (mob_id, caminho) in enumerate(sorted(video.items(), key=lambda kv: kv[1])):
        p("trazendo o vídeo", i, total, Path(caminho).name)
        t_arq = time.time()
        try:
            novo = acoes.link_file(caminho, saida.name)
        except Exception as e:  # noqa: BLE001 — um arquivo não derruba os outros
            falhas.append({"arquivo": caminho, "erro": str(e)})
            continue
        if time.time() - t_arq > 5:  # o normal é < 1 s; o lento é o que já passou do teto antigo (20 s)
            log.info("LinkFile lento: %s em %.1fs", Path(caminho).name, time.time() - t_arq)
        if novo:
            mapa[mob_id] = mobid_pyavb(novo)
        else:
            falhas.append({"arquivo": caminho, "erro": "LinkFile não devolveu mob_id"})
    if total:
        log.info("LinkFile: %d/%d em %.1fs", len(mapa), total, time.time() - t0)

    p("salvando", total, total, "")
    acoes.salvar()
    esperar_bin_estabilizar(saida)

    # ── 4) FECHAR a bin no Media Composer — ANTES de abri-la com o pyavb ────
    #
    # ⚠️⚠️ **A ORDEM AQUI É QUESTÃO DE INTEGRIDADE, não de arrumação.** Este `CloseBin`
    # já esteve LÁ EMBAIXO, no meio da sessão do pyavb, e o resultado foi bin corrompida
    # e Media Composer fechando sozinho ao abri-la (2026-08-16).
    #
    # O mecanismo: o `topen` do pyavb **não lê o arquivo inteiro de uma vez** — ele mantém
    # o handle e resolve objeto por objeto, sob demanda. Fechar a bin faz o **MC
    # REESCREVER esse mesmo arquivo**. Com o handle aberto por cima de uma reescrita, as
    # leituras seguintes caem em offsets que já não valem: o sintoma foi
    # `unpack requires a buffer of 8 bytes` — struct lendo lixo — e, pior, o que
    # sobreviveu virou uma bin gravada por cima da outra.
    #
    # ⭐ **Por que fechar, afinal** (a pergunta é justa): porque entregamos **UMA bin
    # só**, a mesma do começo ao fim. Reescrever por baixo de uma bin ABERTA não adianta
    # — `OpenBin` numa bin já aberta devolve `Completed` e **não relê o disco**, então o
    # editor continuaria vendo a versão pré-relink enquanto o serviço jura ter entregue a
    # nova. A alternativa seria gravar em outro arquivo, e aí voltam as duas bins no
    # projeto, que é justamente o que foi pedido para acabar.
    #
    # ⭐ E fechar AQUI ainda deve ser mais RÁPIDO: vem logo depois do `Save`, então não há
    # nada pendente para o Avid gravar no fechamento.
    p("fechando a bin no Media Composer", 0, 1, saida.name)
    # Onde o resultado será GRAVADO. Igual à bin de trabalho no caminho feliz — é o que
    # faz o projeto terminar com uma bin só.
    saida_final = saida
    fechada = True
    t_fechar = time.time()
    try:
        mc.fechar_bin(str(saida))
    except Exception as e:  # noqa: BLE001
        fechada = False
        log.warning("não consegui fechar %s (%s) — entregando com outro nome",
                    saida.name, e)
    # Cronometrado porque a duração É a questão em aberto: fechar depois do `Save` não
    # deveria ter nada a gravar. Se ainda demorar, o número diz se o custo é do Avid
    # salvando ou de outra coisa — sem ele, a conversa vira "pareceu demorado".
    log.info("CloseBin(%s): %.1fs (%s)", saida.name, time.time() - t_fechar,
             "ok" if fechada else "falhou")
    if fechada:
        # Fechar também grava. Esperar o arquivo parar de mudar antes de lê-lo é a mesma
        # precaução do `Save`, pelo mesmo motivo: o rpc não promete ter terminado.
        esperar_bin_estabilizar(saida)
    else:
        # Não dá para reescrever por baixo de uma bin aberta e esperar que o MC releia.
        # Entregar com nome novo é pior para o editor, mas é honesto — e é a única saída
        # que não arrisca gravar sobre um arquivo que o Avid ainda tem na mão.
        saida_final = raiz / f"{nome_bin} (relinkada).avb"
        log.warning("entregando em %s", saida_final.name)

    # ── 5-7) achatar → medir → autorar o áudio → mesclar → repontar → gravar ─
    #
    # ⚠️ A ORDEM importa e não é a intuitiva. O áudio só pode ser autorado **depois** do
    # achatamento, porque é ele que define o `start` final de cada clipe — e é o
    # `start + length` que diz de quantos frames o master precisa. Autorar antes deixa o
    # master curto e a timeline inteira é recusada com `PMM_INSUFFICIENT_MEDIA`.
    p("montando a bin", 0, 1, nome_bin)
    bin_audio = Path(pasta_trabalho) / f"{nome_bin} (audio).avb"
    # A taxa da timeline sai dos masters lidos, não do projeto — é a que a bin registra.
    fps = next((m.edit_rate for m in trabalho.masters if m.edit_rate), None)
    r_audio = {"clipes": 0, "mapa": {}, "pulados": [], "sem_template": [],
               "esticados": [], "curtos_demais": []}
    # Onde a bin nova é escrita antes de tomar o lugar da antiga — ver o comentário na
    # gravação. Extensão fora de `.avb` para o Media Composer nem enxergar o arquivo.
    temporaria = saida_final.with_name(saida_final.name + ".novo")
    with topen(str(saida)) as f:
        # ⭐ A sequência PEDIDA, resolvida uma vez e passada a cada passo: sem ela, cada um caía na "composição de
        # mais trilhas" da bin (`percurso.timeline`) — numa bin com várias timelines, outra (medido 2026-10-12).
        alvo = None
        if assinatura is not None:
            alvo = _reencontrar(f, trabalho.sequence_mob_id, assinatura)
            if alvo is None:
                raise RuntimeError("não reencontrei a timeline pedida na bin depois que o Media Composer a salvou "
                                   "— nada foi alterado")
            if alvo.name != assinatura[0]:
                log.info("o MC renomeou %r para %r (AutoCopy) — devolvendo o nome", assinatura[0], alvo.name)
                alvo.name = assinatura[0]
        # ⚠️ ACHATAR antes de tudo — ADR 0006 e `avb_bin/denest.py`.
        r_denest = avb_denest.achatar(f, alvo)

        if audio:
            # Quanto a timeline pede de cada master, agora que os offsets são finais.
            uso = avb_masters.uso_maximo(f, alvo)
            minimos = {caminho: uso.get(mob_id, 0) for mob_id, caminho in audio.items()}
            r_audio = avb_audio.autorar_masters(
                sorted(audio.values()), str(bin_audio), fps=fps, minimos=minimos,
                progresso=lambda feito, tot, n: p("preparando o áudio", feito, tot, n))
            for mob_id, caminho in audio.items():
                novo = r_audio["mapa"].get(caminho)
                if novo:
                    mapa[mob_id] = novo   # texto; resolvido para objeto na bin mesclada
            for nome, erro in r_audio["pulados"]:
                falhas.append({"arquivo": nome, "erro": erro})
            for nome, falta in r_audio["curtos_demais"]:
                falhas.append({"arquivo": nome,
                               "erro": f"o arquivo é {falta} frames mais curto que a "
                                       f"timeline pede — não é a mídia desta edição"})

            if r_audio["clipes"]:
                tem = {m.mob_id for m in f.content.mobs}
                with topen(str(bin_audio)) as fa:
                    for m in fa.content.mobs:
                        if m.mob_id in tem:
                            continue
                        f.content.add_mob(materialize(f, serialize(m)))
                        tem.add(m.mob_id)

        if not mapa:
            raise RuntimeError("nenhum arquivo pôde ser trazido para o Media Composer")

        # Os MobIDs de áudio vieram como texto (do clone individual); resolve-os para os
        # objetos DESTA bin, agora que os mobs estão aqui.
        por_texto = {str(m.mob_id): m.mob_id for m in f.content.mobs}
        mapa_final = {
            chave_mob(velho): (por_texto.get(novo, novo) if isinstance(novo, str) else novo)
            for velho, novo in mapa.items()
        }
        r_remap = avb_remap.repontar(f, mapa_final, alvo)

        # ⭐ Online some da vista, offline fica: a bin entregue é o relatório do que
        # ficou de fora. Ver `avb_bin/visibilidade.py`.
        #
        # ⚠️⚠️ E ISTO NÃO PODE DERRUBAR A ENTREGA. É a última etapa, é COSMÉTICA, e vem
        # depois de todo o trabalho caro (LinkFile arquivo a arquivo, áudio autorado,
        # achatamento, repontamento). Uma exceção aqui saía do `with` sem gravar nada:
        # o editor esperava minutos e recebia um traceback em vez da timeline.
        # Aconteceu — um `NameError` de uma linha, num trecho que nunca tinha rodado.
        # A bin sem o ajuste é a bin certa com ruído a mais; sem gravar não é nada.
        ids_online = _com_ja_online(f, {str(v) for v in mapa_final.values()}, trabalho)
        try:
            r_vis = avb_vis.ajustar(f, alvo if alvo is not None else avb_percurso.timeline(f), ids_online)
        except Exception as e:  # noqa: BLE001 — polimento nunca custa a entrega
            log.warning("não consegui ajustar a visibilidade da bin (%s) — "
                        "entregando com todos os itens visíveis", e, exc_info=True)
            r_vis = {"visiveis": 0, "ocultos": 0, "erro": str(e)}

        # ⭐ UID novo em toda gravação (ADR 0013).
        #
        # ⚠️⚠️ **Grava AO LADO e troca depois — nunca por cima do arquivo aberto.**
        # O `topen` é preguiçoso: ele resolve objeto por objeto sob demanda, com o handle
        # vivo. Gravar no MESMO caminho enquanto se lê dele é pedir para o writer ler um
        # offset de um arquivo que ele próprio acabou de truncar — a mesma corrida que o
        # `CloseBin` no lugar errado já causou, só que auto-infligida. O `.novo` fica na
        # PASTA DO PROJETO de propósito: `os.replace` só é atômico dentro do mesmo volume,
        # e a pasta de trabalho pode estar em outro disco.
        # A sequência entregue, para pô-la no Record no fim (autor, 2026-10-13).
        try:
            seq_entregue = str((alvo if alvo is not None else avb_percurso.timeline(f)).mob_id)
        except Exception:  # noqa: BLE001 — só serve ao Record; a entrega não depende dela
            seq_entregue = ""
        f.content.uid = random.getrandbits(63)
        f.write(str(temporaria))

    # Handle do pyavb fechado; do NOSSO lado ninguém mais tem o arquivo. A troca é
    # atômica: ou a bin antiga, ou a nova — nunca meia bin, que é o que travou o MC.
    #
    # ⚠️ Mas o Media Composer ficou LIVRE durante toda a etapa de áudio (ela não fala com
    # ele), e nada impede o editor de abrir a bin nesse intervalo — é o gesto natural de
    # quem está esperando. Com ela aberta, o Windows pode recusar a troca, e o resultado
    # sairia com outro nome por causa de um clique de curiosidade. Fechar de novo aqui
    # custa uma chamada e desfaz exatamente esse caso.
    try:
        mc.fechar_bin(str(saida_final))
    except Exception:  # noqa: BLE001 — fechar o que já está fechado não é erro
        pass

    try:
        os.replace(temporaria, saida_final)
    except OSError as e:
        # O resultado NÃO se perde por causa da troca: ele está inteiro no `.novo`.
        log.warning("a troca falhou mesmo depois de fechar a bin (%s)", e)
        saida_final = raiz / f"{nome_bin} (relinkada).avb"
        log.warning("entregando como %s", saida_final.name)
        os.replace(temporaria, saida_final)

    # ── 8) entregar ─────────────────────────────────────────────────────────
    #
    # ⚠️ A bin JÁ ESTÁ GRAVADA neste ponto: o trabalho todo está em disco, íntegro. Abrir
    # no editor é conveniência, e uma exceção aqui apagaria o relatório inteiro de um
    # trabalho que deu certo — o editor veria um erro e não saberia que o arquivo existe,
    # nem onde. Mesma regra do ajuste de visibilidade: nada depois da gravação pode custar
    # a entrega. O caminho volta no resultado justamente para poder ser aberto à mão.
    p("abrindo no Media Composer", 0, 1, saida_final.stem)
    aberta = True
    try:
        mc.abrir_bin(str(saida_final))
    except Exception as e:  # noqa: BLE001
        aberta = False
        log.warning("a bin foi gravada mas não abriu sozinha (%s): %s", e, saida_final)

    # ⭐ A timeline entregue NA FRENTE do editor: carregada no Record (autor, 2026-10-13). ⚠️ Banco
    # (`docommand-comandos.md`, "Carregar SEQUÊNCIA na Record"): 3 s depois do OpenBin, e NADA de CloseBin colado
    # depois do carregar (derruba o MC). Acessório: se o MC recusar, a bin já está aberta e o resumo diz qual é.
    no_record = no_source = False
    if aberta and seq_entregue:
        try:
            from sessao_export import mob_id_da_api

            time.sleep(3)
            if _record_pela_api(mc):
                mc.carregar_no_monitor([mob_id_da_api(seq_entregue)], "Record")
                no_record = True
            else:
                mc.carregar_no_monitor([mob_id_da_api(seq_entregue)], "Source")
                no_source = True
        except Exception as e:  # noqa: BLE001
            log.warning("a timeline entregue não foi para o Record (%s)", e)

    resultado = {
        "bin": saida_final.stem,
        "avb": str(saida_final),
        "aberta_no_mc": aberta,
        "no_record": no_record,
        "no_source": no_source,
        "masters_online": len(mapa),
        "masters_pedidos": len(decididos),
        "video_linkado": len(video) - sum(1 for x in falhas if x["arquivo"] in video.values()),
        "audio_autorado": r_audio["clipes"],
        "audio_sem_template": r_audio["sem_template"],
        # Masters que ganharam 1-2 frames de duração DECLARADA para cobrir o que a
        # timeline pede (nenhum frame da edição muda) e os que foram recusados por
        # serem curtos demais — mídia diferente da que o editor usou.
        "audio_esticado": r_audio["esticados"],
        "audio_curto_demais": r_audio["curtos_demais"],
        "falhas": falhas,
        "clipes_visiveis": r_vis["visiveis"],
        "clipes_ocultos": r_vis["ocultos"],
        "subclipes_achatados": r_denest["achatados"],
        "subclipes_restantes": r_denest["subclipes_restantes"],
        "referencias_trocadas": r_remap["repontados"],
        "masters_remapeados": r_remap["masters_trocados"],
        "segmentos_cobertos": sum(por_mob[m].segmentos for m in mapa if m in por_mob),
    }
    p("pronto", 1, 1, "")
    log.info("relink por bin aplicado: %s", resultado)
    return resultado


def aplicar_aaf(mc, trabalho: Trabalho, pasta_projeto: str, pasta_trabalho: str, nome_bin: str,
                progresso: Progresso | None = None) -> dict:
    """Relink de uma AAF RECEBIDA pela rota da bin: a AAF entra numa bin de trabalho do projeto (`ImportFile`) e o
    resto é `aplicar` — vídeo pelo `LinkFile`, ÁUDIO INJETADO (autorado na bin).

    ⭐ Regra do autor (2026-10-13): todo relink no Media Composer traz o áudio injetado, qualquer que seja a origem.
    A rota AAF antiga fazia `LinkFile` também dos WAVs, e o MC abria o `Audio Start-Time Options` em cada BWF com
    start time (medido no PRODUCAO-A: 41 de 47 áudios com `bext`; o editor teve de responder um a um).

    Medido antes de existir (2026-10-13, MC 25.6, `PRODA_CORTE_ORIGINAL.aaf`): o `ImportFile` da AAF offline voltou em
    1,8 s SEM diálogo nenhum, a bin chegou ao disco depois (assíncrono), e os 99 masters mantiveram o MobID da AAF —
    o casamento feito sobre a AAF vale na bin sem tradução.
    """
    p = progresso or Progresso()
    acoes = Acoes(mc)
    # ⭐ A bin da AAF é o BACKUP do que foi importado: mora na pasta da entrega, `<nome>_AAF`, sem parênteses (autor,
    # 2026-10-13). O nome da pasta já é livre (`nome_de_bin_livre` conta as pastas), então o da bin também é.
    pasta = Path(pasta_projeto) / nome_bin
    pasta.mkdir(parents=True, exist_ok=True)
    nome_imp = f"{nome_bin}_AAF"
    caminho = pasta / f"{nome_imp}.avb"
    # ⛔ O que entra no MC é uma CÓPIA da AAF, achatada e com MobIDs NOVOS nos masters (2026-10-13): a AAF crua, num
    # projeto que já a recebeu, abriu o modal "Sub clip conflict found" e travou a API até o Save cair no prazo. A rota
    # antiga já achatava antes do ImportFile por isso (`aaf/remap.py`); os IDs novos evitam o mesmo com os masters.
    # O trabalho passa a falar dos IDs novos durante o relink e volta aos antigos no fim (`_com_ids`).
    from aaf.remap import remapear_masters
    from aaf2.mobid import MobID
    from sessao_export import mob_id_da_api

    p("importando a timeline", 0, 1, Path(trabalho.aaf).name)
    novos = {m.mob_id: mob_id_da_api(str(MobID.new())) for m in trabalho.masters}
    copia = Path(pasta_trabalho) / f"{nome_imp}.aaf"
    copia.parent.mkdir(parents=True, exist_ok=True)
    remapear_masters(trabalho.aaf, str(copia), novos, achatar_subclipes=trabalho.achatar_subclipes,
                     achatar_group_clips=trabalho.achatar_group_clips)
    t_imp = time.time()
    acoes.criar_bin(nome_imp, nome_bin)
    acoes.import_file(str(copia), str(caminho))          # caminho ABSOLUTO: o ImportFile aceita (banco, windows.md)
    log.info("AAF → bin: CreateBin + ImportFile voltaram em %.1f s", time.time() - t_imp)
    # O `ImportFile` volta (0,1 s) antes de a bin existir no disco: salvar e esperar até ela trazer os mobs (prazo de
    # 3 min). ⚠️ NÃO salvar colado no ImportFile: com o Save 0,1 s depois, a importação nunca chegou à bin (3 min, 2026-10-13);
    # com o 1º Save 5 s depois, 529 mobs em ~10 s (mesma AAF, mesmo MC).
    # ⚠️ (2026-10-26, PRODUCAO-A) esta espera levou 62 s calada e o editor leu "congelou": cada volta diz o tempo na
    # tela e deixa rastro no log (quanto o Save levou, o tamanho da bin, os mobs) — para a próxima vez dizer ONDE prende.
    inicio = time.time()
    fim = inicio + 180
    mobs, tentativa = 0, 0
    while time.time() < fim:
        time.sleep(5)
        tentativa += 1
        p("importando a timeline", 0, 1, f"esperando o Media Composer gravar a bin importada ({time.time() - inicio:.0f} s)")
        t0 = time.time()
        mobs = garantir_bin_no_disco(mc, str(caminho))
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            tamanho = -1
        log.info("AAF → bin: tentativa %d, %.1f s desde o ImportFile (salvar+ler %.1f s), bin %d bytes, %d mobs",
                 tentativa, time.time() - inicio, time.time() - t0, tamanho, mobs)
        if mobs:
            break
    if not mobs:
        raise RuntimeError(f"a AAF não chegou à bin “{nome_imp}” em 3 min — nada foi relinkado")
    from avb_export.reader import topen
    from avb_bin.segmentos import escolher_sequencia, sequencias

    with topen(str(caminho)) as f:
        seq = escolher_sequencia(f)                     # a AAF de uma timeline traz UMA sequência
        if seq is None:
            from aaf.parser import parse_aaf
            nome = (parse_aaf(trabalho.aaf) or {}).get("composition_name") or ""
            seq = escolher_sequencia(f, nome=nome) if nome else None
        if seq is None:
            raise RuntimeError(f"a bin importada tem {len(sequencias(f))} sequências e não sei qual é a da AAF")
        trabalho.sequence_mob_id = str(seq.mob_id)
    # lida, ela fecha: no fim só a _SEQ fica aberta (autor, 2026-10-13)
    try:
        mc.fechar_bin(str(caminho))
    except Exception as e:  # noqa: BLE001 — fechar é arrumação, não pode custar o relink
        log.warning("não consegui fechar %s (%s)", caminho.name, e)
    with _com_ids(trabalho, novos):
        r = aplicar(mc, trabalho, str(caminho), pasta_trabalho, nome_bin, p, pasta_saida=pasta_projeto)
    r["bin_importada"] = nome_imp
    return r


class _com_ids:
    """O trabalho falando dos MobIDs NOVOS da cópia importada (`aplicar_aaf`), e de volta aos antigos na saída — o
    casamento, as escolhas do editor e o banco continuam a valer para a AAF de verdade."""

    def __init__(self, trabalho: Trabalho, novos: dict):
        from aaf.remap import api_para_urn

        self.t = trabalho
        self.trocas = {velho: (chave_mob(api_para_urn(api)), api_para_urn(api)) for velho, api in novos.items()}

    def __enter__(self):
        self.antes = [(m, m.mob_id, getattr(m, "mob_id_urn", None)) for m in self.t.masters]
        self.escolhas = dict(self.t.escolhas)
        # ⛔ (2026-10-13) os IGNORADOS e os JÁ ONLINE também falam do MobID: sem traduzi-los, na rota da AAF a ignorada
        # que casou seria relinkada e a já online ficava à vista na _SEQ (medido: DJI_0317, entrega "… 2 6").
        self.ignorados = set(getattr(self.t, "ignorados", set()))
        self.ja_online = dict(getattr(self.t, "ja_online", {}) or {})
        for m, velho, _urn in self.antes:
            if velho in self.trocas:
                m.mob_id, m.mob_id_urn = self.trocas[velho]
        novo = lambda k: self.trocas.get(k, (k,))[0]  # noqa: E731
        self.t.escolhas = {novo(k): v for k, v in self.escolhas.items()}
        self.t.ignorados = {novo(k) for k in self.ignorados}
        self.t.ja_online = {novo(k): v for k, v in self.ja_online.items()}
        return self

    def __exit__(self, *exc):
        for m, velho, urn in self.antes:
            m.mob_id = velho
            if urn is not None:
                m.mob_id_urn = urn
        self.t.escolhas = self.escolhas
        self.t.ignorados = self.ignorados
        self.t.ja_online = self.ja_online
        return False


# ── a entrega ORGANIZADA (autor, 2026-10-13) ─────────────────────────────────────────────────────────────────────

def _com_ja_online(f, ids: set[str], trabalho) -> set[str]:
    """`ids` mais os masters da bin que NÃO casaram mas já estão online (`trabalho.ja_online`: Avid MediaFiles ou link
    AMA do projeto). Na bin entregue só o OFFLINE fica à vista (autor, 2026-10-13)."""
    ja = getattr(trabalho, "ja_online", None) or {}
    if ja:
        ids = ids | {str(m.mob_id) for m in f.content.mobs if chave_mob(str(m.mob_id)) in ja}
    return ids


def _bin_ref(f, uid: int, nome: str):
    """O `_ORG_BIN` de um master: a bin em que ele mora. ⚠️ O UID entra TROCADO — `uid_high` = os 32 bits BAIXOS do
    `Bin.uid`, `uid_low` = os 32 ALTOS (medido 2026-10-13 numa bin do MC 25.6: uid 0x070a9fae_6acdf311 →
    high 0x6acdf311, low 0x070a9fae). Sem isto o áudio injetado dizia "Bin TEMPLATE Bin1 is not in the Project"."""
    def s32(x):
        x &= 0xFFFFFFFF
        return x - (1 << 32) if x & 0x80000000 else x
    r = f.create.BinRef()
    r.uid_high, r.uid_low = s32(uid), s32(uid >> 32)
    r.name = r.name_utf8 = nome
    return r


def _alcancaveis(f, raiz) -> set[str]:
    """`str(mob_id)` de tudo que a `raiz` usa, em qualquer profundidade (masters, fontes de essência…)."""
    from avb_bin.percurso import por_mob_id, source_clips

    por = por_mob_id(f)
    vistos, fila = {str(raiz.mob_id)}, [raiz]
    while fila:
        m = fila.pop()
        for tr in getattr(m, "tracks", None) or []:
            for sc in source_clips(getattr(tr, "component", None)):
                mid = str(getattr(sc, "mob_id", "") or "")
                if mid and mid not in vistos and mid in por:
                    vistos.add(mid)
                    fila.append(por[mid])
    return vistos


def juntar_na_midias(fm, bin_audio, r_video: dict, reaproveitar: dict, uid_midias: int, nome_midias: str) -> None:
    """Põe na `_MIDIAS` aberta (`fm`) o áudio injetado (`bin_audio`, ou None), o vídeo injetado (`r_video["saida"]`) e o
    master REAPROVEITADO do projeto com tudo o que ele alcança; e marca todo master como morador dela (`_ORG_BIN`).
    Serve ao relink (`aplicar`) e ao .prproj (`prproj_avid.montar`)."""
    from avb_bin import percurso as avb_percurso
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen

    # o áudio injetado entra na _MIDIAS…
    if bin_audio:
        tem = {m.mob_id for m in fm.content.mobs}
        with topen(str(bin_audio)) as fa:
            for m in fa.content.mobs:
                if m.mob_id not in tem:
                    fm.content.add_mob(materialize(fm, serialize(m)))
                    tem.add(m.mob_id)
    # …o vídeo injetado também (só os mobs novos: o resto da cópia é a própria _MIDIAS com os moldes)
    if r_video.get("saida"):
        tem = {str(m.mob_id) for m in fm.content.mobs}
        with topen(str(r_video["saida"])) as fv:
            for m in fv.content.mobs:
                if str(m.mob_id) not in tem:
                    fm.content.add_mob(materialize(fm, serialize(m)))
                    tem.add(str(m.mob_id))
    # …o master REAPROVEITADO também, com tudo o que ele alcança (fontes, arquivo), da bin onde já mora
    if reaproveitar:
        ja = {str(m.mob_id) for m in fm.content.mobs}
        por_bin: dict[str, list[str]] = {}
        for item in reaproveitar.values():
            por_bin.setdefault(item["bin"], []).append(item["mob_id"])
        for b_origem, ids in por_bin.items():
            with topen(b_origem) as fo:
                por = avb_percurso.por_mob_id(fo)
                for mid in ids:
                    if mid not in por:
                        continue
                    for x in sorted(_alcancaveis(fo, por[mid])):
                        if x not in ja and x in por:
                            fm.content.add_mob(materialize(fm, serialize(por[x])))
                            ja.add(x)
    # …e TODO master dela diz que mora nela (o do áudio vinha "TEMPLATE Bin1")
    for m in fm.content.mastermobs():
        if m.attributes is not None:
            m.attributes["_ORG_BIN"] = _bin_ref(fm, uid_midias, nome_midias)


def trazer_video(mc, acoes: Acoes, video: dict, destino: str, midias: Path, projeto: Path, ignorar: tuple,
                 pasta_trabalho: str, nome_bin: str, fps, p: Progresso) -> dict:
    """O VÍDEO de `video` (`{chave → arquivo}`) trazido para a `_MIDIAS`: o que o projeto já linkou é reaproveitado, um
    arquivo por assinatura vai pelo `LinkFile` (o molde) e os irmãos saem clonados dele. Termina com a `_MIDIAS` salva e
    FECHADA, pronta para o pyavb. Serve ao relink (`aplicar`) e ao .prproj (`prproj_avid.montar`) — a `chave` é o MobID
    do master num, o arquivo no outro.

    Devolve `{mapa: {chave → MobID novo}, falhas, tempos, reaproveitar, a_linkar, linkado, r_video}`."""
    mapa: dict[str, object] = {}
    falhas: list[dict] = []
    tempos: list[tuple[float, str]] = []
    # ⭐ REAPROVEITAR o que o projeto já linkou (autor, 2026-10-13): o LinkFile de um arquivo que o projeto já tem é
    # ~10× mais lento e deixa uma cópia a mais (banco, avid-panel-sdk/windows.md §14). O master ONLINE que já existe
    # numa bin do projeto é copiado para a _MIDIAS (mesmo MobID) na montagem; só o resto passa pelo LinkFile.
    from avb_bin import ama_do_projeto as ama

    reaproveitar: dict[str, dict] = {}
    try:
        acoes.salvar()                     # o disco precisa refletir as bins abertas antes de lê-las
        indice_ama = ama.varrer(str(projeto), str(Path(pasta_trabalho) / f"ama_{projeto.name or 'projeto'}.json"),
                                ignorar=ignorar)
    except Exception as e:  # noqa: BLE001 — sem a varredura, linka como antes
        log.warning("não consegui ver o que o projeto já linkou (%s) — linkando tudo", e)
        indice_ama = {}
    for mob_id, caminho in video.items():
        item = ama.reaproveitavel(indice_ama, caminho)
        if item:
            reaproveitar[mob_id] = item
            mapa[mob_id] = item["mob_id"]          # URN do pyavb (str), como o do áudio injetado
    if reaproveitar:
        log.info("reaproveitados do projeto: %d de %d vídeos (sem LinkFile)", len(reaproveitar), len(video))
    a_linkar = {k: v for k, v in video.items() if k not in reaproveitar}
    # ⭐ "Linka o primeiro, injeta os irmãos" (autor, 2026-10-18): o MC linka UM arquivo por assinatura (o molde) e
    # os irmãos saem clonados dele, com o MESMO motor de leitura (`avb_bin/video.py`). O que não puder ser clonado
    # volta ao LinkFile — o caminho de sempre.
    from avb_bin import video as avb_video

    por_arquivo: dict[str, list[str]] = {}
    for mob_id, caminho in a_linkar.items():
        por_arquivo.setdefault(caminho, []).append(mob_id)
    p("agrupando o vídeo por formato", 0, 1, "")
    grupos = avb_video.agrupar(sorted(por_arquivo))
    linkado: dict[str, object] = {}                 # arquivo → MobID (pyavb) do master que o MC criou

    def linkar(arquivos: list[str], rotulo: str) -> None:
        for i, caminho in enumerate(arquivos):
            p(rotulo, i, len(arquivos), Path(caminho).name)
            t_arq = time.time()
            try:
                novo = acoes.link_file(caminho, destino)
            except Exception as e:  # noqa: BLE001 — um arquivo não derruba os outros
                falhas.append({"arquivo": caminho, "erro": str(e)})
                continue
            tempos.append((time.time() - t_arq, Path(caminho).name))
            if tempos[-1][0] > 5:
                log.info("LinkFile lento: %s em %.1fs", Path(caminho).name, tempos[-1][0])
            if novo:
                linkado[caminho] = mobid_pyavb(novo)
            else:
                falhas.append({"arquivo": caminho, "erro": "LinkFile não devolveu mob_id"})

    total, t0 = len(por_arquivo), time.time()
    linkar([g[0] for g in grupos], "trazendo o vídeo")
    # irmão de molde que o MC recusou vai pelo LinkFile (pode ser só aquele arquivo)
    pelo_link = [c for g in grupos if g[0] not in linkado for c in g[1:]]
    a_injetar = [(str(linkado[g[0]]), g[1:]) for g in grupos if g[0] in linkado and len(g) > 1]
    r_video = {"saida": None, "mapa": {}, "falhas": [], "motores": {}}
    if a_injetar:
        acoes.salvar(str(midias))
        esperar_bin_estabilizar(midias)
        try:
            mc.fechar_bin(str(midias))       # ler com o pyavb com a bin FECHADA (integridade — `_aplicar_bin_unica`)
        except Exception as e:  # noqa: BLE001
            log.warning("não consegui fechar %s (%s)", midias.name, e)
        esperar_bin_estabilizar(midias)
        try:
            r_video = avb_video.injetar_irmaos(
                str(midias), a_injetar, str(Path(pasta_trabalho) / f"{nome_bin} (video).avb"), fps=fps,
                progresso=lambda feito, tot, n: p("injetando o vídeo", feito, tot, n))
        except Exception as e:  # noqa: BLE001 — a injeção é atalho: falhou, vai tudo pelo LinkFile
            log.warning("a injeção de vídeo falhou (%s) — linkando os irmãos", e)
            r_video = {"saida": None, "mapa": {}, "falhas": [(c, str(e)) for _, g in a_injetar for c in g],
                       "motores": {}}
        for caminho, motivo in r_video["falhas"]:
            log.info("de volta ao LinkFile: %s (%s)", Path(caminho).name, motivo)
        pelo_link += [c for c, _ in r_video["falhas"]]
        if pelo_link:
            mc.abrir_bin(str(midias))
    if pelo_link:
        linkar(pelo_link, "trazendo o vídeo")
    for caminho, ids in por_arquivo.items():
        novo = linkado.get(caminho) or r_video["mapa"].get(caminho)
        for mob_id in ids if novo else []:
            mapa[mob_id] = novo
    if r_video["mapa"]:
        log.info("vídeo: %d arquivos linkados pelo MC, %d injetados do molde (%s)", len(linkado),
                 len(r_video["mapa"]), ", ".join(sorted(set(r_video["motores"].values()))))
    if total:
        # o rastro de CADA arquivo (2026-10-13: 48 vídeos em 54 s numa rodada e 221 s na seguinte, mesmos arquivos —
        # a regressão só se mede comparando a distribuição, não o total)
        ts = sorted(t for t, _ in tempos)
        log.info("LinkFile: %d/%d em %.1fs (mediana %.2fs, máx %.1fs; os mais lentos: %s)", len(mapa), total,
                 time.time() - t0, ts[len(ts) // 2] if ts else 0, ts[-1] if ts else 0,
                 ", ".join(f"{n} {t:.1f}s" for t, n in sorted(tempos, reverse=True)[:3]))
    p("salvando", total, total, "")
    acoes.salvar()
    esperar_bin_estabilizar(midias)
    # Fechar ANTES de ler com o pyavb (integridade — ver `_aplicar_bin_unica`, etapa 4).
    try:
        mc.fechar_bin(str(midias))
    except Exception as e:  # noqa: BLE001
        log.warning("não consegui fechar %s (%s)", midias.name, e)
    esperar_bin_estabilizar(midias)
    return {"mapa": mapa, "falhas": falhas, "tempos": tempos, "reaproveitar": reaproveitar, "a_linkar": a_linkar,
            "linkado": linkado, "r_video": r_video}


def aplicar(mc, trabalho: Trabalho, bin_origem: str, pasta_trabalho: str,
            nome_bin: str, progresso: Progresso | None = None, pasta_saida: str | None = None) -> dict:
    """Relink pela bin, entregue ORGANIZADO numa pasta do projeto (autor, 2026-10-13):

        <nome>/                     pasta no projeto
          <nome>_MIDIAS.avb         os masters: o vídeo linkado pelo MC e o áudio INJETADO, todos com `_ORG_BIN` nela
          <nome>_SEQ.avb            só a timeline (MobID novo: sem AutoCopy) e, OCULTO, o que ela usa

    A bin de origem é só LIDA (nunca escrita). ⚠️ Os masters também vão, ocultos, na `_SEQ`: masters AMA e timeline em
    bins separadas deram timeline 100% offline (banco, `protocolos/avb/escrita.md`) — a `_MIDIAS` é a do editor, a
    cópia oculta é a que faz a timeline resolver sozinha.
    """
    from avb.mobid import MobID
    from avb_bin import audio as avb_audio
    from avb_bin import denest as avb_denest
    from avb_bin import masters as avb_masters
    from avb_bin import percurso as avb_percurso
    from avb_bin import remap as avb_remap
    from avb_bin import visibilidade as avb_vis
    from avb_bin.segmentos import escolher_sequencia
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen

    p = progresso or Progresso()
    acoes = Acoes(mc)
    decididos = trabalho.decididos()
    if not decididos:
        raise ValueError("nada decidido — não há o que relinkar")
    raiz = Path(pasta_saida) if pasta_saida else Path(bin_origem).parent
    projeto = Path((mc.projeto() or {}).get("path") or raiz)
    por_mob = {m.mob_id: m for m in trabalho.masters}
    video = {k: v for k, v in decididos.items() if not avb_audio.e_audio(v)}
    audio = {k: v for k, v in decididos.items() if avb_audio.e_audio(v)}

    # ── 1) a pasta e a _MIDIAS, criadas PELO MC (ele precisa conhecê-la para o LinkFile) ──────────────────────
    pasta = raiz / nome_bin
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        sub = os.path.relpath(pasta, projeto)
    except ValueError:
        sub = nome_bin
    nome_midias, nome_seq = f"{nome_bin}_MIDIAS", f"{nome_bin}_SEQ"
    midias, seq = pasta / f"{nome_midias}.avb", pasta / f"{nome_seq}.avb"
    p("preparando a bin", 0, 1, nome_midias)
    sub = "" if sub in (".", "") else sub.replace("\\", "/")
    acoes.criar_bin(nome_midias, sub)
    # ⛔ Bin em subpasta: o destino do LinkFile é o caminho RELATIVO AO PROJETO ("pasta/bin.avb"); só o nome dá
    # "Bin not found" (ErrorType 9) — medido 2026-10-13, MC 25.6: 0/48 vídeos linkados na 1ª entrega organizada.
    destino = f"{sub}/{midias.name}" if sub else midias.name

    # ── 2) VÍDEO pelo LinkFile, na _MIDIAS ────────────────────────────────────────────────────────────────────
    fps = next((m.edit_rate for m in trabalho.masters if m.edit_rate), None)
    v = trazer_video(mc, acoes, video, destino, midias, projeto, (str(bin_origem), str(midias)), pasta_trabalho,
                     nome_bin, fps, p)
    mapa, falhas, tempos = v["mapa"], v["falhas"], v["tempos"]
    reaproveitar, a_linkar, linkado, r_video = v["reaproveitar"], v["a_linkar"], v["linkado"], v["r_video"]

    # ── 3) a timeline: achatar → medir → injetar o áudio → montar as duas bins ────────────────────────────────
    p("montando as bins", 0, 1, nome_bin)
    bin_audio = Path(pasta_trabalho) / f"{nome_bin} (audio).avb"
    fps = next((m.edit_rate for m in trabalho.masters if m.edit_rate), None)
    r_audio = {"clipes": 0, "mapa": {}, "pulados": [], "sem_template": [], "esticados": [], "curtos_demais": []}
    uid_midias, uid_seq = random.getrandbits(63), random.getrandbits(63)
    midias_novo, seq_novo = midias.with_name(midias.name + ".novo"), seq.with_name(seq.name + ".novo")
    with topen(str(bin_origem)) as f:
        alvo = escolher_sequencia(f, mob_id=trabalho.sequence_mob_id) if trabalho.sequence_mob_id \
            else avb_percurso.timeline(f)
        if alvo is None:
            raise RuntimeError("a timeline pedida não está na bin — nada foi alterado")
        r_denest = avb_denest.achatar(f, alvo)
        if audio:
            uso = avb_masters.uso_maximo(f, alvo)
            minimos = {caminho: uso.get(mob_id, 0) for mob_id, caminho in audio.items()}
            r_audio = avb_audio.autorar_masters(
                sorted(audio.values()), str(bin_audio), fps=fps, minimos=minimos,
                progresso=lambda feito, tot, n: p("preparando o áudio", feito, tot, n))
            for mob_id, caminho in audio.items():
                if r_audio["mapa"].get(caminho):
                    mapa[mob_id] = r_audio["mapa"][caminho]
            for nome, erro in r_audio["pulados"]:
                falhas.append({"arquivo": nome, "erro": erro})
            for nome, falta in r_audio["curtos_demais"]:
                falhas.append({"arquivo": nome, "erro": f"o arquivo é {falta} frames mais curto que a timeline pede — "
                                                        f"não é a mídia desta edição"})
        if not mapa:
            raise RuntimeError("nenhum arquivo pôde ser trazido para o Media Composer")

        with topen(str(midias)) as fm:
            juntar_na_midias(fm, str(bin_audio) if r_audio["clipes"] else None, r_video, reaproveitar, uid_midias,
                             nome_midias)
            # a _SEQ recebe uma cópia de cada mob da _MIDIAS (oculta), para a timeline resolver sozinha
            tem = {str(m.mob_id) for m in f.content.mobs}
            for m in fm.content.mobs:
                if str(m.mob_id) not in tem:
                    f.content.add_mob(materialize(f, serialize(m)))
                    tem.add(str(m.mob_id))
            fm.content.uid = uid_midias
            fm.write(str(midias_novo))

        por_texto = {str(m.mob_id): m.mob_id for m in f.content.mobs}
        mapa_final = {chave_mob(velho): (por_texto.get(novo, novo) if isinstance(novo, str) else novo)
                      for velho, novo in mapa.items()}
        r_remap = avb_remap.repontar(f, mapa_final, alvo)
        # a _SEQ é SÓ a timeline e o que ela usa; com MobID novo, o MC não a duplica (AutoCopy) ao abrir
        manter = _alcancaveis(f, alvo)
        itens = f.content.property_data.get("items") or []
        f.content.property_data["items"] = [it for it in itens if str(getattr(getattr(it, "mob", None), "mob_id", "")) in manter]
        if getattr(f.content, "_mob_dict", None):
            f.content._mob_dict = {k: v for k, v in f.content._mob_dict.items() if str(k) in manter}
        alvo.mob_id = MobID.new()
        seq_entregue = str(alvo.mob_id)
        ids_online = _com_ja_online(f, {str(v) for v in mapa_final.values()}, trabalho)
        try:
            r_vis = avb_vis.ajustar(f, alvo, ids_online)
            ligado = avb_vis.garantir_monitor(f, alvo)
            if ligado:
                log.info("monitor de vídeo ligado na V%s (a timeline não tinha nenhum)", ligado)
            for it in f.content.property_data.get("items") or []:     # na _SEQ, master nenhum à vista
                if avb_percurso.e_master(getattr(it, "mob", None)) and str(it.mob.mob_id) in ids_online:
                    it.property_data["user_placed"] = False
        except Exception as e:  # noqa: BLE001 — polimento nunca custa a entrega
            log.warning("não consegui ajustar a visibilidade (%s)", e, exc_info=True)
            r_vis = {"visiveis": 0, "ocultos": 0, "erro": str(e)}
        f.content.uid = uid_seq
        f.write(str(seq_novo))

    os.replace(midias_novo, midias)
    os.replace(seq_novo, seq)

    # ── 4) entregar: SÓ a _SEQ aberta, a timeline no Record — depois de tudo pronto (autor, 2026-10-13: a _MIDIAS
    #       abriu só para receber o LinkFile e já fechou; a da AAF, só para a importação) ──────────────────────────
    p("abrindo no Media Composer", 0, 1, nome_seq)
    aberta = True
    try:
        mc.abrir_bin(str(seq))
    except Exception as e:  # noqa: BLE001
        aberta = False
        log.warning("a bin foi gravada mas não abriu sozinha (%s): %s", e, seq)
    no_record = no_source = False
    if aberta:
        try:
            from sessao_export import mob_id_da_api

            time.sleep(3)
            if _record_pela_api(mc):
                mc.carregar_no_monitor([mob_id_da_api(seq_entregue)], "Record")
                no_record = True
            else:
                mc.carregar_no_monitor([mob_id_da_api(seq_entregue)], "Source")
                no_source = True
        except Exception as e:  # noqa: BLE001
            log.warning("a timeline entregue não foi para o Record (%s)", e)

    resultado = {
        "bin": nome_seq, "bin_midias": nome_midias, "pasta": nome_bin,
        "avb": str(seq), "aberta_no_mc": aberta, "no_record": no_record, "no_source": no_source,
        "masters_online": len(mapa), "masters_pedidos": len(decididos),
        "video_linkado": len(a_linkar) - sum(1 for x in falhas if x["arquivo"] in a_linkar.values()),
        "video_reaproveitado": len(reaproveitar),
        "video_injetado": len(r_video["mapa"]), "video_pelo_link": len(linkado),
        "audio_autorado": r_audio["clipes"], "audio_sem_template": r_audio["sem_template"],
        "audio_esticado": r_audio["esticados"], "audio_curto_demais": r_audio["curtos_demais"],
        "falhas": falhas, "clipes_visiveis": r_vis["visiveis"], "clipes_ocultos": r_vis["ocultos"],
        "subclipes_achatados": r_denest["achatados"], "subclipes_restantes": r_denest["subclipes_restantes"],
        "referencias_trocadas": r_remap["repontados"], "masters_remapeados": r_remap["masters_trocados"],
        "segmentos_cobertos": sum(por_mob[m].segmentos for m in mapa if m in por_mob),
    }
    p("pronto", 1, 1, "")
    log.info("relink organizado aplicado: %s", resultado)
    return resultado
