#!/usr/bin/env python3
"""De Lá Pra Cá — serviço do Media Composer.

Este processo é o plugin. O painel `.avpi` dentro do MC é a interface dele; o motor
(parser AAF, matcher, writers) vem embutido. **Não depende do App De Lá Pra Cá estar
aberto** — o App instala este par uma vez e sai de cena.

Duas conversas, em direções opostas:

    painel  ──HTTP──►  este serviço  ──gRPC──►  Media Composer [::1]:9100
            (7823)                              (sem token — ver avid/mcapi.py)

Rodar em desenvolvimento:

    PYTHONPATH=motor:plugins/media-composer/servico \\
      .venv/bin/python plugins/media-composer/servico/main.py --log debug
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path



# O motor e o cliente do MC são pacotes de topo (ver VENDOR.md → "dívida consciente").
# Em desenvolvimento o PYTHONPATH resolve; empacotado, o PyInstaller resolve. Este
# bloco é a rede para quem roda o arquivo direto, sem preparar nada.
_AQUI = Path(__file__).resolve().parent
for _caminho in (_AQUI, _AQUI.parent.parent.parent / "motor"):
    if str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

import plataforma  # noqa: E402

#: A versão do build (`plataforma.versao`): o selo do rodapé do painel e a dos plugins instalados.
VERSAO = plataforma.versao()
from api import PORTA, iniciar  # noqa: E402
from avid import MediaComposer  # noqa: E402
from sessao import Sessao  # noqa: E402
from sessao_export import SessaoExport  # noqa: E402
from coleta import Coleta  # noqa: E402

log = logging.getLogger("delapraca")


class Servico:
    """O estado do processo. Um só, passado a cada handler pelo servidor."""

    def __init__(self):
        self.versao = VERSAO
        # Um trabalho por vez, de propósito: o painel é de um editor, e o Media
        # Composer é recurso único.
        self.sessao = Sessao(self)
        # A aba Daqui Pra Lá tem a sua: exportar não disputa estado com o relink.
        self.sessao_export = SessaoExport(self)
        # Magic Link: a lista do INSERT PARA COR/VFX, e uma trava para que coletar e enviar
        # nunca rodem juntos — os dois digitam/salvam no Media Composer.
        self.coleta = Coleta()
        self.trava_magic = threading.Lock()
        self.ultimo_envio: dict = {}
        # Lado de quem RECEBE (a casca do Resolve): a caixa de cada canal e o token que ela lê
        # do disco (ADR 0016). O token é publicado em `main`, no arranque.
        from sessao_receber import SessaoReceber, limpar_recebidos

        self.receber = SessaoReceber()
        try:
            n = limpar_recebidos()
            if n:
                log.info("recebidos: %d arquivo(s) de passagem com mais de uma semana apagados", n)
        except OSError:
            log.debug("não consegui limpar recebidos/", exc_info=True)   # acessório: nunca derruba
        self.token: str | None = None
        # `--receptor`: o serviço ligado pela casca do Resolve, sem Media Composer (ver `main`).
        self.receptor = False
        # Onde os AAF reescritos ficam. **Não** numa pasta temporária: quem lê este
        # arquivo é o processo do Media Composer, e no macOS o TCC o impede de ler
        # `/private/tmp`. O caminho por SO mora em `plataforma.py`.
        self.pasta_trabalho = plataforma.pasta_trabalho()
        # Os últimos arrastos que o painel recebeu, para depuração (`/diag/arrasto`).
        #
        # ⭐ Guarda uma HANDFUL, não só o último, e a razão é o tipo de pergunta que esta
        # ferramenta responde: quase toda ela é COMPARATIVA — *o que muda entre arrastar
        # uma pasta e arrastar um arquivo? entre uma e várias?*. Com só o último, cada
        # comparação exigia uma ida e volta entre os dois gestos, e a segunda medição
        # apagava a primeira antes de alguém poder pôr as duas lado a lado.
        #
        # Em memória e limitado: é bancada, não histórico — nada disso sobrevive ao
        # processo, e nada sai da máquina.
        self.arrastos: list = []
        self.MAX_ARRASTOS = 5
        # O executável do aplicativo que subiu este serviço, quando foi ele quem subiu.
        # `None` na bancada (`dev.ps1`) e em qualquer instalação só-plugin — e é por isso
        # que o painel precisa saber cair na vista embutida em vez de prometer a janela.
        self.app_exe: str | None = None

    def media_composer(self) -> MediaComposer:
        """Uma conexão nova com o MC, para usar com `with`.

        Um canal por operação, e não um guardado no serviço: o editor abre e fecha o
        Media Composer enquanto o painel segue aberto, e um canal gRPC que sobreviveu
        ao processo do outro lado falha de um jeito que não parece "o MC fechou". O
        canal é barato; a confusão, não.
        """
        return MediaComposer()


def _configurar_log(nivel: str, origem: str = "serviço") -> None:
    import registro

    logging.basicConfig(
        level=getattr(logging, nivel.upper(), logging.INFO),
        format=registro.FORMATO,
        datefmt="%H:%M:%S",
    )

    # ⭐ **E TAMBÉM EM ARQUIVO.** Até 2026-08-17 o serviço só logava no terminal, e a
    # consequência apareceu no primeiro incidente que exigiu investigação: um relink
    # ficou 3m49s onde antes eram segundos, o Media Composer estourou `ACCESS_VIOLATION`,
    # e **não havia rastro nenhum** para dizer quanto cada etapa custou. Quem viu o
    # problema estava na sala; quem pode depurá-lo, não.
    #
    # Um arquivo só, com rotação e cabeçalho de ambiente (organograma de 2026-10-05,
    # `registro.py`), em `plataforma.pasta_logs()`.
    # ⭐ Os logs mudaram para a pasta do Ciclo Assist (2026-11-07): os de antes vão para o arquivo, ANTES de abrir o novo.
    try:
        movidos = plataforma.arquivar_logs_antigos()
    except Exception:  # noqa: BLE001 — arquivar o velho nunca impede o serviço de subir
        movidos = []
    try:
        log.info("log em arquivo: %s", registro.configurar(origem, VERSAO))
        if movidos:
            log.info("logs antigos arquivados em %s: %s", plataforma.pasta_logs() / "antes-de-2026-11-07",
                     ", ".join(movidos))
    except OSError as e:
        # ⚠️ Não poder gravar log não pode impedir o serviço de subir — o terminal ainda
        # mostra tudo, e o editor precisa trabalhar.
        log.warning("sem log em arquivo (%s) — seguindo só no terminal", e)
    # O motor herdado (`relinker.*`) loga uma linha INFO **por arquivo indexado** —
    # 445 linhas numa varredura, o que afoga o que o serviço tem a dizer. Ele fica em
    # WARNING salvo quando se pede debug de propósito.
    if nivel != "debug":
        logging.getLogger("relinker").setLevel(logging.WARNING)
    _pilhas_por_sinal()


#: O arquivo aberto do `faulthandler` (precisa viver enquanto o serviço vive).
_PILHAS = None


def _pilhas_por_sinal() -> None:
    """POSIX: `kill -USR1 <pid>` despeja as pilhas de TODAS as threads em `pilhas.txt`, ao lado do log.

    Medido em 2026-10-24 (Mac, MC 25.12): logo depois de o MC abrir um projeto, o serviço passou ~3–4 min sem aceitar
    conexões, com a CPU parada e as threads em espera de trava. O `sample` do macOS só mostra as pilhas em C; sem a
    pilha em Python não se sabe QUEM segura a trava. No Windows não há SIGUSR1 (fica sem)."""
    global _PILHAS
    import faulthandler
    import signal

    if not hasattr(signal, "SIGUSR1"):
        return
    try:
        import plataforma

        _PILHAS = open(plataforma.pasta_logs() / "pilhas.txt", "a", encoding="utf-8")
        faulthandler.register(signal.SIGUSR1, file=_PILHAS, all_threads=True)
    except (OSError, AttributeError, ValueError) as e:
        log.debug("sem o despejo de pilhas por sinal (%s)", e)


def vigiar_media_composer(servico, parar: threading.Event, carencia_s: float = 60.0,
                          intervalo_s: float = 5.0) -> None:
    """Encerra o serviço quando o Media Composer sai. Roda em thread daemon.

    Sem isto, fechar o Avid deixa o serviço rodando de fundo até o editor lembrar de
    matá-lo — e ele não tem interface para isso (o start é por `dev.ps1`).

    ⚠️ **Só depois de o MC ter aparecido pelo menos uma vez.** O serviço costuma subir
    ANTES do Avid; encerrar por "não achei o MC" no primeiro segundo mataria o serviço
    justamente enquanto o editor abre o programa.

    ⚠️ **E com carência.** O Media Composer some da lista de processos durante um
    reinício, e a saída do editor de um projeto para outro passa por aí. Um minuto de
    ausência contínua separa "fechou" de "está reabrindo".

    ⚠️ **Nunca encerra no meio de um trabalho.** Um relink em curso está escrevendo bin e
    falando com o MC; morrer ali deixa o projeto do editor pela metade. Se a sessão está
    ocupada, o relógio da carência é zerado.

    ⚠️ **Nem com o painel do Resolve aberto na mesma máquina** (medido 2026-09-28): o autor
    fechou o Avid e, 60 s depois, o serviço saiu no MEIO de um "Atualizar timeline" no Resolve
    — o painel ficou em "serviço fora do ar" / "Failed to fetch". O painel do Resolve bate em
    `/receber/estado` a cada 4 s (`ultimo_uso_receptor`); enquanto ele fala, é uso.
    """
    from plataforma import media_composer_aberto

    ja_vi = False
    ausente_desde: float | None = None
    while not parar.wait(intervalo_s):
        try:
            aberto = media_composer_aberto()
        except Exception:  # noqa: BLE001 — a vigia nunca derruba o serviço
            log.debug("não consegui enumerar processos", exc_info=True)
            continue

        if aberto:
            ja_vi, ausente_desde = True, None
            continue
        if not ja_vi:
            continue                      # ainda não abriu; não é "fechou"
        if servico.sessao.ocupada:
            ausente_desde = None          # trabalho em curso: não conta ausência
            continue
        agora = time.monotonic()
        receptor = getattr(servico, "ultimo_uso_receptor", None)
        if receptor is not None and agora - receptor < carencia_s:
            if ausente_desde is not None:
                log.info("Media Composer fechado, mas o painel do Resolve está em uso — o serviço fica")
            ausente_desde = None          # o painel do Resolve está usando: não conta ausência
            continue

        if ausente_desde is None:
            ausente_desde = agora
            log.info("Media Composer não está mais no ar — aguardando %.0fs", carencia_s)
        elif agora - ausente_desde >= carencia_s:
            log.info("Media Composer fechado há %.0fs — encerrando o serviço", carencia_s)
            parar.set()
            return


def _app_vivo(pid: int):
    """Uma função `() -> bool` que diz se o app `pid` ainda está aberto, ou None se não dá para saber.

    Matriz de plataforma, linha "processo órfão": no Windows o órfão NÃO é readotado e o PID é
    reciclado — então o handle é aberto AGORA (ele prende a identidade do processo) e consultado
    depois; no macOS o órfão passa ao `launchd` (`ppid == 1`)."""
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
        if not h:
            return None
        return lambda: k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102   # WAIT_TIMEOUT = vivo
    if os.getppid() == pid:
        return lambda: os.getppid() == pid

    def vivo() -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    return vivo


def vigiar_app(servico, parar: threading.Event, pid: int, intervalo_s: float = 2.0) -> None:
    """Encerra o serviço quando o APLICATIVO que o subiu fecha, por qualquer caminho.

    ⛔ VISTO 2026-10-04 (Windows, autor): depois do `ATUALIZAR.bat`, o app fechou e o motor ficou
    no ar, órfão — o painel do Resolve seguia "conectado" sem o app (contra a regra: o app é o dono
    do motor). Até aqui só o app o matava, ao fechar a janela (`lib.rs`, `Destroyed`); um app que
    sai por outro caminho (atualizador, travamento, Gerenciador de Tarefas) deixava o motor vivo. E
    no Windows o app mata o LANÇADOR do venv (`Scripts\\python.exe`), não o Python que ele abre.
    ⚠️ Nunca no meio de um trabalho: espera o Importar/relink em curso terminar."""
    vivo = _app_vivo(pid)
    if vivo is None:
        log.warning("não consigo vigiar o aplicativo (pid %d): o motor depende dele me encerrar", pid)
        return
    while not parar.wait(intervalo_s):
        if vivo():
            continue
        if servico.sessao.ocupada or servico.receber.progresso().get("ativo"):
            continue                       # trabalho em curso: encerra quando terminar
        log.info("o aplicativo (pid %d) fechou — encerrando o serviço", pid)
        parar.set()
        return


def vigiar_ociosidade(servico, parar: threading.Event, ocioso_s: float,
                      intervalo_s: float = 30.0) -> None:
    """Modo receptor: encerra quando o script do Resolve para de falar por `ocioso_s`."""
    servico.ultimo_uso_receptor = time.monotonic()
    while not parar.wait(intervalo_s):
        if time.monotonic() - getattr(servico, "ultimo_uso_receptor", 0) >= ocioso_s:
            log.info("receptor sem uso há %.0f min — encerrando", ocioso_s / 60)
            parar.set()
            return


#: O motor montado (PyInstaller) não tem um Python para rodar o `dialogo_win.py` como processo filho:
#: ele mesmo vira o diálogo com esta opção (`escolher._dialogo_win_moderno`). Sem isso, o seletor caía
#: no antigo, em árvore — uma degradação calada (organograma do instalador, 2026-10-05).
ARG_DIALOGO = "--dialogo-win"


def _arquivo_de_verdade(caminho) -> bool:
    """Existe, não está vazio e não é um atalho `XSym` (o symlink que o exFAT grava como arquivo de texto de ~1 KB):
    existir não é estar (banco, bugs-do-mundo-real B034)."""
    try:
        if not os.path.isfile(caminho) or os.path.getsize(caminho) == 0:
            return False
        with open(caminho, "rb") as f:
            return f.read(5) != b"XSym\n"
    except OSError:
        return False


def conferir_pacote() -> int:
    """`--conferir-pacote`: o motor MONTADO acha tudo o que lê do disco e carrega as bibliotecas
    pesadas? (`tools/montar_motor.py` roda isto depois de montar.) Um arquivo de dados que não
    entrou no pacote não dá erro de montagem — dá erro no meio de um Importar."""
    import json as _json

    itens: dict[str, bool] = {"versao": VERSAO != "0.0.0"}
    from api.servidor import DIR_UI
    from avb_export import media_bin, translate
    from drp import writer
    from presets import _RECURSO
    from titulos import resolve as titulos_resolve

    for nome, caminho in (("painel.html", DIR_UI / "painel.html"), ("painel.js", DIR_UI / "painel.js"),
                          ("preset_aaf.xml", _RECURSO), ("formas_r19.xml", writer.FORMAS_NATIVAS),
                          ("formas_r21_arriraw.xml", writer.FORMA_ARRIRAW),
                          ("formas_r21_still.xml", writer.FORMA_STILL), ("mesa99", writer.MESA_99),
                          ("texto_r19.xml", titulos_resolve.FORMA),
                          ("skeleton_r19.drt", os.path.join(os.path.dirname(writer.FORMAS_NATIVAS),
                                                            writer.ESQUELETO_PADRAO)),
                          ("templates.json", translate.TEMPLATES_JSON),
                          ("manifest.json", os.path.join(media_bin.TEMPLATE_DIR, "manifest.json"))):
        itens[nome] = _arquivo_de_verdade(caminho)
    # o seletor de pasta moderno só existe no Windows (no Mac é o `osascript`, `escolher.py`)
    for modulo in ("cv2", "numpy", "aaf2", "avb", "imagehash", "grpc") + (("dialogo_win",) if os.name == "nt" else ()):
        try:
            __import__(modulo)
            itens[modulo] = True
        except Exception:  # noqa: BLE001 — a lista diz qual faltou
            itens[modulo] = False
    try:
        from pymediainfo import MediaInfo

        itens["mediainfo"] = bool(MediaInfo.can_parse())
    except Exception:  # noqa: BLE001
        itens["mediainfo"] = False
    # o ffmpeg/ffprobe que vieram DENTRO do motor (montado, `fftools` nunca olha o PATH)
    import subprocess as _sp

    from media import fftools

    for nome, exe in (("ffmpeg", fftools.ffmpeg()), ("ffprobe", fftools.ffprobe())):
        try:
            r = _sp.run([exe, "-version"], capture_output=True, timeout=30, **fftools.SEM_JANELA)
            itens[nome] = r.returncode == 0 and b"version" in r.stdout
        except (OSError, TypeError, _sp.SubprocessError):
            itens[nome] = False
    print(_json.dumps({"versao": VERSAO, "itens": itens}, ensure_ascii=False))
    return 0 if all(itens.values()) else 1


def _console_utf8() -> None:
    """stdout/stderr em UTF-8, como todo leitor deles espera (o app, `lib.rs::liberar_porta`; o
    `montar_motor.py`; o `escolher.py`). ⛔ MEDIDO 2026-10-09 (Win11, Python 3.12.5): sem isto o pipe
    sai em cp1252 — "Área" chegava ao app como lixo e "テイク" derrubava o `--liberar-porta` com
    UnicodeEncodeError. Aqui, no ponto de entrada do PRODUTO: o PYTHONUTF8 do atualizar.ps1 não
    chega ao app instalado (banco, bugs-do-mundo-real B100). Sem console (o app lança o serviço
    sem janela), o fluxo é None e fica como está."""
    for fluxo in (sys.stdout, sys.stderr):
        if fluxo is not None and hasattr(fluxo, "reconfigure"):
            try:
                fluxo.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (ValueError, OSError):
                pass


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _console_utf8()
    if argv[:1] == [ARG_DIALOGO]:
        import dialogo_win

        return dialogo_win.main(argv[1:])
    if argv[:1] == ["--conferir-pacote"]:
        return conferir_pacote()
    ap = argparse.ArgumentParser(description="Serviço do Media Composer — De Lá Pra Cá")
    ap.add_argument("--porta", type=int, default=PORTA)
    ap.add_argument("--log", default="info", choices=["debug", "info", "warning", "error"])
    ap.add_argument("--sair-com-o-mc", dest="vigiar", action="store_true", default=True,
                    help="encerra o serviço quando o Media Composer fechar (padrão)")
    ap.add_argument("--nao-sair-com-o-mc", dest="vigiar", action="store_false",
                    help="mantém o serviço no ar mesmo sem o Media Composer")
    ap.add_argument("--carencia", type=float, default=60.0,
                    help="segundos de ausência do MC antes de encerrar (padrão: 60)")
    # ⭐ Modo de UMA AÇÃO, para o aplicativo poder oferecer "liberar a porta" sem
    # embutir a lógica dele próprio: quem sabe reconhecer um gateway órfão é a camada
    # de plataforma, e ela viaja com o serviço. Sai em JSON porque quem lê é programa.
    ap.add_argument("--liberar-porta", action="store_true",
                    help="mata o gateway órfão do Panel SDK e sai (imprime JSON)")
    ap.add_argument("--todos", action="store_true",
                    help="com --liberar-porta: mata qualquer gateway, não só o órfão")
    # ⭐ Quem sobe o serviço na instalação do editor é o APLICATIVO, e ele se apresenta
    # aqui com o próprio caminho. O serviço usa isso para reinvocá-lo quando o painel
    # pede a janela de revisão (ver `rotas.app_revisao`).
    #
    # ⚠️ Por que RECEBER e não PROCURAR: uma busca por Program Files / %LOCALAPPDATA% /
    # `target/debug` apodrece a cada mudança de empacotamento e erra do jeito mais caro —
    # achando uma build velha, que abre e não conversa com este serviço. Sem este
    # argumento o serviço simplesmente não conhece app nenhum, e diz isso ao painel.
    ap.add_argument("--app", dest="app", default=None,
                    help="caminho do executável do aplicativo que subiu este serviço")
    ap.add_argument("--pai", type=int, default=None,
                    help="PID do aplicativo que subiu este serviço: ele fechou, o serviço encerra")
    # ⭐ Magic Link: na máquina do RESOLVE não há Media Composer — o vigia derrubaria o
    # serviço em 60 s. Quem sobe neste modo é o script do Resolve (`receptor.json`), e o
    # serviço encerra sozinho depois de um tempo sem uso.
    # A bancada de quem programa (`dev.sh`/`dev.ps1`) sobe o motor sem o app: ela se declara, e a
    # prontidão a aceita. Fora dela, motor sem app é motor órfão (memória `app-obrigatorio-…`).
    ap.add_argument("--bancada", action="store_true",
                    help="motor da bancada de desenvolvimento (sem o aplicativo)")
    ap.add_argument("--receptor", action="store_true",
                    help="modo de quem recebe (Resolve): sem vigia do MC, encerra ocioso")
    ap.add_argument("--ocioso", type=float, default=30 * 60.0,
                    help="com --receptor: segundos sem uso antes de encerrar (padrão: 1800)")
    args = ap.parse_args(argv)

    if args.liberar_porta:
        import json as _json

        print(_json.dumps(plataforma.liberar_gateway(todos=args.todos),
                          ensure_ascii=False))
        return 0

    # ANTES de qualquer ffprobe (e do cabeçalho do log, que diz onde ele está): o serviço subido
    # pela casca do Resolve (ou por qualquer `.app`) no macOS nasce sem o Homebrew no PATH (ver
    # `plataforma.completar_path`).
    novas = plataforma.completar_path()
    origem = ("receptor do Resolve" if args.receptor else "bancada" if args.bancada
              else "aplicativo" if args.app else "serviço")
    _configurar_log(args.log, origem)
    log.info("De Lá Pra Cá %s — serviço do Media Composer", VERSAO)
    if novas:
        log.info("PATH completado com %s (processo lançado por app)", ", ".join(novas))
    from media import fftools as _fftools
    if not _fftools.ffprobe():
        log.warning("ffprobe NÃO encontrado no PATH (%s): sem ele, TC e duração das mídias não se "
                    "leem e a timeline sai offline", os.environ.get("PATH", ""))

    servico = Servico()
    servico.bancada = bool(args.bancada)
    if args.app:
        # ⚠️ Confere que o caminho EXISTE agora, no arranque, e não na hora do clique. Um
        # `--app` que não aponta para arquivo nenhum só apareceria quando o editor
        # pedisse a revisão — no meio do trabalho, e com cara de defeito da revisão.
        if Path(args.app).is_file():
            servico.app_exe = args.app
            log.info("aplicativo que me subiu: %s", args.app)
            # Onde está o app, para a tela de espera da casca do Resolve oferecer "Abrir o De Lá Pra
            # Cá" quando o motor estiver fora do ar (a casca não sobe mais o motor: memória
            # `app-obrigatorio-ordem-nao-importa`). Só o caminho; quem lê confere que existe.
            try:
                import json as _json
                (plataforma.pasta_dados() / "aplicativo.json").write_text(
                    _json.dumps({"executavel": str(Path(args.app).resolve())}), encoding="utf-8")
            except OSError as e:
                log.warning("não gravei aplicativo.json: %s", e)
        else:
            log.warning("--app aponta para um arquivo que não existe: %s", args.app)
            log.warning("a revisão vai abrir dentro do painel, não em janela própria")

    try:
        servidor, _ = iniciar(servico, args.porta)
    except OSError as e:
        # O caso comum é outra instância já no ar. Dizer isso é mais útil que o errno.
        log.error("não consegui abrir a porta %d: %s", args.porta, e)
        log.error("outra instância do serviço já está rodando?")
        return 1

    # ⭐ Fase 4 do plano um app só (2026-11-07): sem token de arquivo. Ele existia só para o script e o painel DENTRO do
    # Resolve (ADR 0016), que saíram; sem token publicado, o portão recusa quem chega sem origem (`portao.py`).

    parar = threading.Event()
    servico.parar = parar                       # `/receber/motor/ceder` (o app assume a porta)
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    signal.signal(signal.SIGTERM, lambda *_: parar.set())

    # Quem pergunta sem dizer o NLE (a casca do Resolve no `GET /receber/estado`) está fora do
    # Media Composer: as rotas de canais NÃO podem ir perguntar ao MC — isso estourava o teto
    # de 3 s da casca, que concluía "serviço fora do ar" e subia outro (ver `rotas._nle`).
    servico.receptor = bool(args.receptor)
    if args.receptor:
        args.vigiar = False
        threading.Thread(target=vigiar_ociosidade, args=(servico, parar, args.ocioso),
                         name="delapraca-ocioso", daemon=True).start()
        log.info("modo receptor: encerra depois de %.0f min sem uso", args.ocioso / 60)

    if servico.app_exe and args.vigiar:
        # O APLICATIVO é o dono do motor nos três NLEs (autor, 2026-10-04 — memória
        # `app-obrigatorio-ordem-nao-importa`): ele o encerra ao fechar a janela principal
        # (`lib.rs`, `WindowEvent::Destroyed`). Fechar o Avid não pode derrubar o motor de quem está
        # no Resolve com o app aberto.
        args.vigiar = False
        log.info("subido pelo aplicativo: o serviço vive enquanto ele estiver aberto")
    if servico.app_exe and args.pai:
        threading.Thread(target=vigiar_app, args=(servico, parar, args.pai),
                         name="delapraca-app", daemon=True).start()
        log.info("vigiando o aplicativo (pid %d): fechou, o serviço encerra", args.pai)

    if servico.app_exe:
        # o aviso de versão nova: ao subir pelo app e a cada 6 horas (organograma de 2026-10-05)
        import versao_nova

        threading.Thread(target=versao_nova.vigiar, args=(parar,), name="delapraca-versao", daemon=True).start()

    if args.vigiar:
        threading.Thread(target=vigiar_media_composer,
                         args=(servico, parar, args.carencia),
                         name="delapraca-vigia", daemon=True).start()
        log.info("o serviço encerra sozinho %.0fs depois de o Media Composer fechar",
                 args.carencia)

    log.info("painel: http://127.0.0.1:%d/painel", args.porta)
    try:
        parar.wait()
    finally:
        log.info("encerrando")
        servidor.shutdown()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
