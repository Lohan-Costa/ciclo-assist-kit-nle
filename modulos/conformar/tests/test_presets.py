"""O preset de export embarcado — travado por regressão, sem precisar do MC aberto.

Rodar:

    PYTHONPATH=plugins/media-composer/servico .venv-win/Scripts/python tests/test_presets.py   (Windows)
    PYTHONPATH=plugins/media-composer/servico .venv/bin/python tests/test_presets.py            (macOS)

## Por que estes casos existem

O bloco `<AvClass id="EXst">` de um preset **ANINHA** — tem um `AvClass` filho dentro de
um `AvProp`. A extração usava um não-guloso (`r'<AvClass id="EXst">.*?</AvClass>'`), que
para no fechamento do FILHO: cada bloco saía **truncado em exatamente 31 caracteres**, a
cauda `'\\n      </AvProp>\\n    </AvClass>'`.

⚠️ **E o defeito escondia a si mesmo**, que é por que ele sobreviveu:

- o recurso embarcado tinha sido extraído com a mesma regex, então **não era XML
  bem-formado** (2 `AvClass` abertos, 1 fechado);
- `instalar()` o inseria no `<usuário> Settings.xml` do editor e o deixava **inválido**
  (1935 aberturas contra 1934 fechamentos, medido num arquivo real de 6,7 MB) —
  devolvendo `{'ok': True}`;
- e `diagnostico()` respondia `situacao: 'ok'` em seguida, porque truncava os **dois**
  lados com a mesma regex e a comparação batia.

Nada levantava exceção. O que apareceria, muito depois, seria o Media Composer perdendo
todas as preferências do editor — longe da causa, culpando qualquer outra coisa.

Medido em 2026-08-16 (MC 25.6, Windows) ao investigar por que o rpc `LoadSetting`
recusava o recurso embarcado com `Parse Error`: a recusa estava certa, o XML é que
estava quebrado.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

import presets  # noqa: E402

# A cauda que o não-guloso descartava. Fixada aqui porque é o valor MEDIDO, não deduzido.
CAUDA = "\n      </AvProp>\n    </AvClass>"

# Um `Settings.xml` mínimo com o mesmo aninhamento do real: `AvClass` de export contendo
# um `AvProp` com um `AvClass` filho. É o aninhamento — não o tamanho — que quebra a
# extração ingênua.
def _bloco(nome: str, formato: str) -> str:
    return (
        '    <AvClass id="EXst">\n'
        f'      <AvProp id="ASET" name="name" type="string">{nome}</AvProp>\n'
        '      <AvProp id="ASET" name="kind" type="string">Export</AvProp>\n'
        '      <AvProp id="EXst" name="iAttrs" type="object">\n'
        '        <AvClass id="ATTR">\n'
        '          <List>\n'
        '            <ListElem>\n'
        '              <AvProp id="ATTR" name="OMFI:ATTB:Kind" type="int32">1</AvProp>\n'
        '              <AvProp id="ATTR" name="OMFI:ATTB:Name" type="string">_EXPORTFORMAT</AvProp>\n'
        f'              <AvProp id="ATTR" name="OMFI:ATTB:IntAttribute" type="int32">{formato}</AvProp>\n'
        '            </ListElem>\n'
        '          </List>\n'
        '        </AvClass>' + CAUDA + "\n")


def _settings(blocos: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
        '<Avid:StreamItems xmlns:Avid="http://www.avid.com">\n'
        "  <Avid:XMLFileData>\n" + blocos + "  </Avid:XMLFileData>\n"
        "</Avid:StreamItems>\n")


def main() -> int:
    falhas: list[str] = []

    def checa(ok: bool, rotulo: str, detalhe: str = "") -> None:
        print(f"{'  ok  ' if ok else ' FALHA'} {rotulo}")
        if not ok:
            falhas.append(detalhe or rotulo)

    # ── 1) o recurso embarcado é XML bem-formado ────────────────────────────
    bruto = presets.preset_embarcado()
    checa(bruto is not None, "o recurso embarcado existe no pacote")
    if bruto:
        try:
            raiz = ET.fromstring(bruto)
            checa(raiz.tag == "AvClass" and raiz.get("id") == "EXst",
                  f"o recurso é um AvClass EXst (veio {raiz.tag}/{raiz.get('id')})")
        except ET.ParseError as e:
            checa(False, "o recurso embarcado é XML bem-formado",
                  f"o recurso embarcado NÃO é XML bem-formado: {e}")
        checa(presets.formato_de(bruto) == presets.FORMATO_AAF,
              f"o recurso embarcado é AAF (_EXPORTFORMAT={presets.FORMATO_AAF})")
        checa(presets._nome_do(bruto) == presets.NOME_PRESET,
              f"o recurso se chama {presets.NOME_PRESET!r}")

    # ── 2) a extração devolve blocos COMPLETOS ─────────────────────────────
    texto = _settings(_bloco("AAF-DLPC", "20") + _bloco("Pro Tools", "25"))
    blocos = presets.blocos_de_export(texto)
    checa(len(blocos) == 2, f"acha os 2 presets de export (achou {len(blocos)})")
    for b in blocos:
        try:
            ET.fromstring(b)
            ok = True
        except ET.ParseError:
            ok = False
        checa(ok, f"o bloco {presets._nome_do(b)!r} sai balanceado",
              f"bloco {presets._nome_do(b)!r} veio truncado — é o bug do não-guloso")
    checa(all(b.rstrip().endswith("</AvClass>") for b in blocos),
          "todo bloco termina no fechamento EXTERNO")
    checa({presets._nome_do(b) for b in blocos} == {"AAF-DLPC", "Pro Tools"},
          "os nomes saem certos")
    checa([presets.formato_de(b) for b in blocos] == ["20", "25"],
          "o _EXPORTFORMAT de cada bloco sai certo")

    # ── 3) instalar NÃO pode invalidar o Settings.xml ───────────────────────
    # ⭐ É este o caso que faltava. Os outros verificam a extração; este verifica a
    # CONSEQUÊNCIA — e é a consequência que custa caro, porque o arquivo tem todas as
    # preferências do editor.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / "CICLO Settings.xml"
        alvo.write_text(_settings(_bloco("Pro Tools", "25")), encoding="utf-8")
        try:
            ET.fromstring(alvo.read_text(encoding="utf-8"))
            partida_ok = True
        except ET.ParseError:
            partida_ok = False
        checa(partida_ok, "o Settings.xml de partida é válido")

        r = presets.instalar(alvo, forcar=True)
        checa(bool(r.get("ok")), f"instalar() reporta sucesso ({r.get('erro', '')})")

        depois = alvo.read_text(encoding="utf-8")
        try:
            ET.fromstring(depois)
            valido = True
            erro = ""
        except ET.ParseError as e:
            valido = False
            erro = str(e)
        checa(valido, "o Settings.xml SEGUE VÁLIDO depois de instalar",
              f"instalar() invalidou o Settings.xml do editor: {erro}")

        nomes = set(presets.presets_de_export(alvo))
        checa(presets.NOME_PRESET in nomes,
              f"o preset entrou no arquivo (presets: {sorted(nomes)})")
        checa("Pro Tools" in nomes, "o preset que já existia continua lá")

    total = 15
    print(f"\n{total - len(falhas)}/{total} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
