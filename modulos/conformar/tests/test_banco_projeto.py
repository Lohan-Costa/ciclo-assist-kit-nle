r"""A ligação projeto ⇄ banco de mídias — sem Media Composer, sem rede.

⭐ **O que este teste prova é uma decisão de desenho, não uma função:** a configuração
vive na PASTA DO PROJETO (`.delapraca.json`), e não na máquina. Daí saem de graça três
comportamentos que ninguém precisou programar:

* abrir o projeto já traz o banco conectado — o gesto que diz "estou nesta produção" é
  abrir o projeto, e ele é o mesmo gesto que acha a configuração;
* **trocar de projeto desconecta** — a pasta é outra, a configuração é outra;
* o assistente que abrir o MESMO projeto encontra o banco já conectado, porque a pasta
  do projeto costuma ser compartilhada.

Guardar isso em `pasta_dados()` daria o efeito errado: o banco da novela seguiria o
EDITOR para dentro do projeto de outro cliente.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import banco  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<52} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        projeto = base / "PROJETOS" / "PRODUCAO-A"
        outro = base / "PROJETOS" / "OUTRA NOVELA"
        projeto.mkdir(parents=True)
        outro.mkdir(parents=True)
        bancos = base / "SERVIDOR" / "bancos"
        bancos.mkdir(parents=True)

        print("── começa desconectado, e sem inventar aviso ────────────────")
        est = banco.estado(str(projeto))
        ok("nenhum banco no projeto novo", est["conectado"], False)
        ok("e sem aviso, porque não há nada configurado", est.get("aviso"), "")

        print("\n── criar (o caminho vem do diálogo de salvar) ───────────────")
        # O diálogo devolve o caminho que o editor COMPÔS; o nome vira a pasta do banco.
        est = banco.criar(str(projeto), str(bancos / "NOVELA PRODUCAO-A"))
        ok("conectou depois de criar", est["conectado"], True)
        ok("o nome é o que o editor digitou", est["nome"], "NOVELA PRODUCAO-A")
        ok("⭐ o banco é uma PASTA com banco.json dentro",
           (bancos / "NOVELA PRODUCAO-A" / "banco.json").is_file(), True)
        ok("e a config ficou na pasta do projeto",
           (projeto / ".delapraca.json").is_file(), True)

        # ⚠️ O editor pode digitar "NOVELA X.json" por hábito. O nome do banco não pode
        # herdar a nossa implementação.
        est2 = banco.criar(str(outro), str(bancos / "SEGUNDA.json"))
        ok("⚠️ extensão digitada por hábito não vira nome", est2["nome"], "SEGUNDA")

        # ⚠️ O nome tem de SOBREVIVER a uma regravação. `producao` mora dentro de
        # `_meta`, e lê-lo do topo devolvia "" — o nome digitado se perdia na primeira
        # vez que o banco fosse consolidado, e o defeito era invisível porque a tela cai
        # no nome da PASTA como reserva.
        from media import banco_midias
        b = banco_midias.Banco.abrir(bancos / "NOVELA PRODUCAO-A")
        ok("⭐ o nome sobrevive a reabrir", b.producao, "NOVELA PRODUCAO-A")
        b.consolidar()
        ok("⚠️ e a uma regravação",
           banco_midias.Banco.abrir(bancos / "NOVELA PRODUCAO-A").producao,
           "NOVELA PRODUCAO-A")

        print("\n── ⭐ trocar de projeto desconecta, sem código para isso ─────")
        ok("o outro projeto vê o SEU banco", banco.estado(str(outro))["nome"], "SEGUNDA")
        ok("e o primeiro continua no dele",
           banco.estado(str(projeto))["nome"], "NOVELA PRODUCAO-A")
        terceiro = base / "PROJETOS" / "SEM BANCO"
        terceiro.mkdir()
        ok("⭐ projeto sem config: desconectado",
           banco.estado(str(terceiro))["conectado"], False)

        print("\n── conectar a um banco existente ────────────────────────────")
        est = banco.conectar(str(terceiro), str(bancos / "NOVELA PRODUCAO-A"))
        ok("aponta para a pasta", est["nome"], "NOVELA PRODUCAO-A")
        # ⭐ O editor escolhe o `banco.json` no diálogo; aceitar o arquivo E a pasta
        # evita uma recusa por um detalhe que não muda nada.
        est = banco.conectar(str(terceiro),
                             str(bancos / "SEGUNDA" / "banco.json"))
        ok("⭐ e também aceita o próprio banco.json", est["nome"], "SEGUNDA")

        print("\n── recusas que EXPLICAM ─────────────────────────────────────")
        nao_banco = base / "uma pasta qualquer"
        nao_banco.mkdir()
        try:
            banco.conectar(str(terceiro), str(nao_banco))
            ok("pasta que não é banco deveria recusar", "não recusou", "recusa")
        except ValueError as e:
            ok("pasta que não é banco: recusa dizendo o que falta",
               "banco.json" in str(e), True)
        try:
            banco.criar(str(projeto), str(bancos / "NOVELA PRODUCAO-A"))
            ok("criar em cima de um banco deveria recusar", "não recusou", "recusa")
        except ValueError as e:
            ok("⚠️ criar em cima de um banco existente: recusa", "já existe" in str(e), True)

        print("\n── o caminho é guardado nas DUAS formas ─────────────────────")
        cfg = json.loads((projeto / ".delapraca.json").read_text(encoding="utf-8"))
        ok("guardou o absoluto", bool(cfg["banco"].get("abs")), True)
        # ⭐ Mesmo volume: existe forma relativa, e é ela que atravessa montagens.
        ok("⭐ e o relativo, porque estão no mesmo volume",
           bool(cfg["banco"].get("rel")), True)

        # ⚠️ Config apontando para um banco que sumiu NÃO é erro: é "desconectado", com
        # motivo. Levantar aqui bloquearia o relink por causa de um acelerador opcional.
        import shutil
        shutil.rmtree(bancos / "SEGUNDA")
        est = banco.estado(str(outro))
        ok("⚠️ banco sumido: desconectado, não exceção", est["conectado"], False)
        ok("e com o motivo na mão", "não foi encontrado" in (est.get("aviso") or ""), True)

        print("\n── desconectar não apaga banco ──────────────────────────────")
        est = banco.desconectar(str(projeto))
        ok("desconectou", est["conectado"], False)
        ok("⚠️ e o banco continua no disco",
           (bancos / "NOVELA PRODUCAO-A" / "banco.json").is_file(), True)
        ok("dá para reconectar depois",
           banco.conectar(str(projeto), str(bancos / "NOVELA PRODUCAO-A"))["conectado"],
           True)

        print("\n── nada disto pode derrubar o serviço ───────────────────────")
        ok("projeto vazio devolve desconectado", banco.estado("")["conectado"], False)
        (terceiro / ".delapraca.json").write_text("{ isto não é json", encoding="utf-8")
        ok("config corrompida devolve desconectado, não estoura",
           banco.estado(str(terceiro))["conectado"], False)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
