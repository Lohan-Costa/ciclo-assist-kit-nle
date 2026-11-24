"""`gerar_midia_de_teste`: a operação 1 do ensaio — a mídia sintética do laboratório.

Plano: `docs/plano/2026-10-31-operacoes-do-ensaio.md`. O motor é `cicloassist/laboratorio.py`;
aqui ficam a conferência antes do cartão e o que volta ao modelo.

⭐ **Escreve** (passa pelo portão): gera arquivos em disco e pode levar minutos de CPU na
máquina de quem trabalha. Reaproveitar o que já está pronto é instantâneo, e a resposta diz
qual dos dois aconteceu.
"""

from __future__ import annotations

from ... import laboratorio as _lab
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta


def _conferir(receita: str = "", **_) -> str:
    if _lab.raiz() is None:
        return ("O laboratório de mídia não está nesta máquina (a pasta 'laboratorio-de-midia' "
                "da família). Diga isso ao editor.")
    todas = _lab.receitas()
    if receita not in todas:
        lista = "; ".join(f"{k} ({v['arquivos']} arquivos: {', '.join(v['fontes'])})" for k, v in todas.items())
        return f"Não há a receita '{receita}'. As receitas são: {lista}."
    return ""


@ferramenta(
    nome="gerar_midia_de_teste",
    descricao=(
        "Gera a mídia SINTÉTICA de um caso do laboratório (câmeras e som direto de uma cena "
        "inventada, com timecode) e o gabarito dela: em que instante da cena cada arquivo começa "
        "— é com ele que o sync e os subclipes são conferidos depois. Receita pelo NOME do caso "
        "(ex.: M06_4TOMADAS, M06_CLAQUETE). Se já estiver gerada, reaproveita na hora; "
        "refazer=true gera numa pasta nova, nunca por cima (a antiga pode estar num projeto). "
        "Devolve a pasta e os arquivos."
    ),
    esquema={
        "type": "object",
        "properties": {
            "receita": {"type": "string", "description": "O nome do caso, sem .json."},
            "refazer": {"type": "boolean", "description": "Gerar de novo mesmo se pronta (pasta nova)."},
        },
        "required": ["receita"],
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def gerar_midia_de_teste(receita: str = "", refazer: bool = False) -> dict[str, object]:
    try:
        r = _lab.gerar(receita, refazer=bool(refazer), relatar=_turno.avisar)
    except _lab.LaboratorioIndisponivel as e:
        return {"erro": str(e)}
    feito = ("já estava gerada — reaproveitei" if r["como"] == "reaproveitado"
             else f"gerada em {r.get('segundos')} s")
    return {**r, "manchete": f"{receita}: {len(r['arquivos'])} arquivos, {feito}, em {r['pasta']}"}
