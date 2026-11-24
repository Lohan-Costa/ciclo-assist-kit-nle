"""Magic Link Avid → Avid: a Carta de uma timeline leva a BIN do Avid anexa (autor, 2026-10-12).

Rodar:

    .venv-win/Scripts/python tests/test_magic_link_bin_anexa.py      (Mac: .venv/bin/python)

- o anexo tem o nome da Carta, `.avb` no lugar de `.carta.json`, e é gravado atômico (nada de `.parcial` sobrando);
- a caixa de quem recebe diz onde está a bin (`bin_anexa`), e vazio quando ela não veio;
- arquivar a Carta (depois de entrar) leva a bin junto, com o MESMO nome que a Carta ganhou (`X_2`);
- o envio é ACESSÓRIO para a bin: sem ela, a Carta é a de sempre.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"),
                str(RAIZ / "tests")]

import canais  # noqa: E402
import magic_link  # noqa: E402
from carta_aberta.writer import montar  # noqa: E402
from test_carta_ida_e_volta import leitura_sintetica  # noqa: E402

ID = "66666666-6666-4666-8666-666666666666"
casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    import sessao_receber as R

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("── o anexo ──")
        carta = tmp / "SEQ__66666666.carta.json"
        ok("nome do anexo", Path(magic_link.anexo_da_carta(str(carta))).name, "SEQ__66666666.avb")
        bin_ = tmp / "projeto.avb"
        bin_.write_bytes(b"AVB" * 100)
        alvo = magic_link.anexar_bin(str(bin_), str(carta))
        ok("copiada ao lado da Carta", Path(alvo).read_bytes(), bin_.read_bytes())
        ok("nada de .parcial sobrando", sorted(p.name for p in tmp.iterdir() if p.name.endswith(".parcial")), [])

        print("── a caixa de quem recebe ──")
        dados, canal = tmp / "dados", tmp / "canal-cor"
        dados.mkdir()
        caixa = canal / "para-edicao"
        caixa.mkdir(parents=True)
        env = {"id": ID, "tipo": "timeline", "remetente": {"maquina": "X"},
               "enviado_em": "2026-10-13T01:00:00-03:00", "bin_anexa": "SEQ__66666666.avb"}
        doc = montar(leitura_sintetica(), [], "SEQ", envio=env)
        com = caixa / "SEQ__66666666.carta.json"
        com.write_text(json.dumps(doc), encoding="utf-8")
        (caixa / "SEQ__66666666.avb").write_bytes(b"AVB")
        doc2 = montar(leitura_sintetica(), [], "OUTRA",
                      envio={**env, "id": "77777777-7777-4777-8777-777777777777", "bin_anexa": None})
        (caixa / "OUTRA__77777777.carta.json").write_text(json.dumps(doc2), encoding="utf-8")
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados):
            s = R.SessaoReceber()
            cx = s.caixa({"cor": str(canal)})
        por_id = {e["id"]: e for e in cx["envios"]}
        ok("a com bin diz onde ela está", por_id[ID].get("bin_anexa"), str(caixa / "SEQ__66666666.avb"))
        ok("a sem bin: vazio", por_id["77777777-7777-4777-8777-777777777777"].get("bin_anexa"), "")

        print("── arquivar leva a bin junto ──")
        # uma Carta de mesmo nome já arquivada: a nova vira _2, e a bin acompanha o nome
        destino = caixa / canais.IMPORTADO / "timelines"
        destino.mkdir(parents=True, exist_ok=True)   # a caixa já cria as pastas do canal
        (destino / "SEQ__66666666.carta.json").write_text("{}", encoding="utf-8")
        novo = canais.arquivar(str(com), "timeline")
        ok("a Carta virou _2", Path(novo).name, "SEQ__66666666_2.carta.json")
        ok("a bin foi junto, com o mesmo nome", (destino / "SEQ__66666666_2.avb").is_file(), True)
        ok("e saiu da fila", (caixa / "SEQ__66666666.avb").exists(), False)

        print("── sem bin, arquivar é o de sempre ──")
        novo = canais.arquivar(str(caixa / "OUTRA__77777777.carta.json"), "timeline")
        ok("a Carta desceu", Path(novo).is_file(), True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
