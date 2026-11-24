"""Abrir e fechar o Media Composer, e abrir ou CRIAR um projeto nele — ops. 2 e 4 do ensaio.

O MC não tem RPC para nada disto no 2024.6 (sem `DoCommand`, sem `OpenProject`, sem `Quit`):
é o piloto (`cicloassist/piloto`) — foto da TELA, o localizador acha e CONFERE o ponto, o clique
só com uma janela do MC na frente. Tudo o que se sabe da tela vem do banco
(`skills/piloto/SKILL.md`, `transversal/operacoes.md`):

- ⛔ **O MC abre SEM foco, e o aviso de idioma do teclado só nasce no 1º foco** (título
  "AvidMediaComposer", o MESMO do progresso de abrir projeto). Resposta: **"Don't warn me
  again"**, nunca OK (o OK volta no meio do trabalho — autor, 31/10). Voltou em 01/11 mesmo
  assim: tratar sempre.
- ⛔ Posição de clique de outra abertura não vale: foto DESTA abertura (o localizador).
- ⛔ **Format ▸ HD 1080 abre por CLIQUE** (passar o mouse não abre) — New Project, MC 2024.6.
- ⛔ Menu e lista suspensa são janelas de topo à parte: foto da TELA, nunca da janela.
- ⭐ **Sair = File → Exit → "Leave the application?" → Leave** (~10 s até o processo sumir).
- ⭐ **A prova de que o projeto abriu é o TÍTULO da janela principal**: `Avid Media Composer
  - <projeto>` (medido 2026-11-01, MC 2024.6). Nada de "o clique deu certo".

- ⭐⭐ **Projeto que já existe abre pelo TECLADO, sem foto nem modelo** (`_abrir_pelo_teclado`, medido em 2026-11-09). A foto fica para criar projeto e para quando o teclado não andar.

⬜ macOS: `pendente` (o piloto do Assist é só Windows).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .. import janela as _janela
from ..piloto import auxilio as _auxilio
from ..piloto import espaco, localizador, maos, tela
from . import socorro as _socorro

log = logging.getLogger("cicloassist.avid.abrir")

EXE = "AvidMediaComposer.exe"
CAMINHO = r"C:\Program Files\Avid\Avid Media Composer\AvidMediaComposer.exe"
AVISO = "AvidMediaComposer"

PRAZO_DE_ABRIR_S = 300.0       # do lançamento ao projeto aberto, com a Select Project no meio
PRAZO_DE_SAIR_S = 120.0        # MEDIDO 2026-11-02: 30,6 · 31,5 · 66,8 s e um > 60 s (layout livre, depois de sync)
#: ⛔⛔ Depois do Leave o MC pode ficar MINUTOS saindo, "Not Responding" (MEDIDO 2026-11-04: ~3,5 min, 1,2 GB,
#: depois de um dia de syncs e conversões no projeto). Com o Leave dado, a saída está em curso: esperar o
#: processo, conferindo-o, em vez de dar o MC por travado aos 120 s — o modelo tentou de novo, o File → Exit
#: caiu numa janela travada (sem foco) e a diária D05 parou no 1º passo.
PRAZO_DEPOIS_DO_LEAVE_S = 600.0
MAXIMO_DE_VOLTAS = 18          # cada volta é no máximo uma pergunta ao localizador (~US$ 0,01)

#: O grupo do menu Format do New Project para cada formato. Só o que foi VISTO no 2024.6.
GRUPOS = {"1080": "HD 1080", "720": "HD 720"}

Relatar = Callable[[str, float | None, str], None]


class McNaoAbre(RuntimeError):
    """Não deu para abrir, criar ou fechar no Media Composer — a frase diz o que se viu."""


class McPreso(McNaoAbre, _auxilio.TelaInesperada):
    """A tela não anda como o script espera: é aqui que o agente do piloto entra."""


def _sem_relato(*_):
    return None


def projeto_do_titulo(titulo: str) -> str:
    """`Avid Media Composer  - desktop` → `desktop`; sem projeto → ""."""
    m = re.match(r"^Avid Media Composer\s+-\s+(.+?)\s*$", titulo or "")
    return m.group(1) if m else ""


def grupo_do_formato(formato: str) -> str:
    """`1080p/25` → `HD 1080`. Formato que não está na tabela é recusado ANTES da tela."""
    m = re.match(r"^(\d{3,4})[pi]/", (formato or "").strip())
    if not m or m.group(1) not in GRUPOS:
        raise McNaoAbre(f"não sei criar projeto no formato {formato!r} ainda; sei: "
                        + ", ".join(f"{k}p/<taxa>" for k in GRUPOS))
    return GRUPOS[m.group(1)]


def aberto() -> bool:
    return bool(_janela.janelas(EXE)) or _processo_vivo()


def _processo_vivo() -> bool:
    if sys.platform != "win32":
        return False
    p = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE}", "/NH"], capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=10, creationflags=0x08000000)
    return EXE.lower() in (p.stdout or "").lower()


def projeto_aberto() -> str:
    """O projeto aberto no MC, pelo título da janela principal, ou "" (fechado ou na Select Project).

    ⛔ MEDIDO (2026-11-01): depois de File → Close Project o título CONTINUA com o projeto
    fechado. Com a Select Project à vista, não há projeto aberto, diga o título o que disser."""
    if _janela_com_titulo(SELECT_PROJECT):
        return ""
    for _h, titulo, _r in _janela.janelas(EXE):
        nome = projeto_do_titulo(titulo)
        if nome:
            return nome
    return ""


# ── as mãos sobre o MC ───────────────────────────────────────────────────────

#: ⭐ MEDIDO (2026-11-01, Win 2024.6): a Select Project é uma janela PRÓPRIA, com este título, e
#: abre ATRÁS da principal (vazia, só menus) — foco na principal mostra um MC "sem nada".
SELECT_PROJECT = "Select Project"


def _janela_com_titulo(titulo: str) -> int:
    for h, t, _r in _janela.janelas(EXE):
        if t.strip() == titulo:
            return h
    return 0


def _de_trabalho() -> int:
    """A Select Project se ela existir, senão a principal — nunca "a da frente"."""
    return _janela_com_titulo(SELECT_PROJECT) or _janela.janela_principal(EXE, "Avid Media Composer") or 0


def _aviso_na_tela() -> int:
    """O aviso (ou barra) pequeno "AvidMediaComposer", se houver.

    ⛔⛔ MEDIDO (2026-11-02): com o aviso de teclado MODAL na tela a principal fica desabilitada e
    o Windows RECUSA pô-la na frente — sem janela nenhuma na frente (o app tinha acabado de sair
    dela), o `_frente_do_mc` falhava calado por 302 s e o aviso nunca era respondido. Quem aceita
    o foco é o aviso."""
    return next((h for h, _r in _avisos() if _janela.habilitada(h)), 0)


def _barra_presa(janelas) -> bool:
    """A janela pequena "AvidMediaComposer" é uma barra PRESA, e não um aviso?

    ⛔⛔ MEDIDO (2026-11-03, MC 2024.6, um monitor, teste do chat): a barra de carregar (402×125)
    ficou VISÍVEL e DESABILITADA atrás da Select Project, que estava habilitada e livre, por mais de
    3 min. Contada como aviso, o abrir nunca agia na Select Project, perguntava ao localizador pelo
    "Don't warn me again" a cada 4 s e, passados 60 s, desistia dizendo "há um aviso na tela" — com
    a tela limpa. ⇒ Um aviso MODAL de verdade fica HABILITADO e desabilita a Select Project; com a
    Select Project habilitada e nenhuma pequena habilitada, não há aviso nenhum."""
    pequenas = [h for h, t, r in janelas if t == AVISO and _janela.aviso(r) and not _janela.e_popup(h)]
    select = [h for h, t, _r in janelas if t.strip() == SELECT_PROJECT]
    return (bool(pequenas) and bool(select) and _janela.habilitada(select[0])
            and not any(_janela.habilitada(h) for h in pequenas))


def _avisos() -> list[tuple[int, tuple[int, int, int, int]]]:
    """As janelas pequenas "AvidMediaComposer", a HABILITADA primeiro.

    ⛔⛔ MEDIDO (2026-11-02, monitor 2 à esquerda): a barra de carregar E o aviso de teclado ao
    mesmo tempo — a barra vazia na frente, DESABILITADA (o modal bloqueia), e o aviso habilitado
    nascido ATRÁS da principal. Pegando a primeira da lista, o abrir procurou o "Don't warn me
    again" na barra 12 vezes. O habilitado é o modal: focado, ele vem para a frente."""
    achadas = [(h, r) for h, t, r in _janela.janelas(EXE)
               if t == AVISO and _janela.aviso(r) and not _janela.e_popup(h)]     # menu ≠ aviso
    return sorted(achadas, key=lambda a: not _janela.habilitada(a[0]))


