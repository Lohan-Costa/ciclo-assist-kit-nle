"""Os merged de um SYNC, em bins por cena — a rota `POST /api/v1/merge` (Ciclo Assist).

A aba Merged do painel parte de uma SEQUÊNCIA que o editor já tem (`premiere/escrita.py`).
Esta parte do RESULTADO DO SYNC que o próprio Órbita rodou: um merged por câmera de cada
tomada, cada um na bin da sua cena (`CENAS/<cena>`, decisão do autor de 2026-11-07), com o
proxy que o Ciclo Assist conferiu anexado.

⭐ A cena é a da CLAQUETE do som, pela MESMA regra da bin por cena do Avid
(`avid/cenas.py`): `DESCARTE` → cena → `NAO RESOLVIDO`. O órfão (câmera sem som) não vira
merged — não há o que fundir —, então não há bin `ORFAOS` aqui.
"""

from __future__ import annotations

from pathlib import Path

from media import claquete as _claquete

BIN_NAO_RESOLVIDO = "NAO RESOLVIDO"
BIN_DESCARTE = "DESCARTE"


def chave_da_cena(take) -> str:
    """Em que bin a tomada entra. A ORDEM é a do Avid: descarte antes da cena."""
    caminho = take.sound.path if take.sound else None
    if _claquete.e_descartado(caminho) is True:
        return BIN_DESCARTE
    c = _claquete.ler(Path(str(caminho)).name) if caminho else None
    if not c:
        return BIN_NAO_RESOLVIDO
    return f"{c.episodio} {c.cena}" if c.episodio else c.cena


def _ordem_da_tomada(take) -> tuple:
    c = _claquete.ler(take.sound.path.name) if take.sound else None
    return (c.plano if c else "", c.take if c else "", take.sound.path.name if take.sound else "")


def agrupar(takes) -> list[tuple[str, list]]:
    """`[(bin, tomadas)]` — cenas em ordem, depois `NAO RESOLVIDO` e `DESCARTE`.

    Só entra tomada com som E câmera: é o que vira merged.
    """
    grupos: dict[str, list] = {}
    for t in takes:
        if not t.sound or not t.cameras:
            continue
        grupos.setdefault(chave_da_cena(t), []).append(t)
    for v in grupos.values():
        v.sort(key=_ordem_da_tomada)
    especiais = (BIN_NAO_RESOLVIDO, BIN_DESCARTE)
    cenas = sorted(k for k in grupos if k not in especiais)
    return [(k, grupos[k]) for k in cenas + [k for k in especiais if k in grupos]]


def anexar_proxies(project, proxies: dict) -> dict:
    """Põe em cada câmera o proxy que veio conferido. Devolve o que ficou de fora.

    `proxies`: `{caminho da câmera: caminho do proxy}`. ⚠️ Quem CONFERE o par (taxa,
    TC, quadros, canais) é o Ciclo Assist — aqui só se exige que o arquivo exista: um
    proxy que sumiu do disco faria o Premiere mostrar offline com o botão ligado.
    """
    norm = {str(Path(str(k))): str(v) for k, v in (proxies or {}).items() if k and v}
    sem_proxy, ausentes = [], []
    for d in project.groups:
        for t in d.takes:
            if not t.sound:
                continue
            for cam in t.cameras:
                p = norm.get(str(cam.path))
                if not p:
                    sem_proxy.append(str(cam.path))
                elif not Path(p).is_file():
                    ausentes.append(p)
                else:
                    cam.proxy_path = Path(p)
                    tam = _tamanho(p)
                    if tam:
                        cam.proxy_size = tam
    return {"sem_proxy": sem_proxy, "proxy_ausente": ausentes}


def _tamanho(caminho: str) -> tuple[int, int] | None:
    """Largura × altura do proxy (o `FrameRect` do `Media` dele). Sem probe, o padrão do modelo."""
    try:
        from media.inspector import probe
        m = probe(caminho)
    except Exception:  # noqa: BLE001 — o tamanho é cortesia; o proxy entra assim mesmo
        return None
    w, h = m.get("width"), m.get("height")
    return (int(w), int(h)) if w and h else None
