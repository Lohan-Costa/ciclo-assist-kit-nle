"""O leitor `.avb → segmentos` da aba Daqui Pra Lá — sem MC, sem mídia.

Rodar:

    .venv-win/Scripts/python tests/test_avb_segmentos.py

Cada caso trava uma convenção MEDIDA em bins reais em 2026-09-24 (ver o topo de
`motor/avb_bin/segmentos.py`). Quase todas falham em **silêncio** se lidas errado: a
timeline sai inteira, sem exceção, com um corte fora do lugar ou uma velocidade invertida.

1. Transição é SOBREPOSIÇÃO: recua o cursor (senão tudo depois dela desloca).
2. `MotionEffect.speed_ratio` é timeline ÷ fonte — o que `build_drt` espera. Um 85% é
   1,1617, não 0,85 (invertido, o Resolve tocaria 116%).
3. `[1000, 1001]` é conformação; fonte de 1 frame é congelamento.
4. `Selector` de clipe desabilitado (`[Filler, clipe]`, `selected=0`) é VAZIO no programa.
5. Subclipe soma o offset — e o nome do clipe continua o que o editor vê.
6. A trilha de timecode certa é a que casa com a taxa da sequência.
7. `WinFileLocator` (`D//…`) é lido, e caminho UNC é recusado ANTES de tocar o disco.
8. Toda trilha fecha no comprimento da sequência — a conferência que pega o resto.

Se `DLPC_BIN_REAL` apontar para uma `.avb`, o teste também a lê e exige que todas as
trilhas fechem. Sem ela, essa parte é PULADA (e o teste sai 0).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import segmentos as S  # noqa: E402

URN = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.{:08x}.1bb20000.060e2b34.7f7f2a80"


def mid(n: int) -> str:
    return URN.format(n)


# ── dublês: a MESMA superfície do pyavb que o leitor toca (o leitor decide pelo NOME
#    da classe, como no pyavb, então cada dublê tem o nome da classe real) ──────────

class Filler:
    def __init__(self, length=0):
        self.length = length


class SourceClip:
    def __init__(self, mob_id, start_time=0, length=10, track_id=1, media_kind="picture"):
        self.mob_id, self.start_time, self.length = mob_id, start_time, length
        self.track_id, self.media_kind = track_id, media_kind


class Sequence:
    def __init__(self, components, media_kind="picture"):
        self.components = components
        self.media_kind = media_kind
        self.length = sum((getattr(c, "length", 0) or 0) * (-1 if type(c).__name__ == "TransitionEffect" else 1)
                          for c in components)


class Track:
    def __init__(self, component, index=1, media_kind=None):
        self.component, self.index = component, index
        self.media_kind = media_kind or getattr(component, "media_kind", None)


class TransitionEffect:
    def __init__(self, length, cutpoint, effect_id="EFF2_BLEND_DISSOLVE"):
        self.length, self.cutpoint, self.effect_id = length, cutpoint, effect_id


class _Grupo:
    def __init__(self, length, tracks, effect_id=None, **pd):
        self.length, self.effect_id = length, effect_id
        self.tracks = [Track(c, i + 1) for i, c in enumerate(tracks)]
        self.property_data = pd


class TrackEffect(_Grupo):
    pass


class Selector(_Grupo):
    pass


class _Item:
    def __init__(self, **pd):
        self.property_data = pd


def curva(*pontos):
    """Um item do `param_list` com `control_track.control_points = [(offset, valor)]`."""
    cps = [_Item(offset=[o, 1], value=v) for o, v in pontos]
    return _Item(control_track=_Item(control_points=cps))


class MotionEffect(_Grupo):
    def __init__(self, length, inner, speed_ratio, p0=(), p1=None, phase_offset=0):
        pl = [curva(*p0)]
        if p1 is not None:
            pl.append(curva(*p1))
        super().__init__(length, [inner], effect_id="EFF_ADV_MOTION_CTL",
                         speed_ratio=speed_ratio, param_list=pl, phase_offset=phase_offset)


class Timecode:
    def __init__(self, start, fps, length=0):
        self.start, self.fps, self.length = start, fps, length


class Locator:
    def __init__(self, **pd):
        self.property_data = pd


class Descriptor:
    def __init__(self, locator=None):
        self.locator = locator


class Mob:
    def __init__(self, mob_id, mob_type, name="", tracks=(), usage=None, usage_code=None,
                 edit_rate=None, length=None, descriptor=None):
        self.mob_id, self.mob_type, self.name = mob_id, mob_type, name
        self.tracks = list(tracks)
        self.usage, self.usage_code = usage, usage_code
        self.edit_rate, self.length = edit_rate, length
        self.descriptor = descriptor


class Master(Mob):
    def __init__(self, mob_id, name, er=25.0, length=5000, fisico=None):
        sc = SourceClip(fisico, length=length) if fisico else Filler(length)
        seq = Sequence([sc])
        seq.edit_rate = er
        super().__init__(mob_id, "MasterMob", name, [Track(seq, 1, "picture")])


class Bin:
    def __init__(self, mobs):
        self.content = type("C", (), {"mobs": mobs})()


def sequencia_de(trilhas, fps=25.0, mob=900):
    comp = max(t.component.length for t in trilhas if t.media_kind in ("picture", "sound"))
    return Mob(mid(mob), "CompositionMob", "MINHA TL", trilhas, usage_code=0,
               edit_rate=fps, length=comp)


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    A, B = Master(mid(1), "CAM_A"), Master(mid(2), "CAM_B")
    V = lambda comps: Track(Sequence([Filler(0)] + comps + [Filler(0)]), 1, "picture")  # noqa: E731

    print("── 1. corte e transição ──────────────────────────────────────")
    trilha = V([SourceClip(mid(1), 100, 50), TransitionEffect(10, 4), SourceClip(mid(2), 200, 40)])
    tl = sequencia_de([trilha])
    r = S.ler_timeline(Bin([A, B, tl]), tl)
    segs = r["segments"]
    ok("três segmentos: clipe, transição, clipe", [s["clip_name"] for s in segs],
       ["CAM_A", "(transition)", "CAM_B"])
    ok("a transição cobre os 10 frames ANTES do fim de A", (segs[1]["timeline_tc_in"],
       segs[1]["timeline_tc_out"], segs[1]["cutpoint"]), ("00:00:01:15", "00:00:02:00", 4))
    ok("⭐ B começa DENTRO de A (sobreposição recua o cursor)", segs[2]["timeline_tc_in"], "00:00:01:15")
    ok("a trilha fecha no comprimento da sequência", r["conferencia"], [])
    ok("source_start do clipe", segs[0]["source_start_frames"], 100)

    print("\n── 2/3. velocidade ───────────────────────────────────────────")

    def vel(me):
        t = V([me])
        s = sequencia_de([t])
        return S.ler_timeline(Bin([A, s]), s)["segments"][0]

    lento = vel(MotionEffect(79, Sequence([Filler(0), SourceClip(mid(1), 1179, 68), Filler(0)]),
                             [79, 68], p0=[(0, 0.85)], p1=[(0, 0.0), (79, 67.15)]))
    ok("⭐ 85% → speed_ratio = timeline/fonte = 79/68", round(lento["speed_ratio"], 4), round(79 / 68, 4))
    ok("constante, criativa", (lento["motion_effect_type"], lento["motion_class"]), ("constant", "creative"))
    ok("mapa de offset é o que o Avid gravou", lento["source_offset_map"], [(0.0, 0.0), (79.0, 67.15)])
    ok("o segmento ocupa o embrulho inteiro na timeline", lento["duration_frames"], 79)
    ok("fonte = início do clipe interno", lento["source_start_frames"], 1179)

    conf = vel(MotionEffect(370, Sequence([SourceClip(mid(1), 37, 371)]), [1000, 1001], p0=[(0, 0.0)]))
    ok("[1000,1001] não é rampa nem congelamento", conf["motion_effect_type"], "constant")
    ok("sem mapa gravado, sintetiza a partir do racional", conf["source_offset_map"][-1],
       (370.0, round(370 / (1000 / 1001), 3)))

    congela = vel(MotionEffect(251, Sequence([SourceClip(mid(1), 9179, 1)]), [251, 1],
                               p0=[(0, 0.0)], p1=[(0, 0.0), (251, 0.0)]))
    ok("fonte de 1 frame é congelamento", congela["motion_effect_type"], "freeze")

    rampa = vel(MotionEffect(100, SourceClip(mid(1), 0, 120), [100, 120],
                             p0=[(0, 0.5), (50, 2.0)], p1=[(0, 0.0), (50, 20.0), (100, 120.0)]))
    ok("curva com valores distintos é rampa", rampa["motion_effect_type"], "ramp")

    print("\n── 4. Selector de clipe desabilitado ─────────────────────────")
    t = V([Selector(30, [Filler(30), SourceClip(mid(1), 5, 30)], is_ganged=True, selected=0)])
    s = sequencia_de([t])
    seg = S.ler_timeline(Bin([A, s]), s)["segments"][0]
    ok("⭐ ramo vazio → o CLIPE sai, marcado DESLIGADO (como o Resolve importa)",
       (seg["is_gap"], seg["disabled"], seg["clip_name"], seg["source_start_frames"]),
       (False, True, "CAM_A", 5))
    t = V([Selector(30, [Filler(30), Filler(30)], is_ganged=True, selected=0)])
    s = sequencia_de([t])
    seg = S.ler_timeline(Bin([A, s]), s)["segments"][0]
    ok("sem clipe em ramo nenhum → vazio desligado", (seg["is_gap"], seg["disabled"]), (True, True))
    t = V([Selector(30, [Filler(30), SourceClip(mid(1), 5, 30)], is_ganged=True, selected=1)])
    s = sequencia_de([t])
    seg = S.ler_timeline(Bin([A, s]), s)["segments"][0]
    ok("ramo selecionado com clipe → o clipe", (seg["clip_name"], seg["source_start_frames"]), ("CAM_A", 5))

    print("\n── 5. subclipe ───────────────────────────────────────────────")
    sub = Mob(mid(50), "CompositionMob", "CAM_A.sub.01",
              [Track(Sequence([Filler(0), SourceClip(mid(1), 1000, 500), Filler(0)]), 1, "picture")],
              usage="subclip", usage_code=2)
    t = V([SourceClip(mid(50), 30, 40)])
    s = sequencia_de([t])
    seg = S.ler_timeline(Bin([A, sub, s]), s)["segments"][0]
    ok("⭐ offset do subclipe SOMA ao do clipe", seg["source_start_frames"], 1030)
    ok("o master é o de verdade, não o subclipe", seg["mob_id"], mid(1))
    ok("o nome é o que o editor vê na timeline", seg["clip_name"], "CAM_A.sub.01")

    # ⚠️ Som de subclipe EMBRULHADO em ganho (medido no curta: 7 clipes perdidos na A1/A2).
    sub_som = Mob(mid(51), "CompositionMob", "CAM_A.sub.02",
                  [Track(Sequence([Filler(0), TrackEffect(500, [SourceClip(mid(1), 2000, 500,
                                                                           media_kind="sound")],
                                                          effect_id="Audio Pan Volume"),
                                   Filler(0)], media_kind="sound"), 1, "sound")],
                  usage="subclip", usage_code=2)
    a1 = Track(Sequence([Filler(0), SourceClip(mid(51), 10, 40, media_kind="sound")],
                        media_kind="sound"), 1, "sound")
    s = sequencia_de([a1])
    seg = S.ler_timeline(Bin([A, sub_som, s]), s)["segments"][0]
    ok("⭐ subclipe com ganho: o master é achado DENTRO do efeito",
       (seg["mob_id"], seg["source_start_frames"]), (mid(1), 2010))

    print("\n── efeito embrulhando o clipe ────────────────────────────────")
    fx = TrackEffect(60, [Sequence([Filler(0), SourceClip(mid(1), 7, 60), Filler(0)])],
                     effect_id="EFF2_BLEND_RESIZE")
    t = V([fx])
    s = sequencia_de([t])
    r = S.ler_timeline(Bin([A, s]), s)
    seg = r["segments"][0]
    ok("o clipe dentro do efeito é achado", (seg["clip_name"], seg["source_start_frames"]), ("CAM_A", 7))
    # Desde 2026-09-27 os parâmetros de enquadramento saem da bin (`avb_bin/efeitos.py`,
    # tests/test_efeitos_bin.py). Este efeito de mentira não tem parâmetros: vai reproduzível e
    # vazio — o writer do DRT não escreve transform nenhum para ele.
    ok("o efeito vai para effects[] como enquadramento, com os parâmetros da bin (aqui, nenhum)",
       (seg["effects"][0]["name"], seg["effects"][0]["category"], seg["effects"][0]["params"]),
       ("EFF2_BLEND_RESIZE", "geometric", {}))
    ok("e não sobra o aviso antigo de 'parâmetros ainda não traduzidos'",
       any("não traduzidos" in a["texto"] for a in r["avisos"]), False)

    print("\n── 6. timecode ───────────────────────────────────────────────")
    trilha = V([SourceClip(mid(1), 0, 10)])
    s = sequencia_de([Track(Timecode(90000, 25), 4, "timecode"), Track(Timecode(86400, 24), 1, "timecode"),
                      trilha], fps=23.976)
    r = S.ler_timeline(Bin([A, s]), s)
    ok("⭐ vale a trilha de TC da taxa da sequência (24), não a de 25", r["timeline_start_tc"], "01:00:00:00")
    ok("em frames nominais", r["timeline_start_frames"], 86400)

    print("\n── áudio ─────────────────────────────────────────────────────")
    a2 = Track(Sequence([Filler(0), SourceClip(mid(1), 3, 10, track_id=2, media_kind="sound")],
                        media_kind="sound"), 2, "sound")
    s = sequencia_de([a2])
    seg = S.ler_timeline(Bin([A, s]), s)["segments"][0]
    ok("A2 vira trilha 1001, como no parse_aaf", (seg["track"], seg["is_audio"]), (1001, True))
    ok("o canal do master vai em source_slot_id", seg["source_slot_id"], 2)
    ok("⭐ …e em canal_arquivo, que o writer do DRT prefere ao palpite", seg["canal_arquivo"], 2)

    print("\n── 7. o caminho do arquivo ───────────────────────────────────")
    fisico = Mob(mid(70), "SourceMob", "x.mov",
                 descriptor=Descriptor(Locator(path="", path_utf8="D//MIDIAS DE TESTES/x.mov")))
    ok("⭐ WinFileLocator: D// vira D:/", S.caminho_do_locator(fisico), "D:/MIDIAS DE TESTES/x.mov")
    gerenciado = Mob(mid(71), "SourceMob", "y", descriptor=Descriptor(Locator(path="", path_utf8="")))
    ok("locator VAZIO (mídia gerenciada) → sem caminho", S.caminho_do_locator(gerenciado), "")
    mac = Mob(mid(72), "SourceMob", "z", descriptor=Descriptor(Locator(path_posix="/Volumes/X/z.mov")))
    ok("MacFileLocator: path_posix", S.caminho_do_locator(mac), "/Volumes/X/z.mov")
    AMA = Master(mid(3), "CAM_AMA", fisico=mid(70))
    ok("a cadeia master → mob físico é seguida dentro da bin",
       S.arquivo_na_bin(AMA, {str(m.mob_id): m for m in (AMA, fisico)})[0], "D:/MIDIAS DE TESTES/x.mov")

    tocados: list[str] = []
    exists_real = os.path.exists
    os.path.exists = lambda p: tocados.append(str(p)) or False  # type: ignore[assignment]
    try:
        for unc in ("//atacante/share/x.mov", r"\\atacante\share\x.mov"):
            c, motivo = S.caminho_confiavel(unc)
            ok("⛔ UNC recusado: %s" % unc[:14], (c, "UNC" in motivo), (None, True))
        c, _ = S.caminho_confiavel("../../Windows/x")
        ok("⛔ relativo com '..' recusado", c, None)
        c, _ = S.caminho_confiavel("//h/s/../x")
        ok("⛔ UNC com '..' continua UNC: recusado", c, None)
        # o Premiere grava `..` resolvidos pela metade (55 clipes de áudio do PRODB entravam offline):
        # absoluto com `..` se resolve pelo TEXTO, pela forma, sem tocar no disco.
        # Os caminhos com letra vão a `_resolver_pontos` direto: no Mac, `caminho_confiavel` leva
        # `D:/…` a `_no_disco_desta_maquina` (procura em /Volumes) e, com o disco de mentira, devolve
        # None — o teste escrito no Windows falhava no Mac (medido 2026-10-04, macOS 15.6.1).
        c = S._resolver_pontos("D:/A/B/../C/x.wav")
        ok("absoluto Windows com '..' resolvido pelo texto", c.replace("\\", "/"), "D:/A/C/x.wav")
        c, _ = S.caminho_confiavel("/Users/x/B/../../y/C/z.wav")
        ok("absoluto POSIX com '..' resolvido pelo texto", c.replace("\\", "/"), "/Users/y/C/z.wav")
        c, _ = S.caminho_confiavel("D:/A/../../../x.wav")
        ok("⛔ '..' acima da raiz é recusado (o normpath o engolia)", c, None)
        ok("o separador fica o do original (a mesma mídia, uma grafia só)",
           (S._resolver_pontos("D:/AUDIO/B/../x.wav"), S._resolver_pontos("D:\\AUDIO\\B\\..\\x.wav")),
           ("D:/AUDIO/x.wav", "D:\\AUDIO\\x.wav"))
    finally:
        os.path.exists = exists_real
    ok("⛔ e NADA disso tocou o disco", tocados, [])

    # `/Volumes/<rótulo>/…` (projeto salvo no Mac) lido no Windows — o gêmeo de `_no_disco_desta_maquina`.
    # Pela FORMA, com discos de mentira: roda igual nas duas máquinas (medido no Windows 2026-10-03:
    # PRODB do Mac = F: com o mesmo rótulo).
    from unittest import mock
    vols = {"D": "SSD", "E": "PROJ-X_D", "F": "PRODB", "G": "PRODB"}

    def no(existem):
        return mock.patch("os.path.isfile", lambda p: p in existem)
    alvo = "/Volumes/PRODB/PRODUCAO-B/INPUT/x.mov"
    with no({r"F:\PRODUCAO-B\INPUT\x.mov"}):
        ok("Mac → Windows: o disco de mesmo rótulo", S._no_volume_desta_maquina(alvo, vols), r"F:\PRODUCAO-B\INPUT\x.mov")
    with no({r"F:\PRODUCAO-B\INPUT\x.mov", r"E:\PRODUCAO-B\INPUT\x.mov"}):
        ok("…o rótulo decide entre dois discos que têm o arquivo",
           S._no_volume_desta_maquina(alvo, vols), r"F:\PRODUCAO-B\INPUT\x.mov")
    with no({r"E:\PRODUCAO-B\INPUT\x.mov"}):
        ok("…disco renomeado: vale se só UM disco tem o arquivo",
           S._no_volume_desta_maquina(alvo, vols), r"E:\PRODUCAO-B\INPUT\x.mov")
    with no({r"F:\PRODUCAO-B\INPUT\x.mov", r"G:\PRODUCAO-B\INPUT\x.mov"}):
        ok("⛔ dois discos com o rótulo e o arquivo: ambíguo, sem palpite",
           S._no_volume_desta_maquina(alvo, vols), None)
    with no(set()):
        ok("nenhum disco tem: None", S._no_volume_desta_maquina(alvo, vols), None)
    ok("só o volume, sem arquivo: None", S._no_volume_desta_maquina("/Volumes/PRODB", vols), None)

    print("\n── casamentos (o match_results do writer) ────────────────────")
    trilha = V([SourceClip(mid(1), 0, 10), SourceClip(mid(2), 0, 10)])
    s = sequencia_de([trilha])
    r = S.ler_timeline(Bin([A, B, s]), s)
    mr = S.casamentos(r, {mid(1): "D:/x.mov"})
    ok("só o master com arquivo casa", [(m["segment_index"], m["matched_path"]) for m in mr], [(0, "D:/x.mov")])
    ok("e o media_ref ganha o caminho", r["segments"][0]["media_ref"]["local_path"], "D:/x.mov")

    print("\n── escolher a sequência pelo MobID do arrasto ────────────────")
    outra = Mob(mid(901), "CompositionMob", "OUTRA", [trilha], usage_code=0, edit_rate=25.0, length=20)
    b = Bin([A, B, s, outra])
    api = "060a2b340101010501010d4313-000000-" + ("%08x" % 901) + "1bb20000-060e2b347f7f-2a80"
    ok("a forma da API (hífens) acha a mesma sequência", S.escolher_sequencia(b, api).name, "OUTRA")
    ok("duas sequências e nada pedido → None (não adivinha)", S.escolher_sequencia(b), None)

    print("\n── 9. identidade do original (mídia gerenciada) ──────────────")

    class CDCI:
        def __init__(self, w, h, layout=0, er=23.976):
            self.stored_width, self.stored_height, self.frame_layout, self.edit_rate = w, h, layout, er

    def mob_com(nome, mob_id, filho=None, inicio=0, tc=None, desc=None, kind="picture"):
        trs = []
        if filho is not None:
            trs.append(Track(Sequence([Filler(0), SourceClip(filho, inicio, 100, media_kind=kind),
                                       Filler(0)], media_kind=kind), 1, kind))
        if tc is not None:
            trs.append(Track(Sequence([Filler(0), Timecode(tc[0], tc[1], 10 ** 6)]), 1, "timecode"))
        return Mob(mob_id, "SourceMob", nome, trs, descriptor=desc)

    fita = mob_com("B001_C011", mid(80), tc=(0, 24))
    essencia = mob_com("B001_C011", mid(81), filho=mid(80), inicio=132203, desc=CDCI(2048, 1080))
    cam = Mob(mid(82), "MasterMob", "B001_C011",
              [Track(Sequence([Filler(0), SourceClip(mid(81), 0, 3063), Filler(0)]), 1, "picture")])
    por = {str(m.mob_id): m for m in (fita, essencia, cam)}
    ident = S.identidade_na_bin(cam, por)
    ok("⭐ TC de câmera = início da fita + offset da cadeia", (ident["tc_inicio"], ident["tc_fps"]),
       (132203, 24))
    ok("reel = o nome do arquivo de câmera", ident["reel"], "B001_C011")
    ok("resolução da essência", (ident["largura"], ident["altura"]), (2048, 1080))

    fita_som = mob_com("msmMMOB.02", mid(90), tc=(0, 24), kind="sound")
    ess_som = mob_com("CENA 4-T002", mid(91), filho=mid(90), inicio=1010880, kind="sound")
    som = Mob(mid(92), "MasterMob", "CENA 4-T002",
              [Track(Sequence([SourceClip(mid(91), 0, 500, media_kind="sound")]), 1, "sound")])
    ident = S.identidade_na_bin(som, {str(m.mob_id): m for m in (fita_som, ess_som, som)})
    ok("⭐ som direto: TC da fita (hora do gravador)", ident["tc_inicio"], 1010880)
    ok("⭐ …mas o NOME não é o interno `msmMMOB.02`", ident["reel"], "CENA 4-T002")

    campo = mob_com("x", mid(95), tc=(0, 30), desc=CDCI(1920, 540, layout=1, er=29.97))
    m1080i = Mob(mid(96), "MasterMob", "x",
                 [Track(Sequence([SourceClip(mid(95), 0, 10)]), 1, "picture")])
    ok("entrelaçado: altura de campo vira a do quadro",
       S.identidade_na_bin(m1080i, {str(m.mob_id): m for m in (campo, m1080i)})["altura"], 1080)

    print("\n── 10. a referência offline ──────────────────────────────────")
    info = {"nome": "B001_C011", "duracao_frames": 3063,
            "identidade": {"reel": "B001_C011", "tc_inicio": 132203, "tc_fps": 24, "fps": 23.976,
                           "audio_sr": 48000, "audio_canais": 2}}
    ref, meta = S.referencia_offline(info, r"E:\ENTREGA")
    ok("sem o MC: o reel, na pasta do export", ref, os.path.join(r"E:\ENTREGA", "B001_C011"))
    ok("TC e duração do Avid", (meta["tc"], meta["nb"]), ("01:31:48:11", 3063))
    ref, _ = S.referencia_offline(info, r"E:\ENTREGA", r"F:\CARTAO\A001", r"B001_C011.braw")
    ok("⭐ com o MC: Source Path + Source File (com EXTENSÃO)", ref,
       os.path.join(r"F:\CARTAO\A001", "B001_C011.braw"))
    ref, _ = S.referencia_offline(info, r"E:\X", "", r"\\atacante\share\y.braw")
    ok("Source File vira só o nome", os.path.basename(ref), "y.braw")
    # ⭐ Sem o MC, o AMA da bin sabe o nome COM extensão (caso E06, bin feita no Mac: sem ela o
    # Resolve não reconectava o clipe sozinho quando o autor importava os mesmos arquivos).
    ama = {**info, "nome": "RELINKER_TESTCHART_3840x2160.new.01",
           "caminho_na_bin": "/Volumes/SSD/MAPEAMENTO/RELINKER_TESTCHART_3840x2160.mov",
           "identidade": {**info["identidade"], "reel": "RELINKER_TESTCHART_3840x2160"}}
    ref, _ = S.referencia_offline(ama, r"E:\ENTREGA")
    ok("⭐ sem o MC: o nome do arquivo do AMA, com a extensão, na pasta do export", ref,
       os.path.join(r"E:\ENTREGA", "RELINKER_TESTCHART_3840x2160.mov"))
    ref, _ = S.referencia_offline({**ama, "caminho_na_bin": r"\\atacante\share\z.mov"}, r"E:\X")
    ok("⛔ do caminho da bin vem só o nome, nunca a pasta (V2)", ref, os.path.join(r"E:\X", "z.mov"))
    ref, _ = S.referencia_offline(ama, r"E:\X", "", "B001.braw")
    ok("o Source File do MC continua ganhando do AMA", os.path.basename(ref), "B001.braw")

    print("\n── 11. um original, um clipe — e o In a partir dele ──────────")
    t = V([SourceClip(mid(201), 10, 20), SourceClip(mid(202), 5, 20)])
    tl = sequencia_de([t])
    leitura = {"segments": S.ler_timeline(Bin([Master(mid(201), "A"), Master(mid(202), "B"), tl]),
                                          tl)["segments"],
               "masters": {
                   mid(201): {"nome": "T.01", "duracao_frames": 100, "identidade":
                              {"reel": "FITA1", "tc_inicio": 1000, "tc_fps": 25, "fps": 25.0}},
                   mid(202): {"nome": "T.02", "duracao_frames": 100, "identidade":
                              {"reel": "FITA1", "tc_inicio": 1300, "tc_fps": 25, "fps": 25.0}}}}
    segs, casados, metas = S.montar_offline(leitura, {}, r"E:\X")
    ok("dois masters do mesmo original → UM clipe no pool", len(metas), 1)
    meta = next(iter(metas.values()))
    ok("início = o menor TC; duração cobre os dois", (meta["tc"], meta["nb"]), ("00:00:40:00", 400))
    ok("⭐ o In do 2º desloca pela diferença (300)", segs[1]["source_start_frames"], 305)
    ok("a leitura original não muda", leitura["segments"][1]["source_start_frames"], 5)
    ok("todos marcados offline", [c["offline"] for c in casados], [True, True])

    print("\n── 8. bin real (opcional) ────────────────────────────────────")
    real = os.environ.get("DLPC_BIN_REAL")
    if real and Path(real).is_file():
        from avb_export.reader import topen
        with topen(real) as f:
            for sq in S.sequencias(f):
                rr = S.ler_timeline(f, sq)
                ok("todas as trilhas fecham: %s" % rr["composition_name"][:30], rr["conferencia"], [])
    else:
        print("  PULADO — defina DLPC_BIN_REAL=<caminho de uma .avb> para ler uma bin real")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
