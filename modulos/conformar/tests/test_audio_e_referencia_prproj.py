"""Premiere → Resolve: o ÁUDIO do corte e o VÍDEO DE REFERÊNCIA (organograma, 2026-10-04).

Rodar:

    .venv/bin/python tests/test_audio_e_referencia_prproj.py     (Windows: .venv-win/Scripts/python)

- A referência achada na timeline (trilha de vídeo mais alta, um clipe de vídeo de ponta a ponta;
  imagem parada não conta) e as opções do som dela: A = trilha nova abaixo de todo o áudio, com
  solo; B = só o som da referência; nenhum. Com segmentos de mentira: roda em qualquer máquina.
- O áudio do PRODB inteiro (2.536 clipes no Premiere): só com o disco `PRODB` montado; sem
  ele, essa parte é PULADA.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from prproj.leitura import _referencia_na_timeline  # noqa: E402
from tools.prproj_para_drt import _referencia  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def seg(trilha, ini, dur, arquivo, audio=False, canal=1):
    return {"timeline_tc_in": f"00:00:{ini // 24:02d}:{ini % 24:02d}", "duration_frames": dur,
            "track": trilha, "is_audio": audio, "is_gap": False, "is_transition": False,
            "is_effect": False, "canal_arquivo": canal, "clip_name": os.path.basename(arquivo),
            "media_ref": {"local_path": arquivo}}


def timeline(com_ref=True, ref="/x/REF.mp4"):
    s = [seg(1, 0, 100, "/x/A001.mxf"), seg(1, 100, 140, "/x/A002.mxf"),
         seg(2, 0, 240, "/x/MASCARA_185.png"),
         seg(1000, 0, 240, "/x/SOM.wav", audio=True), seg(1001, 0, 240, "/x/SOM.wav", audio=True, canal=2)]
    if com_ref:
        s += [seg(3, 0, 240, ref), seg(1002, 0, 240, ref, audio=True),
              seg(1003, 0, 240, ref, audio=True, canal=2)]
    return s


def main() -> int:
    print("── a referência achada na timeline ──")
    s = timeline()
    r = _referencia_na_timeline(s, 24)
    ok("a trilha mais alta com UM vídeo de ponta a ponta é a referência", (r or {}).get("track"), 3)
    ok("ela entra desligada", r.get("trilha_desligada"), True)
    ok("o som do mesmo arquivo também é da referência",
       sorted(x["track"] for x in s if x.get("is_audio") and x.get("referencia")), [1002, 1003])
    s = timeline(com_ref=False)
    ok("a máscara 1.85 (imagem parada) na trilha de cima NÃO é referência",
       _referencia_na_timeline(s, 24), None)
    s = timeline()
    s[5]["duration_frames"] = 120                 # não vai até o fim
    ok("um clipe que não cobre a timeline inteira não é referência", _referencia_na_timeline(s, 24), None)
    s = timeline()
    s[5]["timeline_tc_in"] = "00:00:00:02"        # 2 quadros de folga
    ok("± 2 quadros de folga ainda vale", (_referencia_na_timeline(s, 24) or {}).get("track"), 3)

    print("── o som da referência ──")
    s = timeline()
    _referencia_na_timeline(s, 24)
    a = _referencia(s, None, "A", 24.0, 24)
    som = sorted((x["track"], x.get("solo")) for x in a if x.get("is_audio") and x.get("referencia"))
    ok("A: o som da referência vai para trilhas NOVAS abaixo de todo o áudio, com solo",
       som, [(1002, True), (1003, True)])
    ok("A: o áudio da timeline fica intacto",
       sorted(x["track"] for x in a if x.get("is_audio") and not x.get("referencia")), [1000, 1001])
    s = timeline()
    _referencia_na_timeline(s, 24)
    b = _referencia(s, None, "B", 24.0, 24)
    ok("B: SÓ o som da referência, a partir da A1",
       sorted((x["track"], x["media_ref"]["local_path"]) for x in b if x.get("is_audio")),
       [(1000, "/x/REF.mp4"), (1001, "/x/REF.mp4")])
    s = timeline()
    _referencia_na_timeline(s, 24)
    n = _referencia(s, None, None, 24.0, 24)
    ok("nenhum: o som da referência sai, o resto fica",
       sorted(x["track"] for x in n if x.get("is_audio")), [1000, 1001])
    ok("o vídeo da referência continua, desligado",
       [(x["track"], x.get("trilha_desligada")) for x in n if x.get("referencia")], [(3, True)])

    print("── o volume do clipe ──")
    from drp.writer import _volume_ba
    ok("o filtro de volume é byte a byte o que o Resolve 21.1 exporta (−6 dB)",
       _volume_ba(-6.0), "000000020000001e800a1b087c4a0f085f1a0b0a091100000000000018c04a004a004a004a00")
    ok("+3,5 dB também", _volume_ba(3.5).endswith("0000000000000c404a004a004a004a00"), True)
    import math
    ok("Premiere: Level 0,177828 = 0 dB e 1,0 = +15 dB (dB = 20·log10(v) + 15)",
       (round(20 * math.log10(0.177827939391) + 15, 3), round(20 * math.log10(1.0) + 15, 3)), (0.0, 15.0))

    print("── o solo na trilha (som da referência, A) ──")
    import re
    import tempfile
    import zipfile

    from drp.writer import build_drt
    # Os caminhos do filme vêm do manifesto do caso R03 (regra de 2026-10-04: cada caso é uma ilha)
    import casos as ilhas
    filme = ilhas.carregar("REAL/R03 PRODB FILME") or {"arquivo": {}}
    wav = str(filme["arquivo"].get("wav_amostra") or "")
    if not wav or not os.path.isfile(wav):
        print("  o disco PRODB não está montado — PULADO")
    else:
        def a_(tr, solo):
            return {**seg(tr, 0, 48, wav, audio=True), "timeline_tc_out": "00:00:02:00",
                    "source_start_frames": 0, "source_fps": 24.0, "speed_ratio": 1.0,
                    "relative_speed": 1.0, "conform_ratio": 1.0, "effects": [], "solo": solo}
        with tempfile.TemporaryDirectory() as tmp:
            drt = os.path.join(tmp, "solo.drt")
            build_drt([a_(1000, False), a_(1001, True)],
                      [{"segment_index": 0, "matched_path": wav}, {"segment_index": 1, "matched_path": wav}],
                      drt, timeline_name="solo", timeline_fps=24.0, timeline_size=(1920, 1080))
            with zipfile.ZipFile(drt) as z:
                seq = next(z.read(n).decode("utf-8", "replace") for n in z.namelist() if "SeqContainer" in n)
        atv = re.search(r"<AudioTrackVec>.*?</AudioTrackVec>", seq, re.S).group(0)
        flags = [re.search(r"<Flags>(\d+)</Flags>", re.sub(r"<Items>.*?</Items>", "", t, flags=re.S)).group(1)
                 for t in re.findall(r"<Sm2TiTrack\b.*?</Sm2TiTrack>", atv, re.S)]
        ok("a trilha com solo leva <Flags>32 (medido no Resolve 21.1); a outra fica 0", flags, ["0", "32"])

        print("── a mesa do Fairlight com mais de 16 trilhas ──")
        import struct
        import zlib
        with tempfile.TemporaryDirectory() as tmp:
            drt = os.path.join(tmp, "m.drt")
            build_drt([a_(1000 + k, False) for k in range(20)],
                      [{"segment_index": k, "matched_path": wav} for k in range(20)],
                      drt, timeline_name="m", timeline_fps=24.0, timeline_size=(1920, 1080))
            with zipfile.ZipFile(drt) as z:
                mp = next(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("MediaPool"))
        seq = re.search(r"<Sm2Sequence\b.*?</Sm2Sequence>", mp, re.S).group(0)
        blob = bytes.fromhex(re.findall(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", seq)[0])
        k = "FLStudioModelBA".encode("utf-16-be")
        j = blob.find(k) + len(k)
        n = struct.unpack(">I", blob[j + 5:j + 9])[0]
        mesa = blob[j + 9:j + 9 + n]
        ok("20 trilhas de áudio: o DRT leva a mesa de 99 (todas no Bus 1), não a de 16 do esqueleto",
           mesa == open(RAIZ / "motor" / "drp" / "fairlight_r19_mesa99.bin", "rb").read(), True)
        ok("a mesa de 99 descomprime (qCompress: tamanho + zlib)",
           len(zlib.decompress(mesa[4:])) == struct.unpack(">I", mesa[:4])[0], True)

    print("── o áudio do PRODB ──")
    prproj = str(filme["arquivo"].get("prproj_corte") or "")
    from avb_bin.segmentos import caminho_confiavel   # como o app: o caminho do Mac vira a letra no Windows
    if os.name == "nt":
        prproj = caminho_confiavel(prproj)[0] or prproj
    if not os.path.isfile(prproj):
        print("  o disco PRODB não está montado — PULADO")
    else:
        from prproj.leitura import Leitor
        from prproj.projeto import Projeto
        r = Leitor(Projeto(prproj)).ler("DU_CORTE_06 SIMPLIFICADA")
        au = [x for x in r["segmentos"] if x.get("is_audio") and not x["is_gap"] and not x["is_transition"]]
        ok("todo clipe de áudio desce até um arquivo que existe (nomes com & desescapados)",
           sum(1 for x in au if not os.path.isfile(caminho_confiavel(x["media_ref"]["local_path"])[0] or "")), 0)
        ok("os estéreo viram dois mono: 2.536 clipes do Premiere → mais clipes no Resolve", len(au) > 2536, True)
        ok("as trilhas de áudio são 1000+ (a convenção do writer)", min(x["track"] for x in au), 1000)
        ok("os clipes desligados entram desligados", any(x["disabled"] for x in au), True)
        vols = [x["volume_db"] for x in au if x.get("volume_db") is not None]
        ok("volumes fixos traduzidos (dB), nenhum fora do que o Premiere permite (≤ +15)",
           (len(vols) > 500, max(vols) <= 15.0), (True, True))
        ok("o PRODB não tem referência na timeline (a V5 é a máscara 1.85)",
           any(x.get("referencia") for x in r["segmentos"]), False)

    print("── volume do clipe com keyframes ──")
    from unittest import mock

    from prproj import leitura as LT

    class _P:
        """Só o que `_volume_db` consulta: o parâmetro Level com (ou sem) Keyframes."""
        def __init__(self, kf, valor="0.177828"):
            self.kf, self.valor = kf, valor
        def refs(self, comp, tag):
            return ["Level"]
        def campo(self, prm, nome):
            return {"Name": "Level", "Keyframes": self.kf, "StartKeyframe": None}.get(nome)
    with mock.patch.object(LT, "_valor", lambda p, prm, d: (p.valor, None)):
        av = {}
        # UM keyframe (o PRODB tem 3): 0,316228 = 10^(−10/20) → −10 + 15 = +5 dB, o clipe todo
        ok("um keyframe só é volume FIXO: vira o dB dele", LT._volume_db(_P("25867296000000,0.316227763891,0,0,0,0.1666,0,0.1666;"), None, av), 5.0)
        ok("…sem aviso de keyframes", av, {})
        av = {}
        dois = "0,0.316227763891,0,0,0,0.16,0,0.16;254016000000,0.177828,0,0,0,0.16,0,0.16;"
        ok("dois ou mais: não é volume fixo (vão por _volume_kf), sem aviso", (LT._volume_db(_P(dois), None, av), sum(av.values())), (None, 0))
        ok("…e _volume_kf os lê em (ticks da mídia, dB)", LT._volume_kf(_P(dois), None), [(0, 5.0), (254016000000, 0.0)])
        ok("sem keyframes: o Level fixo, como antes", LT._volume_db(_P(None, "0.354813"), None, {}), 6.0)
        av = {}
        ok("keyframe sem vírgula não derruba a leitura: vale o Level fixo, com aviso",
           (LT._volume_db(_P("25867296000000;", "0.354813"), None, av), sum(av.values())), (6.0, 1))
        ok("uma válida + uma malformada = UMA keyframe: volume fixo dela (não some calado)",
           LT._volume_db(_P("0,0.316227763891;junk,abc;"), None, {}), 5.0)

    # A curva AVALIADA no trecho do clipe (tempos em quadros da timeline; tpf_tl = 1 por simplicidade)
    kf = [(100, 0.0), (110, -10.0)]                       # 0 dB → −10 dB entre os quadros 100 e 110
    f = {"src_in": 0, "vel": 1.0}
    ok("pedaço de lâmina ANTES das keyframes: volume fixo = o da 1ª (0 dB → nenhum)",
       LT._volume_no_trecho(None, kf, f, 0, 50, 1.0, {}), {"volume_db": None, "volume_kf": []})
    ok("pedaço DEPOIS das keyframes: volume fixo = o da última",
       LT._volume_no_trecho(None, kf, {"src_in": 200, "vel": 1.0}, 0, 50, 1.0, {}),
       {"volume_db": -10.0, "volume_kf": []})
    r = LT._volume_no_trecho(None, kf, {"src_in": 90, "vel": 1.0}, 0, 40, 1.0, {})
    ok("pedaço que cruza a rampa: as pontas + as keyframes de dentro, no domínio do In",
       [q for q, _d in r["volume_kf"]], [90, 100, 110, 129])
    ok("…com os valores das pontas avaliados (antes = 0 dB, depois = −10 dB)",
       (r["volume_kf"][0][1], r["volume_kf"][-1][1]), (0.0, -10.0))
    r = LT._volume_no_trecho(None, kf, {"src_in": 100, "vel": 0.5}, 0, 40, 1.0, {})
    ok("com velocidade 50%: o tempo da keyframe dobra (fonte × speed_ratio, como o In)",
       [q for q, _d in r["volume_kf"]][:2], [200, 220])
    av = {}
    ok("take aninhado: não traduzido, com aviso",
       (LT._volume_no_trecho(None, kf, {"src_in": 0, "vel": 1.0, "pos": 0}, 0, 50, 1.0, av)["volume_kf"],
        sum(av.values())), ([], 1))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
