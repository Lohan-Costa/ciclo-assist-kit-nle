"""A rota `.avb`: percurso, masters, achatamento e repontamento — sem MC, sem mídia.

Rodar:

    PYTHONPATH="motor;plugins/media-composer/servico" .venv-win/Scripts/python tests/test_avb_bin.py

## Por que estes casos, e não outros

Todos travam armadilhas **medidas** em 2026-08-16, e as quatro primeiras falham em
**silêncio** — a varredura roda inteira, não levanta exceção e devolve um número menor do
que devia:

1. **No pyavb não existe classe `MasterMob`.** Todo mob é `Composition` e quem distingue é
   o atributo `mob_type`. O teste à moda do pyaaf2 (`type(m).__name__`) devolve **zero
   masters**, como se o acervo estivesse vazio.
2. **`tracks` é propriedade numa classe e MÉTODO noutra.** Iterar sem checar `callable`
   estoura `TypeError` **no meio** do percurso, com parte da timeline já contada.
3. **`track_id` sozinho não identifica a track**: `index=1` existe para imagem E som.
   Casar só pelo índice põe som na track de imagem.
4. **Repontar por NOME é no-op silencioso**: o master AMA novo tem exatamente o mesmo nome
   do offline que ele substitui. Medido: 44 masters presentes, 0 repontados.
5. **Achatar soma o offset do subclipe** ao do clipe na timeline — errar aqui desloca a
   edição inteira sem nenhum erro.

Os objetos são dublês: modelam a superfície do pyavb que o motor toca, o que mantém o
teste portátil (sem `.avb` de fixture) e força as armadilhas a aparecerem.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

from aaf.masters import chave_mob  # noqa: E402
from avb_bin import audio, denest, masters, percurso, remap  # noqa: E402

URN = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.{:08x}.1bb20000.060e2b34.7f7f2a80"


class MobID(str):
    """Um MobID que é texto — basta para `str()`, `chave_mob` e comparação."""


def mid(n: int) -> MobID:
    return MobID(URN.format(n))


class SourceClip:
    def __init__(self, mob_id, track_id=1, start_time=0, media_kind="picture", length=100):
        self.mob_id = mob_id
        self.track_id = track_id
        self.start_time = start_time
        self.media_kind = media_kind
        self.length = length


class Sequence:
    def __init__(self, componentes, length=100):
        self.components = componentes
        self.length = length


class Track:
    def __init__(self, index, media_kind, component):
        self.index = index
        self.media_kind = media_kind
        self.component = component


class Mob:
    """⚠️ UMA classe só para todos os papéis — como no pyavb. `mob_type` é quem separa."""

    def __init__(self, mob_id, mob_type, nome="", tracks=(), usage=None):
        self.mob_id = mob_id
        self.mob_type = mob_type
        self.name = nome
        self.tracks = list(tracks)
        self.usage = usage


class MobMetodo(Mob):
    """⚠️ Um mob cujo `tracks` é MÉTODO — existe no pyavb e derruba percurso ingênuo."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._t = self.tracks
        type(self).tracks = property(lambda s: s._t)

    def tracks(self):  # noqa: D102 — nunca chamado; serve de armadilha
        return self._t


class Conteudo:
    def __init__(self, mobs):
        self.mobs = mobs


class Bin:
    def __init__(self, mobs):
        self.content = Conteudo(mobs)


def cenario():
    """Timeline com 1 subclipe (imagem + 2 sons) e 1 master direto (música).

    O subclipe aponta para o master de CÂMERA na imagem e para o de SOM DIRETO nas duas
    trilhas de som — a mesma forma medida no material real.
    """
    cam, som, mus = mid(1), mid(2), mid(3)
    sub_id = mid(9)

    master_cam = Mob(cam, "MasterMob", "A001_C004",
                     [Track(1, "picture", Sequence([], 500)),
                      Track(1, "sound", Sequence([], 500))])
    master_som = Mob(som, "MasterMob", "SOM DIRETO T001",
                     [Track(1, "sound", Sequence([], 900)),
                      Track(2, "sound", Sequence([], 900))])
    master_mus = Mob(mus, "MasterMob", "trilha.wav",
                     [Track(1, "sound", Sequence([], 300))])

    # ⚠️ O subclipe tem index=1 de IMAGEM e index=1 de SOM — a armadilha do track_id.
    subclipe = Mob(sub_id, "CompositionMob", "04-02-01", [
        Track(1, "picture", SourceClip(cam, track_id=1, start_time=40, media_kind="picture")),
        Track(1, "sound", Sequence([SourceClip(som, track_id=1, start_time=133,
                                               media_kind="sound")])),
        Track(2, "sound", Sequence([SourceClip(som, track_id=2, start_time=133,
                                               media_kind="sound")])),
    ], usage="subclip")

    timeline = Mob(mid(99), "CompositionMob", "TIMELINE", [
        Track(1, "picture", Sequence([SourceClip(sub_id, 1, 7, "picture")])),
        Track(1, "sound", Sequence([SourceClip(sub_id, 1, 7, "sound")])),
        Track(2, "sound", Sequence([SourceClip(sub_id, 2, 7, "sound")])),
        Track(3, "sound", Sequence([SourceClip(mus, 1, 0, "sound")])),
    ])
    return Bin([timeline, subclipe, master_cam, master_som, master_mus]), {
        "cam": cam, "som": som, "mus": mus, "sub": sub_id, "tl": timeline}


