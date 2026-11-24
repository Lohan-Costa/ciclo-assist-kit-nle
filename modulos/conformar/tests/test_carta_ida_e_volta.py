"""Carta Aberta SEM PERDAS: o DRT que sai da Carta é o DRT que sai da bin.

Rodar:

    .venv-win/Scripts/python tests/test_carta_ida_e_volta.py

⭐ O critério do autor é *"nada deve ser perdido na carta aberta"*. Ele é medido na entrada
INTEIRA do writer do DRT — o que `montar_midia` devolve (segmentos, casamentos, metadados
offline) —, porque é ela que decide o arquivo: duas entradas iguais dão o mesmo DRT.

    bin ──ler_timeline──► leitura ──montar_midia──► A
                             └──Carta (JSON em disco)──ler_carta──montar_midia──► B      A ≡ B

Cobre os três caminhos de mídia (gerenciada por essência, AMA, referência offline com o
deslocamento do In de masters do mesmo original), vazio, transição e velocidade — e a Carta
como texto de terceiro (teto, versão, forma, e nenhum caminho de dentro dela tocado no disco).

Se `DLPC_BIN_REAL` apontar para uma ou mais `.avb` (separadas por `;`), toda sequência delas
passa pela mesma ida e volta, com a mídia gerenciada DESTA máquina. Sem ela, essa parte é
PULADA (e o teste sai 0).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import segmentos as S  # noqa: E402
from carta_aberta.reader import CartaInvalida, ler_carta  # noqa: E402
from carta_aberta.writer import build_carta_aberta, montar  # noqa: E402

URN = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.{:08x}.1bb20000.060e2b34.7f7f2a80"
ESS = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.{:08x}.00000000.00000000.00000000"


def mid(n: int) -> str:
    return URN.format(n)


def seg(track, tc_in, tc_out, dur, mob=None, **extra):
    base = {"timeline_tc_in": tc_in, "timeline_tc_out": tc_out, "duration_frames": dur,
            "source_start_frames": extra.pop("src", 0), "source_fps": 25.0,
            "clip_name": extra.pop("nome", "(gap)" if mob is None else "CLIPE"),
            "track": track, "mob_id": mob, "source_slot_id": extra.pop("slot", 1),
            "media_ref": None if mob is None else {
                "mob_name": "M", "url": "", "local_path": "", "descriptor_type": "",
                "source_duration_frames": 500, "source_duration_secs": 20.0, "source_fps": 25.0},
            "is_gap": mob is None and not extra.get("is_transition"),
            "is_transition": False, "is_effect": False, "is_audio": track >= 1000,
            "cutpoint": None, "has_motion_effect": False, "speed_ratio": 1.0,
            "source_offset_map": None, "speed_curve": None, "effects": [], "disabled": False}
    base.update(extra)
    return base


def leitura_sintetica() -> dict:
    """Uma timeline pequena que passa por TODOS os ramos de `montar_midia`."""
    masters = {
        # gerenciada: imagem e dois canais de som, cada um na sua .mxf
        mid(1): {"nome": "A001_C002", "caminho_na_bin": "", "descritor": "CDCIDescriptor",
                 "fps": 25.0, "duracao_frames": 500,
                 "identidade": {"reel": "A001_C002", "tc_inicio": 90000, "tc_fps": 25, "fps": 25.0,
                                "largura": 1920, "altura": 1080, "audio_sr": 48000, "audio_canais": 2},
                 "essencias": {"picture:1": ESS.format(11), "sound:1": ESS.format(12),
                               "sound:2": ESS.format(13)}},
        # AMA: arquivo linkado
        mid(2): {"nome": "B001_C011", "caminho_na_bin": "D:/RODAGEM/B001_C011.mov",
                 "descritor": "", "fps": 25.0, "duracao_frames": 400,
                 "identidade": {"reel": "B001_C011", "tc_inicio": 36000, "tc_fps": 25, "fps": 25.0},
                 "essencias": {}},
        # offline: DOIS masters do MESMO original (o In do 2º desloca 300 frames)
        mid(3): {"nome": "T.01", "caminho_na_bin": "", "descritor": "", "fps": 25.0,
                 "duracao_frames": 100, "essencias": {},
                 "identidade": {"reel": "FITA1", "tc_inicio": 1000, "tc_fps": 25, "fps": 25.0,
                                "audio_sr": 48000, "audio_canais": 1},
                 "colunas_mc": {"Source File": "FITA1.MXF", "Source Path": "", "Tape": ""}},
        mid(4): {"nome": "T.02", "caminho_na_bin": "", "descritor": "", "fps": 25.0,
                 "duracao_frames": 100, "essencias": {},
                 "identidade": {"reel": "FITA1", "tc_inicio": 1300, "tc_fps": 25, "fps": 25.0},
                 "colunas_mc": {"Source File": "FITA1.MXF", "Source Path": "", "Tape": ""}},
    }
    segments = [
        seg(1, "00:00:00:00", "00:00:02:00", 50, mid(1), src=10, nome="A001_C002"),
        seg(1, "00:00:02:00", "00:00:04:00", 50, mid(2), src=5, nome="B001_C011",
            has_motion_effect=True, speed_ratio=1.1617, motion_effect_type="TimeWarp",
            source_offset_map=[[0, 0], [49, 42]]),
        seg(1, "00:00:03:20", "00:00:04:00", 5, None, is_transition=True, cutpoint=3,
            clip_name="(transition)"),
        seg(1, "00:00:04:00", "00:00:05:00", 25, None),
        seg(1, "00:00:05:00", "00:00:06:00", 25, mid(3), src=5, nome="T.01"),
        seg(1, "00:00:06:00", "00:00:07:00", 25, mid(4), src=5, nome="T.02"),
        seg(1000, "00:00:00:00", "00:00:02:00", 50, mid(1), src=10, slot=1, canal_arquivo=1),
        seg(1001, "00:00:00:00", "00:00:02:00", 50, mid(1), src=10, slot=2, canal_arquivo=2),
    ]
    return {"segments": segments, "timeline_fps": 25.0, "total_segments": len(segments),
            "has_nested_scope": False, "composition_name": "SINTETICA",
            "sequence_mob_id": mid(99), "timeline_start_frames": 90000,
            "timeline_drop_frame": False, "timeline_start_tc": "01:00:00:00", "markers": [],
            "masters": masters, "avisos": [{"texto": "efeito não traduzido", "vezes": 1}],
            "conferencia": [], "fonte": "avb"}


def normal(x):
    """Tuplas viram listas, como no JSON — para comparar o que o writer do DRT recebe."""
    return json.loads(json.dumps(x, ensure_ascii=False, sort_keys=True))


def ida_e_volta(leitura: dict, arquivos: dict, gerenciados: dict, colunas: dict,
                pasta: str, pasta_carta: Path, **extras):
    """(A: direto da leitura, B: passando pela Carta em disco, a Carta lida)."""
    direto = S.montar_midia(leitura, arquivos, pasta, colunas, gerenciados)
    saida = pasta_carta / "carta.json"
    build_carta_aberta(leitura, direto[1], str(saida), "NOME", "comentário",
                       arquivos=arquivos, gerenciados=gerenciados, **extras)
    carta = ler_carta(saida)
    pela_carta = S.montar_midia(carta.resultado, carta.arquivos, pasta, carta.colunas_por_mob,
                                carta.gerenciados)
    return direto, pela_carta, carta


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    def iguais(rotulo, a, b):
        """Compara as três partes de `montar_midia` e aponta a PRIMEIRA diferença."""
        for parte, x, y in zip(("segmentos", "casamentos", "metadados offline"), a, b):
            nx, ny = normal(x), normal(y)
            if nx == ny:
                ok(f"{rotulo}: {parte} iguais", True, True)
                continue
            onde = "?"
            if isinstance(nx, list) and isinstance(ny, list):
                for i, (p, q) in enumerate(zip(nx, ny)):
                    if p != q:
                        chaves = sorted(k for k in set(p) | set(q) if p.get(k) != q.get(k)) \
                            if isinstance(p, dict) and isinstance(q, dict) else "valor"
                        onde = f"item {i}: {chaves}"
                        break
                else:
                    onde = f"tamanhos {len(nx)} × {len(ny)}"
            ok(f"{rotulo}: {parte} iguais", onde, True)

    pasta_ref = r"E:\ENTREGA"
    gerenciados = {ESS.format(11): r"D:\Avid MediaFiles\MXF\1\A001_C002_V.mxf",
                   ESS.format(12): r"D:\Avid MediaFiles\MXF\1\A001_C002_A01.mxf",
                   ESS.format(13): r"D:\Avid MediaFiles\MXF\1\A001_C002_A02.mxf"}
    arquivos = {mid(2): "D:/RODAGEM/B001_C011.mov"}

    print("── 1. ida e volta: timeline sintética com os três caminhos de mídia ──")
    with tempfile.TemporaryDirectory() as tmp:
        leitura = leitura_sintetica()
        colunas = {k: m.get("colunas_mc") or {} for k, m in leitura["masters"].items()}
        a, b, carta = ida_e_volta(leitura, arquivos, gerenciados, colunas, pasta_ref, Path(tmp))
        iguais("sintética", a, b)
        ok("a leitura não foi alterada pela ida", leitura == leitura_sintetica(), True)
        segs, casados, metas = a
        ok("sanidade: a imagem gerenciada caiu na .mxf da imagem",
           casados[0]["matched_path"], gerenciados[ESS.format(11)])
        ok("sanidade: o canal 2 de som caiu na _A02", [c["matched_path"] for c in casados
                                                     if c["segment_index"] == 7], [gerenciados[ESS.format(13)]])
        ok("sanidade: dois masters do mesmo original → um clipe offline", len(metas), 1)
        ok("sanidade: o In do 2º master deslocou 300", segs[5]["source_start_frames"], 305)
        ok("a Carta devolve o que o remetente resolveu",
           (carta.arquivos, carta.gerenciados), (arquivos, gerenciados))
        ok("versão 1.2", carta.versao, "1.2")
        ok("sem 'envio', o tipo é timeline", carta.tipo, "timeline")

    print("\n── 2. o envio e a seleção do insert viajam ──")
    with tempfile.TemporaryDirectory() as tmp:
        envio = {"id": "a1b2c3d4-0000-4000-8000-000000000000", "tipo": "insert_vfx",
                 "remetente": {"maquina": "EDIT-02", "usuario": "editor"},
                 "enviado_em": "2026-09-24T16:40:12-03:00"}
        selecao = [{"track": 1, "timeline_tc_in": "00:00:02:00", "timeline_tc_out": "00:00:04:00",
                    "mob_id": mid(2)}]
        _a, _b, carta = ida_e_volta(leitura_sintetica(), arquivos, gerenciados, {}, pasta_ref,
                                    Path(tmp), envio=envio, selecao=selecao)
        ok("tipo do envio", carta.tipo, "insert_vfx")
        ok("o envio volta igual", carta.envio, envio)
        ok("a seleção volta igual", carta.selecao, selecao)
        try:
            montar(leitura_sintetica(), [], "X", envio={"tipo": "insert_audio"})
            ok("tipo de envio inventado é recusado ao ESCREVER", "aceitou", "recusou")
        except ValueError:
            ok("tipo de envio inventado é recusado ao ESCREVER", "recusou", "recusou")

    print("\n── 3. a Carta é texto de terceiro ──")
    with tempfile.TemporaryDirectory() as tmp:
        base = montar(leitura_sintetica(), [], "X", arquivos=arquivos, gerenciados=gerenciados)

        def recusa(rotulo, doc_ou_caminho, trecho, **kw):
            try:
                ler_carta(doc_ou_caminho, **kw)
                ok(rotulo, "aceitou", f"recusou ({trecho})")
            except CartaInvalida as e:
                ok(rotulo, "recusou" if trecho in str(e) else f"recusou por outro motivo: {e}",
                   "recusou")

        recusa("versão 2.x é recusada", {**base, "carta_aberta": "2.0"}, "versão")
        recusa("versão 1.0 (sem bloco avid) é recusada com o motivo", {**base, "carta_aberta": "1.0"},
               "gere de novo")
        recusa("sem taxa de timeline", {**base, "tempo": {}}, "taxa")
        recusa("segmentos que não são lista", {**base, "segmentos": "x"}, "segmentos")
        sem_avid = json.loads(json.dumps(base))
        del sem_avid["masters"][0]["avid"]
        recusa("master sem o bloco avid", sem_avid, "avid")
        recusa("tipo de envio inventado", {**base, "envio": {"tipo": "rm -rf"}}, "tipo de envio")
        p = Path(tmp) / "grande.json"
        p.write_text(json.dumps(base), encoding="utf-8")
        recusa("acima do teto de tamanho", p, "limite", limite_bytes=100)
        (Path(tmp) / "lixo.json").write_bytes(b"\xff\xfe nao e json")
        recusa("arquivo que não é JSON", Path(tmp) / "lixo.json", "JSON")

        # ⛔ Nenhum caminho de DENTRO da Carta pode ser tocado: um UNC vira sessão SMB.
        hostil = json.loads(json.dumps(base))
        hostil["masters"][1]["arquivo_ama"] = r"\\host-do-atacante\c$\x.mov"
        tocados = []
        real_exists, real_stat = os.path.exists, os.stat

        def espiao_exists(caminho):
            tocados.append(str(caminho))
            return real_exists(caminho)

        def espiao_stat(caminho, *a, **k):
            tocados.append(str(caminho))
            return real_stat(caminho, *a, **k)

        with mock.patch("os.path.exists", espiao_exists), mock.patch("os.stat", espiao_stat):
            c = ler_carta(hostil)
        ok("UNC de dentro da Carta volta como TEXTO", c.arquivos.get(mid(2)), r"\\host-do-atacante\c$\x.mov")
        ok("⛔ e nenhum caminho da Carta foi tocado no disco",
           [t for t in tocados if "atacante" in t], [])

    print("\n── 4. bins reais (opcional) ─────────────────────────────────────")
    reais = [p for p in (os.environ.get("DLPC_BIN_REAL") or "").split(";") if p.strip()]
    if not reais:
        print("  PULADO — defina DLPC_BIN_REAL=<.avb>[;<.avb>…] para passar bins reais")
    else:
        from avb_export.reader import topen

        # ⛔ Nunca a mídia da máquina inteira (regra do autor, 2026-10-04: um projeto não acha mídia
        # de outro). A bin real diz de que caso ela é (`DLPC_CASO=<grupo>/<caso>`, o `caso.json`); sem
        # isso, a ida e volta roda SEM mídia — ela vale do mesmo jeito.
        import contextlib

        import casos as ilhas
        caso = ilhas.carregar(os.environ["DLPC_CASO"]) if os.environ.get("DLPC_CASO") else None
        isolar = ilhas.isolar_midia(caso) if caso else contextlib.nullcontext()
        with isolar:
            from media import pmr
            gerenciados_reais = (pmr.indice_de(pmr.raizes_de_midia()).por_arquivo or {}) if caso else {}
        print(f"  mídia gerenciada do caso: {len(gerenciados_reais)} essências"
              + ("" if caso else " (sem DLPC_CASO: nenhuma busca na máquina)"))
        for caminho in reais:
            with topen(caminho.strip()) as f:
                leituras = [S.ler_timeline(f, sq) for sq in S.sequencias(f)]
            for leitura in leituras:
                arq = {}
                for chave, m in leitura["masters"].items():
                    if not caso:
                        break                         # sem caso declarado, sem mídia
                    with ilhas.isolar_midia(caso):
                        c, _motivo = S.caminho_confiavel(m.get("caminho_na_bin") or "")
                    if c and os.path.isfile(c):
                        arq[chave] = c
                with tempfile.TemporaryDirectory() as tmp:
                    a, b, _carta = ida_e_volta(leitura, arq, gerenciados_reais, {}, tmp, Path(tmp))
                nome = leitura["composition_name"][:28]
                print(f"  · {nome}: {len(leitura['segments'])} segmentos, "
                      f"{len(a[1])} com arquivo ({sum(1 for c in a[1] if c.get('gerenciada'))} "
                      f"gerenciados, {sum(1 for c in a[1] if c.get('offline'))} offline)")
                iguais(nome, a, b)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