def _frente_do_mc() -> int:
    """A janela do MC que está na frente — a Select Project se ela existir, senão a principal."""
    frente = maos.da_frente()
    dialogo = _janela_com_titulo(SELECT_PROJECT)
    aviso = _aviso_na_tela()
    if aviso:
        _janela.ao_topo(aviso)       # ⛔ ter o foco não o põe por cima (medido: 8 janelas acima)
    if frente and frente in (dialogo, aviso):
        return frente
    # ⛔ Um aviso modal HABILITADO tem de vir para a frente, mesmo com outra janela do MC lá:
    #   ele pode ter nascido ATRÁS da principal (medido 2026-11-02), e a foto não o veria.
    if not dialogo and not aviso and _janela.exe_da_janela(frente).lower() == EXE.lower():
        return frente
    # ⛔⛔ O aviso ANTES da Select Project. MEDIDO (2026-11-08): com o aviso de teclado sobre ela, a Select Project fica desabilitada e o Windows
    #   recusa o foco, volta após volta (o abrir ficaria preso até o prazo de 300 s).
    principal = _aviso_na_tela() or dialogo or _janela.janela_principal(EXE, "Avid Media Composer")
    # ⚠️ MEDIDO (2026-11-01): com a barra de carregar do MC na tela, o foco é recusado por um
    #   instante. Algumas tentativas antes de desistir.
    limite = time.monotonic() + 4.0
    while not (principal and _janela.focar(principal)):
        if time.monotonic() > limite:
            if _socorro.inesperada():
                raise McPreso("há uma janela do Media Composer que o script não conhece bloqueando as outras")
            raise McNaoAbre("o Windows não deixou pôr o Media Composer na frente")
        time.sleep(0.5)
        dialogo = _janela_com_titulo(SELECT_PROJECT)
        principal = _aviso_na_tela() or dialogo or _janela.janela_principal(EXE, "Avid Media Composer")
    time.sleep(0.3)
    frente = maos.da_frente()
    if _janela.exe_da_janela(frente).lower() != EXE.lower():
        raise McNaoAbre("outra janela tomou a frente do Media Composer")
    return frente


#: (alvo, retângulo da janela) → ponto de TELA que já foi achado E conferido. Na memória do
#: serviço, de propósito: a próxima abertura do MC pode desenhar tudo em outro lugar, e aí a
#: conferência falha e o ponto cai.
_PONTOS: dict[tuple, tuple[int, int]] = {}


