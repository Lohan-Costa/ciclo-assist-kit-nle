"""A bin AMA que o pyavb não consegue regravar — o que, exatamente, o Media Composer recusa?

    python spikes/a_bin_ama_regravada.py              # só escreve as variantes, NÃO toca no MC
    python spikes/a_bin_ama_regravada.py --abrir      # põe o Media Composer a julgar

⛔⛔ O ponto de partida (`spikes/mover_entre_bins.py`, 2026-09-12): bin com `SourceMob` de
`WinFileLocator` (material AMA) passada pelo `write()` do pyavb → `OpenBin` recusa a bin
INTEIRA com `FILE_OPEN_FAILURE`. Aquilo parou em "é o mob AMA"; não disse o que no ARQUIVO.

⭐ O que se mediu antes de escrever este spike, só lendo bytes:

- Descontada a renumeração das referências, **todo objeto regravado é idêntico byte a byte**
  ao original (574 de 574 na bin da sequência). O `WINF` não é mal serializado.
- Mesmo tamanho, mesma contagem, nenhum órfão.
- Sobram DUAS diferenças: a **ordem dos objetos no arquivo** (o pyavb escreve na ordem do
  walk; o MC, noutra) e **4 bytes do cabeçalho** logo depois da data, que o MC preenche e o
  pyavb zera.

⇒ As variantes isolam uma de cada vez. As fixtures do editor NUNCA são escritas.

    python spikes/a_bin_ama_regravada.py ORI --abrir   # a bin recusada em 2026-09-12

## O QUE ISTO MEDIU (2026-09-13, MC 2025.6.58781, pyavb 1.4.0)

**As duas bins AMA do editor** (BRAW, MOV e WAV linkados; 20 `WinFileLocator`): as 7
variantes ABREM, inclusive o `write()` cru do pyavb com uma timeline nova — que é o que o
produto já fazia. ⇒ Nem a ordem dos objetos nem o cabeçalho importam; e "mob AMA condena a
bin" estava **errado**.

**A `BIN ORIGEM`, recusada ontem**, comparada byte a byte: os dois `WinFileLocator` dela têm
o caminho UTF-8 **nulo** — tamanho `ff ff`. O pyavb lê `""` e grava `00 00`.

| a `BIN ORIGEM` regravada | `OpenBin` |
|---|---|
| pyavb cru | ⛔ `FILE_OPEN_FAILURE` |
| pyavb com o `0xFFFF` preservado | ✅ |
| idem + timeline nova | ✅ |
| bin NOVA do produto (timeline + 13 mobs de fecho, ocultos) | ✅ |

⇒ O conserto mora em `cicloassist/avid/avb_fiel.py`. As outras diferenças que sobraram na
comparação são inofensivas e ficam registradas: taxa de amostragem do `PCMA` em outra
codificação (48·10³ contra 48000, mesmo valor) e um ext `01 01` vazio do `TrackGroup` sem
tracks que o pyavb não repete — a bin de 94 itens já abria com as duas.

⚠️ **Abrir não é carregar** — em 2026-08-30 a bin abria e o MC caía ao carregar. ✅ Por
isso o olho: o editor carregou na Record as timelines `_AMA … TL …` desta rodada (e as do
`montar_corte` com masters AMA e gerenciados), uma bin por vez, e **todas carregaram com a
mídia online e tocando** (2026-09-13).

As bins de trabalho (`_AMA *.avb`) foram apagadas depois da conferência; rodar de novo as
recria.
"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402
from avb.core import walk_references  # noqa: E402
from avb.ioctx import AVBIOContext  # noqa: E402

from cicloassist.avid import avb_fiel  # noqa: E402
from cicloassist.avid import timeline as _timeline  # noqa: E402
from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR")

#: As fixtures do editor (2026-09-13). ⛔ SOMENTE LEITURA.
FIXTURES = {
    "SEQ": PROJETO / "BIN COM SEQUENCIA AMA LINK.avb",
    "MID": PROJETO / "BIN COM MIDIA AMA LINK.avb",
}


#: A bin onde a recusa foi medida em 2026-09-12. ⛔ SOMENTE LEITURA.
ORIGEM_DE_ONTEM = PROJETO / "BIN ORIGEM.avb"


# ── a string nula ────────────────────────────────────────────────────────────


def string_nula(ligar: bool) -> None:
    """Liga ou desliga o conserto do PRODUTO (`cicloassist/avid/avb_fiel.py`).

    ⚠️ Importar `cicloassist.avid` já o liga; as medições "sem conserto" o desligam
    explicitamente, senão mediriam o conserto achando que medem o pyavb cru.
    """
    if ligar:
        avb_fiel.aplicar()
    else:
        AVBIOContext.read_string = avb_fiel._ler_do_pyavb
        AVBIOContext.write_string = avb_fiel._escrever_do_pyavb


# ── o writer que preserva a ordem ────────────────────────────────────────────


def _bytes_do_cabecalho(caminho: Path) -> bytes:
    """Os 4 bytes entre a data de gravação e `ATob` (lidos em disco como `boTA`)."""
    cru = caminho.read_bytes()[:200]
    k = cru.index(b"boTA")
    return cru[k - 4:k]


def escrever_na_ordem(f, saida: Path, cabecalho: bytes | None = None) -> None:
    """Grava como o `AVBFile.write`, mas os objetos que vieram do arquivo mantêm a ORDEM
    relativa que tinham nele; os novos entram depois; a raiz (`Bin`) é sempre o último.

    ⚠️ As referências se resolvem pelo mapa pré-povoado, então apontar para a frente é
    permitido — o `write_object_ref` do pyavb só exige que o id esteja no mapa.
    """
    n_original = len(getattr(f, "object_positions", [0])) - 1
    vistos, todos = set(), []
    for o in walk_references(f.content):
        if o.instance_id not in vistos:
            vistos.add(o.instance_id)
            todos.append(o)

    raiz = f.content
    antigos = sorted((o for o in todos if o is not raiz and o.instance_id <= n_original),
                     key=lambda o: o.instance_id)
    novos = [o for o in todos if o is not raiz and o.instance_id > n_original]
    ordem = antigos + novos + [raiz]

    f.ref_mapping = {o.instance_id: i + 1 for i, o in enumerate(ordem)}
    f.next_chunk_id = len(ordem)
    f.octx = AVBIOContext("little")
    try:
        with io.open(saida, "wb") as out:
            pos = f.write_header(out)
            for o in ordem:
                f.write_object(out, o)
            fim = out.tell()
            out.seek(pos)
            f.octx.write_u32(out, len(ordem))
            f.octx.write_u32(out, len(ordem))     # a raiz é o último
            out.seek(fim)
    finally:
        f.octx = None

    if cabecalho is not None:
        cru = bytearray(saida.read_bytes())
        k = cru.index(b"boTA", 0, 200)
        cru[k - 4:k] = cabecalho
        saida.write_bytes(bytes(cru))


# ── a timeline de teste ──────────────────────────────────────────────────────


def _entradas(f) -> list:
    """Duas entradas curtas: um master com imagem e um master só de som, os dois AMA."""
    saida = []
    for item in f.content.items:
        m = item.mob
        if str(getattr(m, "mob_type", "")) != "MasterMob":
            continue
        pares, conta = [], {"picture": 0, "sound": 0}
        for t in m.tracks:
            kind = str(getattr(t.component, "media_kind", ""))
            if kind in conta:
                conta[kind] += 1
                pares.append((kind, conta[kind]))
        if not pares:
            continue
        tem_imagem = conta["picture"] > 0
        saida.append((m.name, str(m.mob_id), tuple(pares), tem_imagem))

    imagem = next((s for s in saida if s[3]), None)
    som = next((s for s in saida if not s[3]), None)
    escolhidas = [s for s in (imagem, som) if s]
    for nome, _, pares, _ in escolhidas:
        print(f"   entrada: {nome!r} {pares}")
    return [_timeline.Entrada(mob_id=mid, duracao=48, trilhas=pares, start_time=0)
            for _, mid, pares, _ in escolhidas]


# ── as variantes ─────────────────────────────────────────────────────────────


def variantes(chave: str) -> list[tuple[str, Path]]:
    fixture = FIXTURES[chave]
    cab = _bytes_do_cabecalho(fixture)
    print(f"\n{fixture.name}: cabeçalho do MC {cab.hex(' ')}")
    feitas = []
    # ⚠️ 0 a 6 medem o pyavb CRU, como na primeira rodada, antes de o conserto existir.
    string_nula(False)

    def caminho(rotulo):
        return PROJETO / f"_AMA {chave} {rotulo}.avb"

    p = caminho("0 copia crua")
    shutil.copy2(fixture, p)
    feitas.append(("controle: cópia crua do arquivo", p))

    p = caminho("1 pyavb")
    with avb.open(str(fixture)) as f:
        f.write(str(p))
    feitas.append(("pyavb write, sem mudar nada", p))

    p = caminho("2 ordem")
    with avb.open(str(fixture)) as f:
        escrever_na_ordem(f, p)
    feitas.append(("ordem original, cabeçalho do pyavb", p))

    p = caminho("3 ordem+cab")
    with avb.open(str(fixture)) as f:
        escrever_na_ordem(f, p, cabecalho=cab)
    igual = p.read_bytes() == fixture.read_bytes()
    feitas.append((f"ordem original + cabeçalho do MC (idêntico ao original: {igual})", p))

    p = caminho("4 pyavb+cab")
    with avb.open(str(fixture)) as f:
        f.write(str(p))
    cru = bytearray(p.read_bytes())
    k = cru.index(b"boTA", 0, 200)
    cru[k - 4:k] = cab
    p.write_bytes(bytes(cru))
    feitas.append(("pyavb write + cabeçalho do MC", p))

    p = caminho("5 ordem+timeline")
    with avb.open(str(fixture)) as f:
        _timeline.montar_timeline(f, f"_AMA {chave} TL ordem", _entradas(f), 23.976)
        escrever_na_ordem(f, p, cabecalho=cab)
    feitas.append(("ordem original + cabeçalho do MC + timeline NOVA", p))

    p = caminho("6 pyavb+timeline")
    with avb.open(str(fixture)) as f:
        _timeline.montar_timeline(f, f"_AMA {chave} TL pyavb", _entradas(f), 23.976)
        f.write(str(p))
    feitas.append(("pyavb write + timeline NOVA (o que o produto faz hoje)", p))

    string_nula(True)
    feitas.append(bin_nova_com_fecho(fixture, PROJETO / f"_AMA {chave} 9 nova+fecho.avb",
                                     f"_AMA {chave} TL nova"))

    for rotulo, p in feitas:
        with avb.open(str(p)) as f:
            n = len(f.content.items)
        print(f"   {p.name:32s} {p.stat().st_size:>7} bytes, {n:>3} itens · {rotulo}")
    return feitas


def bin_nova_com_fecho(fixture: Path, saida: Path, nome: str) -> tuple[str, Path]:
    """O caminho do PRODUTO para a bin nova: só a timeline visível, o fecho oculto."""
    with avb.open(str(fixture)) as f:
        entradas = _entradas(f)
    _timeline.escrever_bin(saida, [(nome, entradas)], 23.976, base=fixture)
    with avb.open(str(saida)) as f:
        ocultos = sum(1 for i in f.content.items if not i.user_placed)
    return (f"bin NOVA do produto: timeline + {ocultos} mobs de fecho ocultos", saida)


def variantes_da_origem() -> list[tuple[str, Path]]:
    """A bin recusada ontem, com e sem o conserto da string nula."""
    print(f"\n{ORIGEM_DE_ONTEM.name}")
    feitas = []

    p = PROJETO / "_AMA ORI 1 pyavb.avb"
    string_nula(False)
    with avb.open(str(ORIGEM_DE_ONTEM)) as f:
        f.write(str(p))
    feitas.append(("pyavb write, sem conserto (a recusa de ontem)", p))

    string_nula(True)
    try:
        p = PROJETO / "_AMA ORI 7 nula.avb"
        with avb.open(str(ORIGEM_DE_ONTEM)) as f:
            f.write(str(p))
        feitas.append(("pyavb write + string nula preservada", p))

        p = PROJETO / "_AMA ORI 8 nula+timeline.avb"
        with avb.open(str(ORIGEM_DE_ONTEM)) as f:
            _timeline.montar_timeline(f, "_AMA ORI TL nula", _entradas(f), 23.976)
            f.write(str(p))
        feitas.append(("pyavb write + string nula + timeline NOVA", p))
    finally:
        string_nula(False)

    # ⚠️ O produto aplica o conserto ao importar `cicloassist.avid` — aqui ele é religado
    #    só para esta variante, que passa pelo `escrever_bin` de verdade.
    string_nula(True)
    try:
        feitas.append(bin_nova_com_fecho(ORIGEM_DE_ONTEM, PROJETO / "_AMA ORI 9 nova+fecho.avb",
                                         "_AMA ORI TL nova"))
    finally:
        string_nula(False)

    for rotulo, p in feitas:
        print(f"   {p.name:32s} {p.stat().st_size:>7} bytes · {rotulo}")
    return feitas


def julgar(todas: list[tuple[str, Path]]) -> None:
    print("\n" + "=" * 78)
    print("O MEDIA COMPOSER JULGA — uma bin aberta por vez, as fixtures fechadas")
    print("=" * 78)
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            print("o Media Composer não está aberto.")
            return

        def rel(p):
            return mc.caminho_relativo_da_bin(str(p))

        def fechar(p):
            try:
                mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel(p))
            except Exception:   # noqa: BLE001 — bin já fechada é o normal
                pass

        for fx in FIXTURES.values():
            fechar(fx)
        for _, p in todas:
            fechar(p)

        for rotulo, p in todas:
            try:
                mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel(p))
                itens = mc.itens_da_bin(rel(p), tipos=("AllTypes",))
                print(f"✅ {p.name:32s} abriu, {len(itens)} na janela · {rotulo}")
                for i in itens:
                    if "TL" in (i.nome or ""):
                        print(f"      ↳ {i.nome}")
            except Exception as e:      # noqa: BLE001 — é o que se quer medir
                print(f"⛔ {p.name:32s} {str(e)[:70]} · {rotulo}")
            fechar(p)


def main() -> int:
    for fx in FIXTURES.values():
        if not fx.exists():
            sys.exit(f"fixture ausente: {fx}")
    chaves = [a for a in sys.argv[1:] if a in FIXTURES]
    if "ORI" not in sys.argv and not chaves:
        chaves = list(FIXTURES)
    todas = []
    for chave in chaves:
        todas += variantes(chave)
    if "ORI" in sys.argv:
        todas += variantes_da_origem()
    if "--abrir" in sys.argv:
        julgar(todas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
