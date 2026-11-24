"""O preview de um padrão contra um conjunto de fichas — e as quatro respostas.

⭐⭐ **Puro como o resto de `nomes/`**: não sabe o que é Avid, take, subclipe ou bin.
Recebe um padrão e uma lista de dicionários; devolve o que cada um vira e se dá para
aplicar. É o que permite a aba Renomear e a aba Subclipes fazerem a MESMA pergunta com
o MESMO código — e o dia em que uma regra mudar, ela muda num lugar.
"""

from __future__ import annotations

from . import template as _template


def prever(padrao: str, fichas) -> dict:
    """O que cada item vai virar, e se dá para aplicar.

    ⭐ **Decisão do autor, 2026-08-28**, revista em 2026-09-17 — só dois casos bloqueiam:

    | situação | resposta |
    |---|---|
    | `%campo` que não existe | 🔴 **bloqueia** |
    | o nome renderizado sai vazio | 🟡 **mantém o nome de agora** (`de_origem`) |
    | … e o item nem nome tem | 🔴 **bloqueia** |
    | campo existe e está vazio neste item | 🟡 marca a linha |
    | dois itens com o mesmo nome | 🟡 marca as duas |

    ⚠️ Os dois amarelos não bloqueiam por motivo de MATERIAL: o Avid aceita nome
    repetido, e no Projeto C não há cena — travar todo padrão com `%cena` tornaria a
    ferramenta inútil justamente no produto que mais precisa dela. **Mas marcar é
    obrigatório:** o editor tem de VER que o nome saiu incompleto antes de aplicar.

    ⚠️⚠️ O que bloqueia, bloqueia o LOTE INTEIRO, e basta um item. Aplicar metade de um
    renomeamento é pior que não aplicar: sobra uma bin em dois estados e nenhum jeito
    de saber onde parou.

    ⭐⭐ **`tokens` viaja junto, e é o que o painel pinta.** O espelho colorido da caixa
    de texto poderia ser calculado no JS — o plano original dizia isso —, mas aí
    existiriam DUAS implementações da mesma gramática, e a que divergisse seria a do
    preview contra a do aplicar. É o pior lugar possível para uma divergência: o editor
    confere na tela uma coisa e o Media Composer recebe outra. Uma implementação só, e
    o custo é um ida-e-volta em loopback por tecla — medido em milissegundos, porque
    aqui não há chamada gRPC nenhuma.

    ⭐ **O nome vazio mantém o nome de agora** (decisão do autor em 2026-09-17, primeiro
    para o Premiere e no mesmo dia para o Avid): *"ter um valor vazio em algum metadado
    não deve bloquear o renomeamento, só não deve ter nada naquele espaço"*. O item cujo
    nome sairia VAZIO fica com o valor de `name` da ficha — `de_origem: True`, amarelo, e
    o aplicar o pula, porque o nome não muda. O bloqueio acima continua valendo para o
    item que nem `name` tem: aí não há o que manter.
    """
    fichas = list(fichas or [])
    catalogo = fichas[0] if fichas else {}
    tokens = [{"bruto": t.bruto, "inicio": t.inicio, "fim": t.fim,
               "campo": t.campo, "cauda": t.cauda}
              for t in _template.analisar(padrao, catalogo)]
    invalidos = [t for t in tokens if t["campo"] is None]
    if invalidos or not str(padrao or "").strip() or not fichas:
        return {"bloqueado": True, "invalidos": invalidos, "tokens": tokens,
                "linhas": []}

    usados = _template.campos_usados(padrao, catalogo)
    linhas = []
    for ficha in fichas:
        nome = _template.render(padrao, ficha).strip()
        de_origem = False
        if not nome:
            nome, de_origem = str(ficha.get("name") or ""), True
        linhas.append({
            "nome": nome,
            "de_origem": de_origem,
            "vazios": [c for c in usados if not str(ficha.get(c) or "").strip()],
            "vazio_total": not nome.strip(),
            "repetido": False,
        })
    # ⚠️ A colisão é marcada nos DOIS lados: quem vê só o segundo assinalado conclui
    # que o primeiro está certo, e vai procurar o problema no lugar errado.
    contagem: dict[str, int] = {}
    for l in linhas:
        contagem[l["nome"]] = contagem.get(l["nome"], 0) + 1
    for l in linhas:
        l["repetido"] = contagem[l["nome"]] > 1

    return {
        "bloqueado": any(l["vazio_total"] for l in linhas),
        "invalidos": [],
        "tokens": tokens,
        "linhas": linhas,
    }
