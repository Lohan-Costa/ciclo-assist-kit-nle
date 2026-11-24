"""`salvar_tudo`: a operação 8 do ensaio — o "Save All" do Media Composer, pelo piloto.

Motor: `cicloassist/avid/salvar.py`. ⛔ Passa pelo portão (`escreve=True`): ela CLICA na tela do
editor e grava o projeto — gesto na máquina dele é coisa que ele aprova.
"""

from __future__ import annotations

from ...avid import salvar as _salvar
from ...avid import socorro as _socorro
from ...avid.mcapi import McApiErro, MediaComposer
from ...servico import turno as _turno
from ..registro import ferramenta


def _projeto() -> str:
    try:
        with MediaComposer() as m:
            if m.info().get("ocupado"):
                raise _salvar.AvisoNaTela("o Media Composer está ocupado — provavelmente há um diálogo na tela dele")
            caminho = m.projeto(recarregar=True).get("caminho")
    except McApiErro as e:
        # ⛔⛔ MEDIDO (2026-11-09, teste pilotado): com um diálogo aberto a API nem responde ("GetAppInfo não respondeu no prazo"), e o fluxo era recusado antes de começar, sem o agente do piloto ver a tela.
        if _socorro.inesperada():
            raise _salvar.AvisoNaTela("há um diálogo do Media Composer na tela, e a API dele não responde enquanto ele estiver aberto") from e
        raise
    if not caminho:
        raise _salvar.SalvarFalhou("o Media Composer não está com um projeto aberto")
    return caminho


def _conferir(**_) -> str:
    try:
        _salvar.arquivo_do_projeto(_projeto())
    except _salvar.AvisoNaTela:
        return ""       # ⭐ Um diálogo na tela é o caso do agente do piloto: quem resolve é a ferramenta, não a recusa antes do cartão.
    except _salvar.SalvarFalhou as e:
        return str(e)
    except McApiErro as e:
        return f"Não consegui falar com o Media Composer: {e}"
    return ""


@ferramenta(
    nome="salvar_tudo",
    descricao=(
        "Salva tudo no Media Composer (Save All Bins) pelo gesto na tela: põe o foco num vazio da timeline e "
        "aperta Ctrl+S. Use depois de escrever bins ou pastas POR FORA do MC (Sincronizar, De Lá Pra Cá) — sem um save "
        "elas não aparecem no painel de bins. Só grava se houver algo modificado: 'salvou: false' quer dizer que "
        "não havia nada a salvar, e aí uma PASTA nova escrita por fora continua invisível até algo mudar."
    ),
    esquema={"type": "object", "properties": {}},
    escreve=True,
    conferir=_conferir,
)
def salvar_tudo() -> dict[str, object]:
    try:
        # ⭐ O `_projeto` também fica dentro: com um diálogo na tela a API responde "ocupado" antes de o save começar.
        r = _socorro.com_agente("salvar o projeto no Media Composer (Ctrl+S)", lambda: _salvar.salvar_tudo(_projeto(), relatar=_turno.avisar), _salvar.SalvarFalhou, _turno.avisar)
    except _salvar.SalvarFalhou as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer recusou: {e}"}
    if r["salvou"]:
        return {**r, "manchete": f"salvo — o projeto foi regravado ({r['segundos']} s)"}
    return {**r, "manchete": "nada a salvar: o Media Composer não tinha nada modificado (o projeto não mudou)"}