def main() -> int:
    falhas: list[str] = []

    def checa(ok, rotulo, detalhe=""):
        print(f"{'  ok  ' if ok else ' FALHA'} {rotulo}")
        if not ok:
            falhas.append(detalhe or rotulo)

    f, ids = cenario()
    tl = percurso.timeline(f)

    # ── 1) `mob_type`, não o nome da classe ─────────────────────────────────
    todos = f.content.mobs
    checa(sum(1 for m in todos if percurso.e_master(m)) == 3,
          "acha os 3 MasterMob pelo mob_type",
          "e_master não achou os masters — o teste à moda do pyaaf2 devolve zero")
    checa(sum(1 for m in todos if type(m).__name__ == "MasterMob") == 0,
          "⭐ nenhum mob tem 'MasterMob' como NOME DE CLASSE (é essa a armadilha)")
    checa(percurso.e_subclipe(next(m for m in todos if m.mob_id == ids["sub"])),
          "reconhece o subclipe pelo `usage`")

    # ── 2) a timeline é a de mais tracks, entre CompositionMob ──────────────
    checa(tl is not None and tl.name == "TIMELINE",
          f"timeline() acha a composição certa (veio {getattr(tl, 'name', None)!r})")

    # ── 3) `tracks` como MÉTODO não derruba o percurso ──────────────────────
    esquisito = MobMetodo(mid(50), "CompositionMob", "ESQUISITO",
                          [Track(1, "picture", Sequence([SourceClip(ids["cam"])]))])
    try:
        n = len(percurso.source_clips(esquisito))
        checa(n == 1, f"percorre mob com `tracks` calável (achou {n})")
    except TypeError as e:
        checa(False, "percorre mob com `tracks` calável", f"estourou: {e}")

    # ── 4) track_de casa por índice E tipo de mídia ─────────────────────────
    sub = next(m for m in todos if m.mob_id == ids["sub"])
    tr = percurso.track_de(sub, 1, "sound")
    checa(tr is not None and tr.media_kind == "sound",
          "⭐ track_de(1, 'sound') NÃO devolve a track de imagem de índice 1",
          "index=1 de imagem venceu — som cairia na trilha errada, calado")
    checa(percurso.track_de(sub, 1, "picture").media_kind == "picture",
          "track_de(1, 'picture') devolve a de imagem")

    # ── 5) masters_em_uso: subclipe atravessado + master direto ─────────────
    ms = masters.masters_em_uso(f, tl)
    por_nome = {m.nome: m for m in ms}
    checa(len(ms) == 3, f"3 masters em uso (veio {len(ms)})")
    checa(set(por_nome) == {"A001_C004", "SOM DIRETO T001", "trilha.wav"},
          f"acha câmera, som direto e música (veio {sorted(por_nome)})")
    checa(por_nome["SOM DIRETO T001"].segmentos == 2,
          f"o som direto conta 2 segmentos (veio {por_nome['SOM DIRETO T001'].segmentos})")
    checa(por_nome["SOM DIRETO T001"].e_audio and not por_nome["A001_C004"].e_audio,
          "e_audio vem do SourceClip da timeline, não do mob")
    checa(all(len(m.mob_id) == 64 for m in ms),
          "mob_id normalizado em 64 hex (32 bytes)")
    checa(por_nome["A001_C004"].duracao_frames == 500,
          f"duração lida (veio {por_nome['A001_C004'].duracao_frames})")

    # ── 6) ⭐ achatar soma os offsets e zera os subclipes ───────────────────
    r = denest.achatar(f, tl)
    checa(r["achatados"] == 3, f"3 SourceClips achatados (veio {r['achatados']})")
    checa(r["subclipes_restantes"] == 0,
          f"nenhum subclipe restante (veio {r['subclipes_restantes']})")
    scs = percurso.source_clips(tl)
    img = next(s for s in scs if s.media_kind == "picture")
    checa(str(img.mob_id) == str(ids["cam"]),
          "a imagem passou a apontar direto para o master da câmera")
    checa(img.start_time == 47,
          f"⭐ start = 7 (timeline) + 40 (subclipe) = 47 (veio {img.start_time})",
          "o offset do subclipe não somou — a edição sairia deslocada, sem erro")
    som2 = [s for s in scs if s.media_kind == "sound" and str(s.mob_id) == str(ids["som"])]
    checa(len(som2) == 2 and {s.track_id for s in som2} == {1, 2},
          f"os dois canais do som direto mantêm track_id 1 e 2 "
          f"(veio {sorted(s.track_id for s in som2)})",
          "o canal colapsou — e isso NÃO se pega de ouvido")

    # ── 7) ⭐ repontar exige mapa por IDENTIDADE ────────────────────────────
    novo_cam = mid(1001)
    r2 = remap.repontar(f, {chave_mob(ids["cam"]): novo_cam}, tl)
    checa(r2["repontados"] == 1, f"1 referência trocada (veio {r2['repontados']})")
    checa(r2["masters_trocados"] == 1, "1 master trocado")
    checa(str(next(s for s in percurso.source_clips(tl)
                   if s.media_kind == "picture").mob_id) == str(novo_cam),
          "a imagem aponta para o master NOVO")
    checa(r2["sem_destino"] == 3,
          f"os 3 sem entrada no mapa são contados, não silenciados "
          f"(veio {r2['sem_destino']})")

    # ── 8) áudio autorado: as conversões que decidem o online ──────────────
    checa(audio.forma_avid("E:\\MIDIAS\\SD02\\x.WAV") == "E//MIDIAS/SD02/x.WAV",
          "⭐ forma_avid: E:\\A\\B → E//A/B (a diferença que decidia o online)",
          "sem esta conversão o clipe fica offline com o arquivo existindo e mtime batendo")
    checa(len(audio.forma_avid("E:\\MIDIAS\\x.WAV")) == len("E:\\MIDIAS\\x.WAV"),
          "forma_avid é size-neutral (byte-surgery sem corrigir tamanho de chunk)")
    checa(audio.forma_avid("/Volumes/CICLO/x.wav") == "/Volumes/CICLO/x.wav",
          "forma_avid não mexe em caminho POSIX")
    checa(audio.e_audio("a.WAV") and audio.e_audio("b.aif")
          and not audio.e_audio("c.braw"),
          "e_audio separa áudio de vídeo pela extensão")

    # `_AMD_SOURCE_LENGTH`: o u64 de 8 bytes que o `scoped_replace_u32` não alcança —
    # com o valor do template, o clipe vem offline mesmo com todo o resto correto.
    import struct as _st
    import tempfile as _tmp

    marca = _st.pack("<H", 18) + b"_AMD_SOURCE_LENGTH" + _st.pack("<I", 8)
    bruto = (b"antes" + marca + _st.pack("<Q", 111111)
             + b"meio" + marca + _st.pack("<Q", 222222) + b"fim")
    with _tmp.TemporaryDirectory() as td:
        alvo = Path(td) / "clone.avb"
        alvo.write_bytes(bruto)
        n = audio._patch_amd_source_length(alvo, 25129104)
        depois = alvo.read_bytes()
        checa(n == 2, f"patcha as 2 ocorrências de _AMD_SOURCE_LENGTH (veio {n})")
        valores = [_st.unpack_from("<Q", depois, i + len(marca))[0]
                   for i in range(len(depois) - len(marca))
                   if depois[i:i + len(marca)] == marca]
        checa(valores == [25129104, 25129104],
              f"o u64 passa a valer o nº de samples (veio {valores})")
        checa(len(depois) == len(bruto),
              "o patch é size-neutral (não desloca o resto da bin)")

    # ── 9) ⭐ uso_maximo: o que impede o PMM_INSUFFICIENT_MEDIA ─────────────
    # O master autorado tem de cobrir o maior `start + length` que a timeline pede. Errar
    # por UM frame faz o Media Composer recusar a TIMELINE INTEIRA — medido em 2026-08-16.
    f2, ids2 = cenario()
    tl2 = percurso.timeline(f2)
    denest.achatar(f2, tl2)                      # ⚠️ medir só DEPOIS de achatar
    uso = masters.uso_maximo(f2, tl2)
    checa(uso.get(chave_mob(ids2["cam"])) == 147,
          f"⭐ pede 147 do master da câmera = start 47 + length 100 "
          f"(veio {uso.get(chave_mob(ids2['cam']))})",
          "o mínimo saiu errado — o master nasceria curto e a timeline seria recusada")
    checa(uso.get(chave_mob(ids2["mus"])) == 100,
          f"pede 100 da música, que a timeline referencia direto "
          f"(veio {uso.get(chave_mob(ids2['mus']))})")

    # Medir ANTES de achatar dá um número menor — é o erro que o comentário do módulo
    # descreve, e este caso existe para que ninguém "simplifique" a ordem.
    f3, ids3 = cenario()
    tl3 = percurso.timeline(f3)
    uso_cedo = masters.uso_maximo(f3, tl3)
    checa(uso_cedo.get(chave_mob(ids3["cam"]), 0) < 147,
          f"⭐ medir ANTES de achatar subestima (veio "
          f"{uso_cedo.get(chave_mob(ids3['cam']), 0)}, o certo é 147)")

    checa(audio.TOLERANCIA_FRAMES == 2,
          f"a tolerância de preenchimento é de 2 frames (veio {audio.TOLERANCIA_FRAMES})",
          "acima disso o arquivo é OUTRO, e preencher com silêncio esconderia o erro")

    # ── 10) ⭐ relink parcial: o que NÃO SE SABE tem de passar ──────────────
    # Mesma regra da degradação do ADR 0011: o caminho degradado nunca pode ser mais
    # RESTRITIVO que o completo. Um master de mídia gerenciada não diz pela bin se está
    # offline; tratá-lo como "online" o descartaria calado, e o editor veria menos
    # clipes relinkados sem nenhuma explicação.
    from relink import filtrar_masters  # noqa: PLC0415

    class _M:
        def __init__(self, nome, e_ama, offline):
            self.nome, self.e_ama, self.esta_offline = nome, e_ama, offline

    amostra = [_M("ama-online", True, False), _M("gerenciado", False, None),
               _M("ama-offline", True, True), _M("desconhecido", None, None)]

    mantidos, _c = filtrar_masters(amostra, False, False)
    checa(len(mantidos) == 4, "sem filtro, passa tudo")

    mantidos, c = filtrar_masters(amostra, True, False)
    nomes = [m.nome for m in mantidos]
    checa(nomes == ["gerenciado", "desconhecido"],
          f"“só importados” tira os AMA e MANTÉM o desconhecido (veio {nomes})",
          "o desconhecido foi descartado — filtro mais restritivo que o completo")
    checa(c["fora_por_ama"] == 2, f"conta os 2 que saíram (veio {c['fora_por_ama']})")

    mantidos, _c = filtrar_masters(amostra, False, True)
    nomes = [m.nome for m in mantidos]
    checa(nomes == ["gerenciado", "ama-offline", "desconhecido"],
          f"⭐ “só offline” tira só o que se SABE online (veio {nomes})",
          "descartou um master cujo estado é desconhecido")

    mantidos, _c = filtrar_masters(amostra, True, True)
    checa([m.nome for m in mantidos] == ["gerenciado", "desconhecido"],
          "os dois filtros se somam")

    # ⭐ "Carregar a seleção da timeline" (2026-10-25): só os masters dos clipes selecionados, em qualquer grafia
    for m, h in zip(amostra, ("a1", "b2", "c3", "d4")):
        m.mob_id = "urn:smpte:umid:060a2b34." + h * 28
    sel = ["060a2b34-" + "B2" * 28, "060A2B34" + "d4" * 28]
    mantidos, c = filtrar_masters(amostra, False, False, sel)
    checa([m.nome for m in mantidos] == ["gerenciado", "desconhecido"],
          f"⭐ “só a seleção” fica com os masters selecionados, pela grafia que vier (veio {[m.nome for m in mantidos]})")
    checa(c.get("fora_da_selecao") == 2, f"conta os 2 fora da seleção (veio {c})")
    mantidos, _c = filtrar_masters(amostra, False, True, sel)
    checa([m.nome for m in mantidos] == ["gerenciado", "desconhecido"], "a seleção soma com “só offline”")

    total = 43
    print(f"\n{total - len(falhas)}/{total} casos")
    for x in falhas:
        print("  !", x)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
