"""A operação 8 do ensaio: SALVAR TUDO no Media Composer — foco num vazio da timeline + Ctrl+S.

Para que existe: bin ou PASTA escrita POR FORA do MC (Sincronizar, De Lá Pra Cá, pyavb) só aparece
no painel de bins depois de um save (banco, `transversal/operacoes.md`). Não há RPC para isso
no 2024.6 (sem `DoCommand`), então é o gesto, pelo piloto (`cicloassist/piloto`).

MEDIDO no MC 2024.6 (2026-11-01, projeto `CICLO ENSAIO M06`):
- ⛔⛔ **Só salva o que está MODIFICADO.** Sem nada sujo, "Save All Bins Ctrl+S" fica CINZA no
  menu File e o gesto não grava nada. Com uma bin suja (a do pyavb aberta pela API já vem com
  `*`), o gesto gravou o `.avp` e a pasta nova `OP8 PASTA FORA` apareceu.
- ⇒ **A prova é a data do `.avp`**, nunca a foto: o painel igual antes e depois não distingue
  "não salvou" de "salvou e não havia o que mostrar".
- ⛔ O foco vai num vazio da TIMELINE, não na bin: com a bin em foco o Ctrl+S salvaria só ela
  (banco). O ponto vem do localizador (a foto), conferido; e fica guardado enquanto a janela
  do MC não mudar de lugar nem de tamanho — reaproveitado, ele só é CONFERIDO (1 pergunta).
- ⛔ Clicar no VÃO entre dois clipes de uma trilha move a agulha: o alvo é a faixa cinza entre a
  régua de cima e a trilha mais alta (o spike achou o vão quando "refinou" — ver o localizador).

⛔⛔ **"Nada a salvar" é SUCESSO, não falha** (prova da F1, 2026-11-01): depois de um sync por
cena o Sincronizar já salvou tudo; o Ctrl+S direto não regravou nada (nada sujo), o recurso do clique
foi tentado e a conferência do ponto RECUSOU a timeline vazia (o recorte de 480×270 só mostra
cinza liso) — e o passo do fluxo FALHOU por um save que não tinha o que fazer. Agora:
- o clique só é o recurso quando há SINAL de que o foco estava numa bin: alguma `.avb` do projeto
  regravada pelo Ctrl+S direto sem o `.avp` mudar (com a bin em foco o MC salva só ela);
- sem esse sinal, ainda se tenta o clique (bin limpa em foco com outra suja é possível), mas o
  ponto não confirmado vira `salvou: false` com "nada a salvar", nunca erro.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Callable

from .. import janela
from ..piloto import auxilio as _auxilio
from ..piloto import espaco, localizador, maos, tela
from . import socorro as _socorro

log = logging.getLogger("cicloassist.avid.salvar")

EXE = "AvidMediaComposer.exe"
AVISO = "AvidMediaComposer"     # o título do aviso de teclado (e do progresso de abrir projeto)
#: ⛔⛔ A 1ª versão exigia "a faixa entre a régua e a trilha mais alta" — e com a timeline VAZIA
#:   (nenhuma sequência carregada: o caso do teste do autor, 2026-11-01) essa faixa não existe e o
#:   save falhou. Autor: *"o salvar não precisa de timeline, basta o MC estar em foco; qualquer
#:   Ctrl+S funciona contanto que o foco não esteja numa bin"*. O clique só existe para tirar o
#:   foco de uma bin, e só quando o Ctrl+S direto não gravou.
ALVO = ("um ponto liso e VAZIO do painel da TIMELINE do Media Composer (a área grande de baixo): sem "
        "clipe, sem régua, sem botão, sem cabeçalho de trilha. Com a timeline vazia, qualquer ponto da "
        "área cinza dela. NUNCA o vão entre dois clipes de uma trilha")
#: Quanto o Ctrl+S direto tem para regravar o `.avp` antes de tentar com o clique.
PRAZO_DO_SAVE_DIRETO_S = 3.0
PRAZO_DO_SAVE_S = 8.0

_guardado: dict[tuple, tuple[int, int]] = {}   # (hwnd, retângulo da janela) → ponto de tela


class SalvarFalhou(RuntimeError):
    pass


class AvisoNaTela(SalvarFalhou, _auxilio.TelaInesperada):
    """Um aviso do MC no caminho do save: é aqui que o agente do piloto entra."""


def _retangulo(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def arquivo_do_projeto(caminho: str | Path) -> Path:
    """O `.avp` da pasta do projeto — é ele que o "Save All" regrava."""
    # ⛔ Sem os `._*` do exFAT: `._X.avp` vem antes de `X.avp` na ordem, e a prova do save olharia a sombra.
    avps = sorted(p for p in Path(caminho).glob("*.avp") if not p.name.startswith("._"))
    if not avps:
        raise SalvarFalhou(f"não achei o .avp do projeto em {caminho}")
    return avps[0]


def _datas_das_bins(caminho: str | Path) -> dict[Path, float]:
    """`mtime` de cada `.avb` do projeto (subpastas incluídas; os `._*` do exFAT fora)."""
    datas: dict[Path, float] = {}
    for b in Path(caminho).rglob("*.avb"):
        if b.name.startswith("._"):
            continue
        try:
            datas[b] = b.stat().st_mtime
        except OSError:
            pass
    return datas


def _bins_regravadas(antes: dict[Path, float], caminho: str | Path) -> list[str]:
    depois = _datas_das_bins(caminho)
    return sorted(b.stem for b, t in depois.items() if t > antes.get(b, 0.0))


def esperar_mudar(arquivo: Path, antes: float, prazo_s: float = PRAZO_DO_SAVE_S) -> bool:
    fim = time.monotonic() + prazo_s
    while time.monotonic() < fim:
        try:
            if arquivo.stat().st_mtime > antes:
                return True
        except OSError:
            pass
        time.sleep(0.25)
    return False


def sujar(m, bin_absoluta: str | Path) -> None:
    """Deixa uma bin MODIFICADA aos olhos do MC, para o "Save All" ter o que gravar.

    MEDIDO (MC 2024.6, 2026-11-01): quem escreve por fora e já salva pela API (o Sincronizar faz
    isso com cada bin) deixa o projeto LIMPO — o Ctrl+S não grava, e a pasta nova não aparece.
    Uma bin sem `attributes` (larguras de coluna, fonte, barra de status…) abre com `*`: o MC os
    preenche ao abrir. Regravada só com isso e reaberta, ela fica suja; o save devolve tudo
    (o tamanho voltou a 114K). ⚠️ Só para bin que NASCEU nesta operação: o que se perde são as
    larguras de coluna, que numa bin de segundos atrás são as de fábrica.

    `CloseBin` → pyavb ao lado, `uid` preservado → `os.replace` → `OpenBin` (banco,
    `protocolos/avb/escrita.md`). ⛔ Recusada a reabertura, a original volta byte a byte.
    """
    import avb  # noqa: PLC0415  (pyavb, com o avb_fiel aplicado por `cicloassist.avid`)

    p = Path(bin_absoluta)
    rel = m.caminho_relativo_da_bin(str(p))
    # ⛔ quem escreveu (o Sincronizar) acabou de carregar a sequência num monitor, e carregar →
    #    consultar → fechar colados derruba o MC (banco); a nossa ponte só segura os NOSSOS.
    time.sleep(3.0)
    try:
        m._chamar("CloseBin", _timeout=60, bin_path=rel)
    except Exception:  # noqa: BLE001  — bin já fechada: segue (como no montar_corte)
        pass
    original = p.read_bytes()
    novo = p.with_name(p.name + ".novo")      # extensão que o MC não enxerga
    try:
        with avb.open(str(p)) as f:
            f.content.attributes.clear()
            f.write(str(novo))
        os.replace(novo, p)
        m._chamar("OpenBin", _timeout=60, bin_path=rel)
    except Exception:
        novo.unlink(missing_ok=True)
        p.write_bytes(original)
        try:
            m._chamar("OpenBin", _timeout=60, bin_path=rel)
        except Exception:  # noqa: BLE001
            pass
        raise


def _janelas_de_trabalho(principal: int) -> list[int]:
    """As janelas do MC onde a timeline pode estar: a do painel "Timeline" SOLTO primeiro
    (layout livre: a janela tem o nome do painel), depois as GRANDES que não são a principal, a
    principal por último.

    ⛔⛔ MEDIDO (2026-11-02, MC 2024.6): no layout PADRÃO de dois monitores a Timeline (e o
    Composer) vão para uma 2ª janela de topo no outro monitor ("AvidMediaComposer"); a principal
    fica só com as bins — procurar a timeline nela dava "não achei". Num monitor só, a principal
    é a única, e a ordem não custa nada."""
    painel = janela.do_painel(EXE, "Timeline")       # solta: a janela dela, de qualquer tamanho
    outras = [h for h, t, r in janela.janelas(EXE)
              if h not in (principal, painel) and t.strip() != "Select Project" and not janela.pequena(r)]
    return [*([painel] if painel else []), *outras, principal]


def _ponto_da_timeline(principal: int, relatar) -> tuple[int, int, int, float]:
    """(janela, x, y, custo em US$): o ponto vazio da timeline, em coordenada de tela, e em que
    janela do MC ele está."""
    foto = tela.fotografar()
    candidatas = _janelas_de_trabalho(principal)
    custo = 0.0
    for h in candidatas:
        chave = (h, _retangulo(h))
        if chave in _guardado:
            x, y = _guardado[chave]
            ok, _r, _s, c = localizador.conferir(foto, x, y, ALVO, recorte=localizador.RECORTE_AMPLO)
            custo += c
            if ok:
                return h, x, y, custo
            _guardado.pop(chave, None)
    relatar("procurando um vazio na timeline", None, "")
    erro: localizador.NaoAchei | None = None
    cortada: localizador.JanelaCortada | None = None
    for h in candidatas:
        ret = _retangulo(h)
        try:
            a = localizador.localizar(foto, ALVO, regiao=ret, recorte=localizador.RECORTE_AMPLO)
        except localizador.JanelaCortada as e:
            cortada = cortada or e          # ⭐ dita no fim: "não achei" seria a frase errada
            continue
        except localizador.NaoAchei as e:
            erro = e
            continue
        _guardado.clear()
        _guardado[(h, ret)] = (a.x, a.y)
        return h, a.x, a.y, custo + a.custo_usd
    raise cortada or erro or localizador.NaoAchei("nenhuma janela do Media Composer para procurar a timeline")


def salvar_tudo(caminho_do_projeto: str | Path,
                relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """Foco num vazio da timeline + Ctrl+S — com a janela do app FORA da frente (`piloto/espaco`).
    macOS: File → Save All Bins pelo NOME (acessibilidade), sem foco nem tecla (`_salvar_pelo_menu`)."""
    if sys.platform == "darwin":
        return _salvar_pelo_menu(caminho_do_projeto, relatar)
    with espaco.tela_livre():
        return _socorro.com_agente("salvar o projeto no Media Composer (Ctrl+S)", lambda: _salvar_tudo(caminho_do_projeto, relatar), SalvarFalhou, relatar)


#: O item do menu do MC no Mac (25.12, menu em inglês) e o processo dono da barra de menus.
_MENU_SALVAR = 'menu item "Save All Bins" of menu 1 of menu bar item "File" of menu bar 1'
_PROCESSO_MAC = "AvidMediaComposer"


def _no_menu(acao: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", f'tell application "System Events" to tell process '
                                              f'"{_PROCESSO_MAC}" to {acao} {_MENU_SALVAR}'],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30)


def _salvar_pelo_menu(caminho_do_projeto: str | Path,
                      relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """macOS: File → Save All Bins por AXPress — MEDIDO (2026-11-05, MC 25.12): regravou o `.avp` e a bin suja
    em 1,4 s com o Terminal na frente (nenhum foco roubado, nenhuma tecla). O item fica CINZA sem nada
    modificado (como o Ctrl+S do Windows): aí não há o que salvar, e isso é dito."""
    relatar = relatar or (lambda *_: None)
    r = _no_menu("get enabled of")
    if r.returncode != 0:
        raise SalvarFalhou("não achei o menu File → Save All Bins do Media Composer "
                           f"({(r.stderr or '').strip() or 'ele está aberto?'})")
    avp = arquivo_do_projeto(caminho_do_projeto)
    comeco = time.monotonic()
    base = {"projeto": str(avp), "ponto": [None, None], "custo_usd": 0.0}
    if r.stdout.strip() != "true":
        return {**base, "salvou": False, "segundos": 0.0,
                "nota": "o Save All Bins está cinza — o projeto não tinha nada modificado"}
    antes = avp.stat().st_mtime
    relatar("salvando (File → Save All Bins)", None, "")
    c = _no_menu("click")
    if c.returncode != 0:
        raise SalvarFalhou(f"o Media Composer recusou o Save All Bins ({(c.stderr or '').strip()})")
    salvou = esperar_mudar(avp, antes, PRAZO_DO_SAVE_S)
    return {**base, "salvou": salvou, "segundos": round(time.monotonic() - comeco, 1)}


def _salvar_tudo(caminho_do_projeto: str | Path,
                 relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """Foco num vazio da timeline + Ctrl+S. Devolve se o `.avp` foi regravado."""
    relatar = relatar or (lambda *_: None)
    if sys.platform != "win32":
        raise SalvarFalhou("salvar pelo gesto ainda não existe fora do Windows")
    hwnd = janela.janela_principal(EXE, "Avid Media Composer")
    if not hwnd:
        raise SalvarFalhou("o Media Composer não está aberto")
    if janela.existe_aviso(AVISO) or _socorro.inesperada():
        raise AvisoNaTela("há um aviso do Media Composer na tela — responda a ele antes")
    avp = arquivo_do_projeto(caminho_do_projeto)
    antes = avp.stat().st_mtime
    bins_antes = _datas_das_bins(caminho_do_projeto)
    anterior = maos.da_frente()
    comeco = time.monotonic()
    custo = 0.0
    nota = ""
    try:
        if not janela.focar(hwnd):
            raise SalvarFalhou("o Windows não deixou pôr o Media Composer na frente")
        time.sleep(0.5)
        # ⛔ o aviso de teclado NASCE com o foco (banco): olhar de novo depois de focar
        if janela.existe_aviso(AVISO):
            raise AvisoNaTela("apareceu um aviso do Media Composer ao trazê-lo para a frente — responda a ele antes")
        # ⭐ 1º: o MC em foco e Ctrl+S, sem pergunta nenhuma ao modelo (autor, 2026-11-01).
        relatar("salvando (Ctrl+S)", None, "")
        maos.tecla(hwnd, ord("S"), maos.VK_CONTROL)
        salvou = esperar_mudar(avp, antes, PRAZO_DO_SAVE_DIRETO_S)
        x = y = None
        if not salvou:
            # 2º: o foco pode estar numa bin (só ela é salva): um clique na Timeline e de novo.
            #   Com uma bin regravada sem o `.avp`, isso é CERTO, e não achar o ponto é falha;
            #   sem sinal nenhum, o mais provável é não haver nada sujo (ver o docstring).
            so_a_bin = _bins_regravadas(bins_antes, caminho_do_projeto)
            try:
                onde, x, y, custo = _ponto_da_timeline(hwnd, relatar)
            except localizador.NaoAchei as e:
                if so_a_bin:
                    raise SalvarFalhou(f"o Ctrl+S salvou só a bin {so_a_bin[0]} (o foco estava nela) e não "
                                       f"achei um vazio da timeline para salvar o resto: {e}") from e
                log.info("salvar: nada regravado e o ponto da timeline não confirmado (%s)", e)
                nota = "o Ctrl+S não regravou nada — o projeto não tinha nada modificado"
            else:
                relatar("salvando (Ctrl+S, com o foco na timeline)", None, "")
                # a timeline pode estar noutra janela do MC (dois monitores): o clique e a tecla
                # vão a ELA — `maos` confere a janela da frente antes de cada gesto
                if onde != hwnd and not janela.focar(onde):
                    raise SalvarFalhou("o Windows não deixou pôr a janela da timeline na frente")
                maos.clicar(onde, x, y)
                time.sleep(0.3)
                maos.tecla(onde, ord("S"), maos.VK_CONTROL)
                # ⭐ Sem sinal de bin suja, o mais provável é "nada a salvar": a espera curta.
                #   MEDIDO (2026-11-02): com o ponto achado e nada sujo, a espera cheia custou 26 s.
                salvou = esperar_mudar(avp, antes, PRAZO_DO_SAVE_S if so_a_bin else PRAZO_DO_SAVE_DIRETO_S)
                if not salvou and not so_a_bin:
                    nota = "o Ctrl+S não regravou nada — o projeto não tinha nada modificado"
    except (localizador.NaoAchei, tela.SemTela, maos.ForaDeFoco, maos.Parado) as e:
        raise SalvarFalhou(str(e)) from e
    finally:
        if anterior and anterior != hwnd:
            janela.focar(anterior)
    r = {"salvou": salvou, "projeto": str(avp), "ponto": [x, y],
         "segundos": round(time.monotonic() - comeco, 1), "custo_usd": round(custo, 4)}
    if nota:
        r["nota"] = nota
    return r