class _Piloto:
    """Uma operação: soma o custo das perguntas e guarda o que se viu, para a resposta."""

    def __init__(self, relatar: Relatar):
        self.relatar = relatar
        self.custo = 0.0
        self.passos: list[str] = []
        self.aviso_sem_teclado = False

    def achar(self, alvo: str) -> tuple[int, int]:
        hwnd = _frente_do_mc()
        # ⭐ Só o monitor da janela de TRABALHO (dois monitores = 3840 px reduzidos a 1366) — e não
        #   o da frente: no layout de dois monitores a da frente pode ser a do Composer/Timeline.
        a = localizador.localizar(tela.fotografar(), alvo, regiao=tela.monitor_da_janela(_de_trabalho()))
        self.custo += a.custo_usd
        return hwnd, a.x, a.y

    def clicar(self, alvo: str, espera: float = 0.5) -> None:
        hwnd, x, y = self.achar(alvo)
        maos.clicar(hwnd, x, y)
        self.passos.append(f"clique: {alvo[:60]}")
        time.sleep(espera)

    def no_menu(self, menu: str, item: str, prazo: float = 3.0) -> None:
        """Abre `menu` e clica `item` — esperando a janela do MENU nascer, nunca um tempo fixo.

        ⛔ MEDIDO (2026-11-01): 0,4 s depois do clique o File ainda não estava aberto, e o banco já
        dizia "abrir o menu, esperar ~1 s". ⭐ O menu Qt é uma janela de topo NOVA do processo:
        esperar por ela custa nada, e o item é procurado SÓ nela (foto pequena, resposta rápida)."""
        antes = {h for h, _t, _r in _janela.janelas(EXE)}

        def esperar_menu(segundos: float):
            limite = time.monotonic() + segundos
            while time.monotonic() < limite:
                novas = [r for h, _t, r in _janela.janelas(EXE) if h not in antes]
                if novas:
                    return max(novas, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
                time.sleep(0.1)
            return None

        # ⛔ MEDIDO (2026-11-01, 2024.6): Alt+F NÃO abre o File, apesar do F sublinhado. O clique,
        #   com o ponto guardado por janela (`achar_varios`): da 2ª vez, só a conferência.
        principal = _janela.janela_principal(EXE, "Avid Media Composer")
        regiao = next((r for h, _t, r in _janela.janelas(EXE) if h == principal), None)
        m = self.achar_varios({"menu": f"o menu {menu} na barra de menus do Media Composer"}, regiao)
        self.clicar_em(m["menu"], f"menu {menu}", espera=0.0)
        nova = esperar_menu(prazo)
        if nova is None:
            raise localizador.NaoAchei(f"o menu {menu} não abriu em {prazo:.0f} s")
        time.sleep(0.15)                      # o menu termina de se desenhar
        a = self.achar_varios({"item": f"o item {item} do menu {menu}"}, nova)
        self.clicar_em(a["item"], f"{menu} > {item}", espera=0.3)

    def abrir_lista(self, achado: Any, rotulo: str, prazo: float = 3.0):
        """Clica algo que abre uma lista/submenu e devolve o retângulo da janela NOVA (ou None)."""
        antes = {h for h, _t, _r in _janela.janelas(EXE)}
        self.clicar_em(achado, rotulo, espera=0.0)
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            novas = [r for h, _t, r in _janela.janelas(EXE) if h not in antes]
            if novas:
                time.sleep(0.15)
                return max(novas, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
            time.sleep(0.1)
        return None

    def achar_varios(self, alvos: dict[str, str],
                     regiao: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
        """Uma foto, UMA pergunta para todos os alvos, as conferências em paralelo (`localizar_varios`).

        ⭐ Ponto GUARDADO por (alvo, janela no mesmo lugar e tamanho) — o que o `salvar_tudo` já faz:
        quando todos os alvos têm ponto guardado, a pergunta de achar é pulada e só a CONFERÊNCIA
        roda (numa foto nova, com a cruz) — metade do tempo, a mesma segurança. Falhou uma,
        esquece e acha de novo."""
        _frente_do_mc()
        foto = tela.fotografar()
        chave = tuple(regiao) if regiao else None
        guardados = {k: _PONTOS.get((alvo, chave)) for k, alvo in alvos.items()}
        if all(guardados.values()):
            achados, s, c = localizador.conferir_varios(
                foto, {k: (guardados[k][0], guardados[k][1], alvos[k]) for k in alvos})
            self.custo += c
            if all(isinstance(v, localizador.Achado) for v in achados.values()):
                log.info("piloto: %d alvo(s) só conferidos em %.1f s", len(alvos), s)
                return achados
            for alvo in alvos.values():
                _PONTOS.pop((alvo, chave), None)
        achados, s, c = localizador.localizar_varios(foto, alvos, regiao)
        self.custo += c
        for k, v in achados.items():
            if isinstance(v, localizador.Achado):
                _PONTOS[(alvos[k], chave)] = (v.x, v.y)
        log.info("piloto: %d alvo(s) em %.1f s — %s", len(alvos), s,
                 {k: ("ok" if isinstance(v, localizador.Achado) else "não") for k, v in achados.items()})
        return achados

    def clicar_em(self, achado: Any, rotulo: str, espera: float = 0.3) -> None:
        if not isinstance(achado, localizador.Achado):
            raise achado if isinstance(achado, Exception) else McNaoAbre(f"sem ponto para {rotulo}")
        maos.clicar(_frente_do_mc(), achado.x, achado.y)
        self.passos.append(rotulo)
        time.sleep(espera)

    def tela_da_frente(self) -> tuple[str, str]:
        """Qual tela do MC está à frente (pergunta ao modelo). Devolve (tela, o que viu)."""
        _frente_do_mc()
        foto = tela.fotografar().recorte(tela.monitor_da_janela(_de_trabalho()))
        r, _s, c = localizador.perguntar(tela.jpeg(foto.img, localizador.LARGURA), (
            "Esta é a tela do computador com o Avid Media Composer. Qual destas telas do Media "
            "Composer está À FRENTE? Responda {\"tela\": \"aviso_teclado\" | \"selecionar_projeto\" | "
            "\"novo_projeto\" | \"carregando\" | \"sair\" | \"principal\" | \"outra\", \"o_que_vi\": \"<curto>\"}. "
            "aviso_teclado = aviso sobre o idioma/layout do teclado; selecionar_projeto = a janela "
            "Select Project com a aba Projects mostrando a LISTA de projetos; novo_projeto = a mesma "
            "janela com a aba New Project à mostra (campos de nome e Format do projeto novo); "
            "carregando = barra de progresso ou splash; sair = a pergunta 'Leave the application?'; "
            "principal = o MC com um projeto aberto (bins, monitores, timeline)."))
        self.custo += c
        return str(r.get("tela") or "outra"), str(r.get("o_que_vi") or "")


# ── abrir ────────────────────────────────────────────────────────────────────

def _lancar() -> None:
    # ⛔ Pelo explorer: o MC nasce filho DELE, como no duplo clique (o mesmo motivo do Resolve).
    subprocess.Popen(["explorer.exe", CAMINHO], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _mesmo_formato(lido: str, pedido: str) -> bool:
    """O Format mostra o pedido? `lido` é o texto do campo (achado) ou a descrição do que está sob
    a cruz (só conferido) — por isso "contém", com fronteira: 1080p/25 não casa 1080p/250."""
    n = lambda s: re.sub(r"\s+", "", (s or "").lower())  # noqa: E731
    alvo = re.escape(n(pedido))
    return bool(lido) and re.search(rf"(?<![\w.]){alvo}(?![\w.])", n(lido)) is not None


_CAMINHO_NO_MCSTATE = re.compile(rb"([A-Za-z])//([^\x00-\x1f]{3,400}?)/(?=[\x00-\x1f])")


def _location_do_mcstate() -> Path | None:
    """A Location que a Select Project MOSTRA: a pasta de cima do último projeto aberto, gravado no `MCState` do perfil.

    ⛔ MEDIDO (2026-11-19, MC 2024.6, Windows): a Location fica a última escolhida (aqui `D:\\MIDIAS DE TESTES\\…\\PROJETO`),
    e o projeto criado ali "não estava na lista" para quem olhava só `Documents\\Avid Projects` — o abrir pedia o formato
    para CRIAR de novo um projeto que existia. O `MCState` (`Public\\Documents\\Avid Media Composer\\Avid Users\\<perfil>\\`)
    guarda o caminho no formato do Avid, `D//pasta/…/projeto/`. Mac: `pendente`."""
    if sys.platform != "win32":
        return None
    raiz = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Documents" / "Avid Media Composer" / "Avid Users"
    try:
        estados = sorted(raiz.glob("*/MCState"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for arq in estados:
        try:
            dados = arq.read_bytes()
        except OSError:
            continue
        for letra, resto in _CAMINHO_NO_MCSTATE.findall(dados):
            texto = resto.decode("utf-8", "replace")
            if "Avid Users" in texto:            # a pasta do próprio perfil, não um projeto
                continue
            projeto = Path(f"{letra.decode()}:/{texto}")
            if projeto.parent.is_dir():
                return projeto.parent
    return None


def pasta_de_projetos() -> Path:
    """A Location da Select Project: a do `MCState` (a última usada) e, sem ela, a padrão (medida:
    `C:\\Users\\<eu>\\Documents\\Avid Projects\\`)."""
    return _location_do_mcstate() or Path.home() / "Documents" / "Avid Projects"


def _regiao_select_project() -> tuple[int, int, int, int] | None:
    return next((r for _h, t, r in _janela.janelas(EXE) if t.strip() == SELECT_PROJECT), None)


def _novo_projeto(p: _Piloto, projeto: str, formato: str) -> None:
    """A aba New Project à mostra: nome, Format (só se não estiver certo) e Create.

    ⭐ Uma pergunta acha os três e LÊ o Format: o MC lembra o último formato, e quando ele já é
    o pedido, os três cliques da lista suspensa não acontecem.

    ⛔⛔ O retângulo é lido AQUI, depois da troca de aba — nunca herdado. MEDIDO (2026-11-02,
    dois monitores): levada ao monitor de 100 % a Select Project encolhe (1352×759 → 1082×607,
    a razão das escalas) e a aba New Project a ESTICA para 1082×751. Com a região de antes, o
    rodapé ficava fora do recorte e o Create "não existia"."""
    regiao = _regiao_select_project()
    grupo = grupo_do_formato(formato)
    p.relatar("criando o projeto no Media Composer", None, f"{projeto} · {formato}")
    a = p.achar_varios({
        "nome": "o campo de texto Project name",
        "format": "a lista suspensa Format (o campo que mostra o formato atual, ex. 1080p/25)",
        # ⭐ MEDIDO (2026-11-01, 2024.6): o botão é Create, no rodapé, ao lado de Quit.
        "create": "o botão Create no rodapé (ao lado de Quit)",
    }, regiao)
    p.clicar_em(a["nome"], "campo do nome", espera=0.2)
    hwnd = _frente_do_mc()
    maos.tecla(hwnd, ord("A"), maos.VK_CONTROL)
    maos.digitar(hwnd, projeto)
    p.passos.append("nome digitado")
    lido = a["format"].o_que_vi if isinstance(a["format"], localizador.Achado) else ""
    if _mesmo_formato(lido, formato):
        p.passos.append(f"Format já era {formato}")
    else:
        # ⭐ Lista e submenu são janelas NOVAS: espera-se por elas e procura-se só nelas. Sem
        #   janela nova (não medido se o Qt a cria aqui), a tela inteira.
        lista = p.abrir_lista(a["format"], "lista Format")
        g = p.achar_varios({"grupo": f"o item '{grupo}' na lista suspensa Format que está aberta"}, lista)
        sub = p.abrir_lista(g["grupo"], grupo)
        f = p.achar_varios({"formato": f"o item '{formato}' no submenu de {grupo} que está aberto"}, sub)
        p.clicar_em(f["formato"], formato, espera=0.3)
    p.clicar_em(a["create"], "Create", espera=0.5)


def _na_select_project(p: _Piloto, projeto: str, formato: str) -> bool:
    """Uma volta na Select Project. Devolve True se CRIOU (clicou Create), False se mandou abrir.

    ⭐ Uma pergunta por tela (autor, 2026-11-01: "as outras ações podem ter uns 3 a 5 s"): a mesma
    foto diz em que aba se está, onde está o projeto, o Open e a aba New Project."""
    regiao = _regiao_select_project()
    a = p.achar_varios({
        "lista": "o nome de um projeto qualquer na coluna Name da LISTA de projetos (o primeiro visível)",
        "open": "o botão Open no rodapé da janela (ao lado de Quit)",
        "aba_novo": "a aba New Project no alto (ao lado da aba Projects)",
        "nome": "o campo de texto Project name (só existe com a aba New Project à mostra)",
    }, regiao)
    if isinstance(a["nome"], localizador.Achado):          # a aba New Project já está à mostra
        if (pasta_de_projetos() / projeto).is_dir():
            # ⛔ O projeto já existe: criar de novo dá o aviso de nome repetido, em laço.
            aba = p.achar_varios({"aba": "a aba Projects no alto da janela (ao lado da aba New Project)"}, _regiao_select_project())
            p.clicar_em(aba["aba"], "aba Projects", espera=0.5)
            return False
        if not formato:
            raise McNaoAbre("a aba New Project está aberta e falta o formato do projeto")
        _novo_projeto(p, projeto, formato)
        return True
    # ⭐⭐ QUEM DIZ SE O PROJETO EXISTE É A PASTA DELE, e quem o SELECIONA é a digitação na lista
    #    (a busca do Qt: clicar uma linha, digitar o nome — a lista rola e seleciona). MEDIDO
    #    (2026-11-01): procurar o nome pela FOTO falhava duas vezes — a lista em ordem decrescente
    #    escondia o projeto abaixo da área visível, e a coluna Name corta "CICLO TESTE …" (dois
    #    iguais), sem como conferir. A prova de que abriu o CERTO é o título da janela (`_abrir`).
    if (pasta_de_projetos() / projeto).is_dir():
        p.clicar_em(a["lista"], "uma linha da lista", espera=0.2)
        maos.digitar(_frente_do_mc(), projeto)
        p.passos.append(f"'{projeto}' digitado na lista")
        time.sleep(0.4)
        p.clicar_em(a["open"], "Open", espera=0.5)
        return False
    if not formato:
        raise McNaoAbre(f"o projeto '{projeto}' não está na lista do Media Composer, e para CRIÁ-LO "
                        "falta o formato (ex.: 1080p/25 — o da mídia que vai entrar)")
    p.clicar_em(a["aba_novo"], "aba New Project", espera=0.5)
    _novo_projeto(p, projeto, formato)
    return True


def _abrir_pelo_teclado(p: _Piloto, projeto: str) -> bool:
    """Seleciona e abre o projeto SEM foto, sem coordenada e sem modelo. True = as teclas foram enviadas.

    ⭐⭐ MEDIDO (2026-11-09, MC 2024.6): com a Select Project focada, o foco já está na LISTA. Digitar o nome move a seleção, e Enter abre (0,3 s até a janela sumir).
    ⛔ O aviso de teclado nasce com o 1º foco, e um espaço do nome o responderia: por isso a pausa antes de digitar, e a frente conferida a cada letra.
    ⭐ Quem prova que abriu o CERTO continua sendo o título da janela (`_abrir`). Não andou, o caminho pela foto assume.
    """
    h = _janela_com_titulo(SELECT_PROJECT)
    if not h or not _janela.habilitada(h) or not _janela.focar(h):
        return False
    time.sleep(1.5)
    if _aviso_na_tela():
        return False
    try:
        maos.digitar(h, projeto)
        time.sleep(0.5)
        maos.tecla(h, maos.VK_RETURN)
    except maos.ForaDeFoco:
        return False
    p.passos += [f"'{projeto}' digitado na lista", "Enter"]
    return True


def _forma_de_barra(r: tuple[int, int, int, int]) -> bool:
    """⭐ MEDIDO (2026-11-09, MC 2024.6): aviso de teclado 518×190 (2,7:1), barra de carregar 402×125 (3,2:1). A proporção não muda com a escala do monitor."""
    return (r[2] - r[0]) / max(r[3] - r[1], 1) >= 3.0


def _aviso_pelo_teclado(p: _Piloto, h: int) -> bool:
    """⭐ MEDIDO (2026-11-09): o foco nasce no OK, e um Tab o leva ao "Don't warn me again". Não sumiu, a foto assume."""
    if p.aviso_sem_teclado:
        return False
    try:
        _frente_do_mc()
        time.sleep(0.3)
        maos.tecla(h, maos.VK_TAB)
        time.sleep(0.2)
        maos.tecla(h, maos.VK_SPACE)
    except maos.ForaDeFoco:
        return False
    limite = time.monotonic() + 2.0
    while time.monotonic() < limite:
        if not any(a == h for a, _r in _avisos()):
            p.passos.append("Don't warn me again")
            return True
        time.sleep(0.1)
    p.aviso_sem_teclado = True
    return False


def _aviso_resolvido(p: _Piloto) -> bool:
    """Há uma janela "AvidMediaComposer": é o aviso de teclado (Don't warn me again) ou a barra de progresso (o mesmo título)? A forma separa os dois, de graça; a foto fica para o que o teclado não resolver."""
    avisos = _avisos()
    if not avisos:
        return False
    h, regiao = avisos[0]
    if _forma_de_barra(regiao):
        return False
    if _aviso_na_tela() == h and _aviso_pelo_teclado(p, h):
        return True
    a = p.achar_varios({"nao_avisar": "o botão \"Don't warn me again\" de um aviso sobre o teclado"},
                       regiao)
    if isinstance(a["nao_avisar"], localizador.Achado):
        p.clicar_em(a["nao_avisar"], "Don't warn me again", espera=0.5)
        return True
    return False


def abrir(projeto: str, formato: str = "", relatar: Relatar | None = None,
          prazo: float = PRAZO_DE_ABRIR_S) -> dict[str, Any]:
    """Abre o MC e o projeto (ver `_abrir`) — com a janela do app FORA da frente (`piloto/espaco`)."""
    with espaco.tela_livre():
        return _socorro.com_agente(f"abrir o projeto '{projeto}' no Media Composer", lambda: _abrir(projeto, formato, relatar, prazo), McNaoAbre, relatar)


def fechar(relatar: Relatar | None = None, prazo: float = PRAZO_DE_SAIR_S) -> dict[str, Any]:
    """Fecha o MC (ver `_fechar`) — com a janela do app FORA da frente (`piloto/espaco`)."""
    with espaco.tela_livre():
        return _socorro.com_agente("fechar o Media Composer (File, Exit, Leave)", lambda: _fechar(relatar, prazo), McNaoAbre, relatar)


def _projeto_pela_api() -> str:
    """O NOME do projeto aberto, pela ponte gRPC; "" sem MC ou sem projeto."""
    from .mcapi import MediaComposer, McApiErro  # noqa: PLC0415  (gRPC só quando precisa)
    try:
        with MediaComposer() as m:
            return Path(str(m.projeto().get("caminho") or "").rstrip("/\\")).name
    except (McApiErro, OSError):
        return ""


def _abrir(projeto: str, formato: str = "", relatar: Relatar | None = None,
           prazo: float = PRAZO_DE_ABRIR_S) -> dict[str, Any]:
    """Abre o MC (se fechado) e o projeto `projeto`; sem ele na lista, CRIA com `formato`.

    Projeto diferente aberto: **File → Close Project** (banco: o DoCommand de fechar projeto não
    fecha no 2024.6), e a Select Project volta. Devolve `como` (ja_aberto · aberto · criado),
    `segundos`, `custo_usd` e os `passos`."""
    relatar = relatar or _sem_relato
    if sys.platform != "win32":
        # ⭐ macOS: o piloto da Select Project ainda é só do Windows, mas o projeto JÁ aberto se confere pela API
        #   (medido 2026-11-05, MC 25.12): é o caso do fluxo que o editor começa com o MC no projeto certo.
        if _projeto_pela_api() == projeto:
            return {"como": "ja_aberto", "segundos": 0.0, "custo_usd": 0.0, "passos": []}
        raise McNaoAbre("abrir o Media Composer pelo Ciclo Assist ainda não existe fora do Windows — "
                        f"abra o projeto {projeto!r} no Media Composer e peça de novo")
    if formato:
        grupo_do_formato(formato)        # recusa o formato desconhecido ANTES de mexer em nada
    comeco = time.monotonic()
    atual = projeto_aberto()
    if atual == projeto:
        return {"como": "ja_aberto", "segundos": 0.0, "custo_usd": 0.0, "passos": []}
    p = _Piloto(relatar)
    if atual:
        relatar(f"fechando o projeto '{atual}' no Media Composer", None, "")
        try:
            p.no_menu("File", "Close Project")
        except localizador.NaoAchei as e:
            raise McNaoAbre(f"não consegui fechar o projeto '{atual}': {e}") from e
    if not aberto():
        relatar("abrindo o Media Composer", None, "")
        _lancar()
    criou = False
    agiu_na_select = tentativas_de_teclado = 0
    enviou_teclado = False
    ultimo_aviso = aviso_desde = quieto_desde = outro_desde = 0.0
    estranho_desde = 0.0
    avisos_sem_botao = 0
    fim = comeco + prazo
    # ⭐⭐ O ESTADO SAI DOS TÍTULOS DAS JANELAS, de graça, a cada meio segundo (autor, 2026-11-01:
    #    "não sei se é possível saber quando a tela de carregamento termina"). É: o fim do
    #    carregamento é a janela "Select Project" aparecer; o projeto aberto é o título da
    #    principal. O modelo só é chamado para AGIR — e para separar o aviso de teclado da barra de
    #    progresso, que têm o mesmo título.
    while time.monotonic() < fim:
        maos.freio()
        try:
            janelas = _janela.janelas(EXE)
            aviso = any(t == AVISO and _janela.aviso(r) and not _janela.e_popup(h) for h, t, r in janelas)
            select = any(t.strip() == SELECT_PROJECT for _h, t, _r in janelas)
            if aviso and _barra_presa(janelas):
                aviso = False
            # ⛔ MEDIDO (2026-11-01): a barra de carregar aparece, some e VOLTA — pronto num vão
            #   entre duas barras devolveu o MC ainda carregando. Pronto = o título E nenhuma
            #   janela "AvidMediaComposer" por 1,5 s seguidos.
            if aviso or projeto_aberto() != projeto:
                quieto_desde = 0.0
            elif not quieto_desde:
                quieto_desde = time.monotonic()
            if quieto_desde and time.monotonic() - quieto_desde >= 1.5:
                return {"como": "criado" if criou else "aberto",
                        "segundos": round(time.monotonic() - comeco, 1),
                        "custo_usd": round(p.custo, 4), "passos": p.passos,
                        "fechou_antes": atual or ""}
            outro = projeto_aberto()
            if outro and outro != projeto and (agiu_na_select or enviou_teclado):
                # ⛔ A digitação na lista selecionou OUTRO projeto, e ele abriu: dizer, não esperar.
                #   ⚠️ Por 5 s seguidos: logo depois do Open o título ainda pode ser o VELHO.
                outro_desde = outro_desde or time.monotonic()
                if time.monotonic() - outro_desde > 5.0:
                    raise McNaoAbre(f"o Media Composer abriu o projeto '{outro}', não '{projeto}'")
            else:
                outro_desde = 0.0
            # ⛔ MEDIDO (2026-11-19): o modal "This volume has not yet been mounted" ("Avid Media Composer", com
            #   espaços — não é o título do aviso de teclado) travou a entrada no projeto e o laço só esperava o prazo de
            #   300 s. Modal desconhecido parado 3 s = a tela não está como o script espera: é a vez do agente do piloto.
            if _socorro.inesperada():
                estranho_desde = estranho_desde or time.monotonic()
                if time.monotonic() - estranho_desde >= 3.0:
                    raise McPreso("há uma janela do Media Composer esperando resposta")
            else:
                estranho_desde = 0.0
            if not janelas:
                relatar("esperando a janela do Media Composer", None, f"{int(time.monotonic() - comeco)} s")
                time.sleep(0.5)
                continue
            # ⚠️ Aviso de teclado OU barra de progresso ("Initializing Format pane", medido — o MESMO
            #   título): uma pergunta no recorte dela, no máximo a cada 4 s. Com o título já no
            #   projeto pedido é quase sempre a barra do carregamento (40–50 s medidos): só pergunta
            #   se ela passar de 20 s, senão seriam dez perguntas para ver uma barra andar.
            if aviso and not aviso_desde:
                aviso_desde = time.monotonic()
                log.info("janela %s: %s", AVISO, [r for _h, t, r in janelas if t == AVISO and _janela.aviso(r)])
            if not aviso:
                aviso_desde = 0.0
            ja_no_projeto = projeto_aberto() == projeto
            if (aviso and time.monotonic() - ultimo_aviso > 4.0
                    and (not ja_no_projeto or time.monotonic() - aviso_desde > 20.0)):
                ultimo_aviso = time.monotonic()
                try:
                    if _aviso_resolvido(p):
                        avisos_sem_botao = 0
                        continue
                    # ⛔ MEDIDO (2026-11-02): o aviso NA TELA e o botão "não achado" 45 vezes em
                    #   304 s. A barra de carregar também cai aqui (o mesmo título, também pequena,
                    #   ~20 s no arranque): três seguidas E a janela há mais de 60 s na tela.
                    avisos_sem_botao += 1
                    if (avisos_sem_botao >= 3 and not ja_no_projeto
                            and time.monotonic() - aviso_desde > 60.0):
                        raise McPreso("há um aviso do Media Composer na tela e não consegui achar o botão "
                                        "\"Don't warn me again\" — responda a ele e tente de novo")
                except McNaoAbre as e:
                    if "aviso do Media Composer" in str(e):
                        raise
                    # sem foco ainda (o splash some antes): espera — mas DITO no log: calado,
                    # isto escondeu por 5 min o foco recusado na principal (2026-11-02)
                    log.info("aviso na tela, ainda sem agir: %s", e)
            if select and not aviso:
                if not enviou_teclado and tentativas_de_teclado < 3 and (pasta_de_projetos() / projeto).is_dir():
                    tentativas_de_teclado += 1
                    enviou_teclado = _abrir_pelo_teclado(p, projeto)
                    limite = time.monotonic() + (3.0 if enviou_teclado else 0.0)
                    while time.monotonic() < limite and _janela_com_titulo(SELECT_PROJECT):
                        time.sleep(0.2)
                    continue
                if agiu_na_select >= 4:
                    raise McPreso("a Select Project continua na tela depois de 4 tentativas "
                                    f"(passos: {', '.join(p.passos)})")
                try:
                    criou = _na_select_project(p, projeto, formato) or criou
                except McNaoAbre as e:
                    if "não deixou" in str(e) or "tomou a frente" in str(e):
                        time.sleep(0.5)  # o foco ainda está mudando: outra volta
                        continue
                    raise
                agiu_na_select += 1
                # Depois de Open/Create a Select Project some; se não sumir em 3 s, outra volta.
                limite = time.monotonic() + 3.0
                while time.monotonic() < limite and _janela_com_titulo(SELECT_PROJECT):
                    time.sleep(0.3)
                continue
            relatar("o Media Composer está carregando", None, f"{int(time.monotonic() - comeco)} s")
            time.sleep(0.5)
        except localizador.NaoAchei as e:
            # ⭐ MEDIDO (2026-11-09, 3 de 3 arranques): o aviso de teclado nasce com o foco, por cima da lista, e o ponto da lista reprova. O script sabe resolver esse aviso: uma volta, sem gastar o agente.
            if _aviso_na_tela() and not avisos_sem_botao:
                time.sleep(0.3)
                continue
            raise McNaoAbre(f"{e} (passos até aqui: {', '.join(p.passos) or 'nenhum'})") from e
        except (maos.ForaDeFoco, maos.Parado, tela.SemTela) as e:
            raise McNaoAbre(str(e)) from e
    raise McPreso(f"o projeto '{projeto}' não abriu em {int(time.monotonic() - comeco)} s "
                    f"(passos: {', '.join(p.passos) or 'nenhum'})")


# ── fechar ───────────────────────────────────────────────────────────────────

def _fechar(relatar: Relatar | None = None, prazo: float = PRAZO_DE_SAIR_S) -> dict[str, Any]:
    """File → Exit → Leave, e espera o PROCESSO sumir. As bins o MC salva ao sair."""
    relatar = relatar or _sem_relato
    if not aberto():
        return {"ja_estava_fechado": True, "segundos": 0.0, "projeto": "", "custo_usd": 0.0}
    if sys.platform != "win32":
        raise McNaoAbre("fechar o Media Composer pelo Ciclo Assist ainda não existe fora do Windows")
    comeco = time.monotonic()
    projeto = projeto_aberto()
    principal = _janela.janela_principal(EXE, "Avid Media Composer") or 0
    if principal and _janela.travada(principal):
        # ⭐ Já está saindo (um fechar anterior deu o Leave) ou travado: o menu não responde. Esperar.
        return _esperar_sair(relatar, comeco, projeto, 0.0, [], "o Media Composer já está saindo")
    p = _Piloto(relatar)
    try:
        if _janela.existe_aviso(AVISO):
            _aviso_resolvido(p)
        relatar("fechando o Media Composer", None, projeto)
        antes = {h for h, _t, _r in _janela.janelas(EXE)}
        if _janela_com_titulo(SELECT_PROJECT):
            # ⛔ MEDIDO (2026-11-09): sem projeto aberto a principal fica desabilitada, e o menu File não abre. Daqui se sai pelo Quit, que faz a mesma pergunta do Exit.
            a = p.achar_varios({"quit": "o botão Quit no rodapé da janela Select Project"}, _regiao_select_project())
            p.clicar_em(a["quit"], "Quit", espera=0.3)
        else:
            p.no_menu("File", "Exit")
        fim = comeco + prazo
        perguntou = False
        while time.monotonic() < fim:
            if not _processo_vivo():
                return {"ja_estava_fechado": False, "segundos": round(time.monotonic() - comeco, 1),
                        "projeto": projeto, "custo_usd": round(p.custo, 4), "passos": p.passos}
            # ⭐ A pergunta "Leave the application?" é uma janela NOVA do MC: esperar por ela pelos
            #   títulos (de graça) em vez de perguntar ao modelo antes de ela existir.
            nova = [r for h, _t, r in _janela.janelas(EXE) if h not in antes]
            if not perguntou and (nova or time.monotonic() - comeco > 8.0):
                try:
                    a = p.achar_varios({"leave": "o botão Leave da pergunta 'Leave the application?'"},
                                       nova[0] if len(nova) == 1 else None)
                    p.clicar_em(a["leave"], "Leave", espera=0.5)
                    perguntou = True
                    return _esperar_sair(relatar, comeco, projeto, p.custo, p.passos,
                                         "o Media Composer está salvando e saindo")
                except localizador.NaoAchei:
                    pass            # ainda desenhando, ou já saiu
            relatar("fechando o Media Composer", None, f"{int(time.monotonic() - comeco)} s")
            time.sleep(0.5)
    except localizador.NaoAchei as e:
        raise McNaoAbre(f"{e} (passos: {', '.join(p.passos) or 'nenhum'})") from e
    except (maos.ForaDeFoco, maos.Parado, tela.SemTela) as e:
        raise McNaoAbre(str(e)) from e
    raise McPreso(f"o Media Composer não fechou em {int(prazo)} s (passos: {', '.join(p.passos)})")


def _esperar_sair(relatar: Relatar, comeco: float, projeto: str, custo: float, passos: list,
                  frase: str, prazo: float = PRAZO_DEPOIS_DO_LEAVE_S) -> dict[str, Any]:
    """A saída está em curso: espera o PROCESSO sumir, contando o tempo a cada meio segundo (nunca às
    cegas: o processo é conferido a cada volta). ⚠️ Não mata o MC: ele está gravando o projeto."""
    desde = time.monotonic()
    while time.monotonic() - desde < prazo:
        if not _processo_vivo():
            log.info("MC saiu em %.0f s (%.0f s depois do Leave)", time.monotonic() - comeco, time.monotonic() - desde)
            return {"ja_estava_fechado": False, "segundos": round(time.monotonic() - comeco, 1),
                    "projeto": projeto, "custo_usd": round(custo, 4), "passos": passos}
        relatar(frase, None, f"{int(time.monotonic() - comeco)} s")
        time.sleep(2.0)             # o tasklist custa ~0,1 s; a saída leva minutos
    raise McNaoAbre(f"o Media Composer recebeu o Leave e não saiu em {int(prazo)} s — o processo continua vivo; "
                    "veja se há um diálogo na tela dele (não force: ele pode estar gravando o projeto)")
