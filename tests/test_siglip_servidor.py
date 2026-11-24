"""O servidor de vetores do Mac (`servidor_mac/siglip_servidor.py`), sem modelo nenhum.

⭐ O modelo real só roda no Mac. Aqui o codificador é FALSO, e o que se confere é o contrato
que o notebook vai usar: rotas exatas, limites, formato dos vetores e a receita — o que, se
mudar calado, deixa o índice do notebook comparando vetores de modelos diferentes.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "siglip_servidor",
    Path(__file__).resolve().parents[1] / "servidor_mac" / "siglip_servidor.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

JPEG = b"\xff\xd8\xff\xe0falso"


class Falso:
    """Vetor determinístico por conteúdo: o mesmo quadro dá o mesmo vetor."""

    def __init__(self):
        self.chamadas = []

    def _vetor(self, semente: bytes):
        rng = np.random.default_rng(int.from_bytes(semente[-4:].rjust(4, b"\0"), "little"))
        v = rng.normal(size=S.DIM).astype(np.float32)
        return v / np.linalg.norm(v)

    def imagens(self, jpegs):
        self.chamadas.append(("imagens", len(jpegs)))
        return np.stack([self._vetor(j) for j in jpegs])

    def frases(self, frases):
        self.chamadas.append(("frases", frases))
        return np.stack([self._vetor(f.encode()) for f in frases])


@pytest.fixture
def servidor():
    falso = Falso()
    srv = S.Servidor(("127.0.0.1", 0), S.fabricar_manipulador(falso))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", falso
    srv.shutdown()
    srv.server_close()


def pedir(url, caminho, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url + caminho, data=dados, method="POST" if dados else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def vetores(resposta):
    return np.frombuffer(base64.b64decode(resposta["vetores"]), dtype="<f4").reshape(
        resposta["quantos"], resposta["dim"])


def test_saude_diz_a_receita(servidor):
    url, _ = servidor
    status, r = pedir(url, "/saude")
    assert status == 200 and r["ok"]
    assert r["receita"]["dim"] == 768 and r["receita"]["normalizado"] is True
    assert r["receita"]["modelo"] == "onnx-community/siglip2-base-patch16-256-ONNX"


def test_imagens_viram_vetores_normalizados(servidor):
    url, _ = servidor
    b64 = base64.b64encode(JPEG + b"A").decode()
    status, r = pedir(url, "/imagens", {"imagens": [b64, base64.b64encode(JPEG + b"B").decode()]})
    assert status == 200
    v = vetores(r)
    assert v.shape == (2, 768)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0, atol=1e-5)


def test_frases_viram_vetores(servidor):
    url, falso = servidor
    status, r = pedir(url, "/frases", {"frases": ["  close noturno  ", "praia"]})
    assert status == 200 and vetores(r).shape == (2, 768)
    assert falso.chamadas[-1] == ("frases", ["close noturno", "praia"])


@pytest.mark.parametrize("corpo, trecho", [
    ({"imagens": []}, "lista"),
    ({"imagens": ["@@@"]}, "base64"),
    ({"imagens": [base64.b64encode(b"PNG...").decode()]}, "JPEG"),
    ({"imagens": [base64.b64encode(JPEG).decode()] * (S.MAX_IMAGENS + 1)}, "no máximo"),
    ({"frases": [""]}, "caracteres"),
    ({"frases": ["x" * (S.MAX_CHARS_FRASE + 1)]}, "caracteres"),
])
def test_pedido_ruim_e_400_com_a_frase(servidor, corpo, trecho):
    url, falso = servidor
    caminho = "/imagens" if "imagens" in corpo else "/frases"
    status, r = pedir(url, caminho, corpo)
    assert status == 400 and trecho in r["erro"]
    assert not falso.chamadas, "pedido ruim não pode chegar ao modelo"


def test_rota_e_caminho_exato(servidor):
    url, _ = servidor
    assert pedir(url, "/imagensX", {"imagens": ["x"]})[0] == 404
    assert pedir(url, "/saude/x")[0] == 404


def test_so_rede_local():
    assert S.cliente_aceito("192.168.1.20") and S.cliente_aceito("127.0.0.1")
    assert not S.cliente_aceito("8.8.8.8")


def test_os_tres_arquivos_tem_hash_fixado():
    """⛔ Modelo com outro hash é outro modelo com o mesmo nome."""
    assert set(S.ARQUIVOS) == {"vision_model.onnx", "text_model_fp16.onnx", "tokenizer.json"}
    assert all(len(sha) == 64 for _, sha in S.ARQUIVOS.values())
