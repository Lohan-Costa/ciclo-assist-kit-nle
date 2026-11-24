"""
O FALLBACK DE SCALER do proxy de vídeo — e a geometria dos dois filtros.

O que estes testes guardam:

  1. `scale_filter` (swscale) e `zscale_filter` (libzimg) mantêm a MESMA semântica
     de geometria: cabem no teto do nível, sem esticar, dimensões pares.
  2. O `_transcode` tenta o swscale PRIMEIRO (rápido, provado) e só cai no zscale
     se ele falhar — a razão de o zscale existir é o swscale RECUSAR certos ProRes
     4444 12-bit 4:4:4 (colorspace não-especificado). Sem esse fallback, o monitor
     caía em "não foi possível exibir este formato" com material que o app até
     sincroniza normalmente.
  3. Se o swscale já dá conta, o zscale NEM é chamado (o caminho comum não paga
     um segundo transcode).
  4. Se OS DOIS falham (arquivo corrompido de verdade), levanta com o rótulo certo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media import proxy


def test_scale_filter_caps_por_nivel():
    # O swscale usa force_original_aspect_ratio=decrease (cabe sem esticar).
    assert "1920" in proxy.scale_filter("full") and "1080" in proxy.scale_filter("full")
    assert "960" in proxy.scale_filter("half") and "540" in proxy.scale_filter("half")
    assert "480" in proxy.scale_filter("quarter")
    assert "force_original_aspect_ratio=decrease" in proxy.scale_filter("full")


def test_zscale_filter_mesma_geometria_e_format():
    z = proxy.zscale_filter("full")
    # Fator ≤1 (nunca amplia) que cabe no teto, dims pares (trunc(...*_/2)*2),
    # e o format=yuv420p DEPOIS do zscale (o frame já tem colorspace definido).
    assert z.startswith("zscale=")
    assert "1920" in z and "1080" in z
    assert "min(1\\," in z  # nunca amplia
    assert z.endswith("format=yuv420p")


def _build_factory(tmp: Path):
    # Comando mínimo: o runner é mockado, só o `-vf` e o tmp (último arg) contam.
    return lambda vf: ["ffmpeg", "-vf", vf, str(tmp)]


# ── _transcode_progress: escolha de scaler pelo croma + cancelamento ──────────
# (é o ÚNICO runner agora — o `window` e o `preview` passam os dois por ele.)


def _fake_progress_runner(*, rcs: list[int]):
    """`_run_progress` falso: devolve os returncodes de `rcs` em ordem (um por
    scaler tentado), escreve o tmp num sucesso (rc==0), e registra o scaler visto."""
    calls: list[str] = []
    seq = iter(rcs)

    def fake_run(cmd, duration_s, on_progress, on_spawn):
        vf = cmd[cmd.index("-vf") + 1]
        calls.append(vf)
        if on_spawn:
            on_spawn(4242)
        rc = next(seq)
        if rc == 0:
            Path(cmd[-1]).write_bytes(b"\x00\x01")
            if on_progress:
                on_progress(1.0)
        return rc, "err"

    return fake_run, calls


def test_progress_444_usa_so_zscale(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy.cachedir, "maybe_enforce", lambda: None)
    fake_run, calls = _fake_progress_runner(rcs=[0])
    monkeypatch.setattr(proxy, "_run_progress", fake_run)

    out, tmp = tmp_path / "o.mp4", tmp_path / "o.part.mp4"
    res = proxy._transcode_progress(
        _build_factory(tmp), "full", tmp, out, Path("/x.mov"), 10.0, "4:4:4", None, None
    )
    # 4:4:4 pula o swscale (ele recusa): um scaler só, zscale.
    assert res == out and len(calls) == 1 and calls[0].startswith("zscale=")


def test_progress_nao444_swscale_depois_zscale(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy.cachedir, "maybe_enforce", lambda: None)
    fake_run, calls = _fake_progress_runner(rcs=[1, 0])  # swscale falha, zscale ok
    monkeypatch.setattr(proxy, "_run_progress", fake_run)

    out, tmp = tmp_path / "o.mp4", tmp_path / "o.part.mp4"
    res = proxy._transcode_progress(
        _build_factory(tmp), "full", tmp, out, Path("/x.mov"), 10.0, "4:2:2", None, None
    )
    assert res == out and len(calls) == 2
    assert calls[0].startswith("scale=") and calls[1].startswith("zscale=")


def test_progress_cancel_rc_negativo_nao_faz_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy.cachedir, "maybe_enforce", lambda: None)
    # swscale MORTO por sinal (rc<0 = preview_cancel) → NÃO cai no zscale.
    fake_run, calls = _fake_progress_runner(rcs=[-9, 0])
    monkeypatch.setattr(proxy, "_run_progress", fake_run)

    out, tmp = tmp_path / "o.mp4", tmp_path / "o.part.mp4"
    with pytest.raises(RuntimeError):
        proxy._transcode_progress(
            _build_factory(tmp), "full", tmp, out, Path("/x.mov"), 10.0, "4:2:2", None, None
        )
    assert len(calls) == 1 and not out.exists()  # parou no 1º; não rodou o zscale


def test_progress_encaminha_fracao_e_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy.cachedir, "maybe_enforce", lambda: None)
    fake_run, _ = _fake_progress_runner(rcs=[0])
    monkeypatch.setattr(proxy, "_run_progress", fake_run)

    fracs, pids = [], []
    out, tmp = tmp_path / "o.mp4", tmp_path / "o.part.mp4"
    proxy._transcode_progress(
        _build_factory(tmp), "full", tmp, out, Path("/x.mov"), 10.0, "4:4:4",
        fracs.append, pids.append,
    )
    assert fracs == [1.0] and pids == [4242]
