"""Ler a seleção da timeline do Media Composer pelo ARO — o 2º caminho da seleção.

O 1º caminho é a CÓPIA do editor (`coleta.capturar`: Ctrl+0 → Ctrl+C), que o autor não gosta
porque PISCA e cria/apaga uma bin temporária. O ARO (AvidRemoteObjects) é o servidor interno de
automação do próprio MC: escrevemos a dylib que o transporta (`tools/aro/aro_servidor.c`, só
laboratório por enquanto), e ela lê a seleção POR DENTRO — sem flicker, sem bin — e dá o MobID da
FONTE de cada segmento selecionado (`AComposition::GetMobID`). Banco:
`plugins/avid-panel-sdk/arrastar.md` §"IDENTIDADE RESOLVIDA".

Só LEITURA, por um socket em `127.0.0.1` (a dylib escuta ali quando o MC a carrega). Se o ARO não
estiver presente (dylib não instalada, ou MC sem o canal), as funções devolvem `None` e o chamador
cai no Caminho A (a cópia). Nada aqui depende do ARO existir.
"""
from __future__ import annotations

import logging
import socket

log = logging.getLogger("delapraca.mc.aro")

PORTA = 17890


def _comando(cmd: str, porta: int = PORTA, prazo: float = 20.0) -> str | None:
    """Manda um comando de linha ao canal ARO e devolve a resposta até `END`, ou `None` se não responder."""
    try:
        s = socket.create_connection(("127.0.0.1", porta), timeout=2.0)
    except OSError:
        return None
    try:
        s.settimeout(prazo)
        s.sendall((cmd + "\n").encode())
        buf = b""
        while not buf.rstrip().endswith(b"END"):
            d = s.recv(8192)
            if not d:
                break
            buf += d
        return buf.decode("utf-8", "replace")
    except OSError as e:
        log.debug("ARO %s falhou: %s", cmd, e)
        return None
    finally:
        s.close()


def disponivel(porta: int = PORTA) -> bool:
    """O canal ARO está no ar (a dylib carregada e escutando)?"""
    resp = _comando("PING", porta)
    return bool(resp and "PONG" in resp)


def ler_selecao(porta: int = PORTA) -> dict | None:
    """A seleção da timeline pelo ARO.

    Devolve `{"mob_id": <seq>|None, "masters": [64hex, ...], "clipes": n, "erro": <str>|None}`, ou `None`
    se o canal não responder (aí o chamador usa o Caminho A). `masters` são os MobIDs das FONTES dos segmentos
    selecionados, sem repetição; títulos e fillers (sem master) não entram. `erro` preenchido = o ARO respondeu
    mas sem timeline/seleção utilizável.

    A dylib entrega o MobID CRU (ordem interna do MC = o `bytes_le` do pyavb): a fonte de cada segmento vem de
    `ASourceClip::GetSrcMobID`, a sequência de `AComposition::GetMobID`. Aqui convertemos com o **pyavb**
    (`MobID(bytes_le=...)` → URN externa) — a mesma grafia que `relink._hexa`/`aaf.remap` normalizam para comparar
    com o `.avb`. Teste: o `mob_id` daqui deve igualar `mc.sequencia_no_record()`.
    """
    resp = _comando("SELMOB", porta)
    if resp is None:
        return None
    seq: str | None = None
    masters: list[str] = []
    erro: str | None = None
    for linha in resp.splitlines():
        if linha.startswith("MOB "):
            u = _para_urn(linha[4:].strip())
            if u:
                masters.append(u)
        elif linha.startswith("SEQ "):
            seq = _para_urn(linha[4:].strip())
        elif linha.startswith("ERR"):
            erro = linha[3:].strip() or "erro do ARO"
    return {"mob_id": seq, "masters": list(dict.fromkeys(masters)), "clipes": len(masters), "erro": erro}


def _para_urn(cru_hex: str) -> str | None:
    """MobID cru do ARO (64 hex, ordem interna = `bytes_le` do pyavb) → a URN externa. `None` se não for 64 hex."""
    h = (cru_hex or "").strip().lower()
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        return None
    try:
        from avb.mobid import MobID
        return str(MobID(bytes_le=bytes.fromhex(h)))
    except Exception as e:  # noqa: BLE001
        log.debug("MobID cru inválido %r: %s", cru_hex, e)
        return None
