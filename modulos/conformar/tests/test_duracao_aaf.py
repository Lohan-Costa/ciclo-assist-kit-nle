r"""A duração do master na rota AAF, e o portão que ela liga.

Até 2026-08-16 a rota AAF **não preenchia `duracao_frames`**, e o efeito não era um
campo vazio: era o **portão de duração do `casar_masters` ficando neutro na rota
inteira** — o veto que separa dois clipes de mesmo nome simplesmente não opinava. A rota
`.avb` já preenchia. Medido no AAF real (`PRODA_RELINKER_ALTA.aaf`): **303/303 MasterMobs
têm a duração disponível**, e **118/118 masters em uso** passaram a tê-la; nenhuma fora
da faixa plausível.

⚠️⚠️ **O que este teste protege é a conta que dá certo pelo motivo errado.** Num AAF a
trilha de som pode contar em *samples* (`edit_rate = 48000`) e a de imagem em frames
(`23,976`). Cruzar o comprimento de uma com a taxa da outra produz um número **plausível
e errado por três ordens de grandeza** — e um número plausível não levanta exceção, só
reprova candidatos certos. Por isso `length` e `edit_rate` saem sempre do MESMO slot.

⭐ Medido também: no mesmo AAF apareceram `edit_rate` de **23,976 e de 24,0** entre os
sons. A taxa não pode ser presumida a partir de um slot só nem da timeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from aaf.masters import _duracao_em_frames, _segundos_do_slot  # noqa: E402
from media.matcher_masters import _duracao_do_master  # noqa: E402


class SlotFalso:
    def __init__(self, media_kind, length, edit_rate):
        self.media_kind = media_kind
        self.edit_rate = edit_rate
        self.segment = type("Seg", (), {"length": length})()


class MobFalso:
    def __init__(self, slots):
        self.slots = slots


class MasterFalso:
    def __init__(self, duracao_frames, edit_rate):
        self.duracao_frames = duracao_frames
        self.edit_rate = edit_rate


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<52} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── segundos de um slot (length e taxa do MESMO slot) ────────")
    # Imagem: 1298 frames a 23,976 — o caso real medido no AAF do projeto.
    img = SlotFalso("Picture", 1298, 23.976023976023978)
    ok("imagem em frames", round(_segundos_do_slot(img), 3), 54.137)
    # ⭐ Som contando em SAMPLES: a mesma conta continua dando segundos, porque os dois
    # números saem do mesmo slot. É isto que torna o método imune à unidade.
    som_samples = SlotFalso("Sound", 48000 * 30, 48000.0)
    ok("⭐ som em samples dá os mesmos 30s", _segundos_do_slot(som_samples), 30.0)
    # E som contando em frames@timeline, que foi o que o AAF real trouxe.
    som_frames = SlotFalso("Sound", 5064, 23.976023976023978)
    ok("som em frames@timeline", round(_segundos_do_slot(som_frames), 2), 211.21)
    ok("sem comprimento não inventa", _segundos_do_slot(SlotFalso("Picture", None, 24.0)),
       None)
    ok("sem taxa não inventa", _segundos_do_slot(SlotFalso("Picture", 100, None)), None)
    ok("taxa zero não estoura", _segundos_do_slot(SlotFalso("Picture", 100, 0)), None)

    print("\n── duração do master, na base do `edit_rate` do segmento ────")
    # Master de câmera: slot de imagem + dois de som, todos com a mesma duração.
    camera = MobFalso([
        SlotFalso("Picture", 1298, 23.976023976023978),
        SlotFalso("Sound", 1298, 23.976023976023978),
    ])
    ok("imagem: 1298 frames", _duracao_em_frames(camera, "picture", 23.976023976023978),
       1298)

    # ⚠️⚠️ O CASO QUE JUSTIFICA O MÓDULO: master cujo som conta em samples, e o segmento
    # da timeline traz 23,976. Ler o `length` do som (1 440 000) com a taxa do segmento
    # daria 60 054 "frames" — 41 minutos onde há 30 segundos.
    misto = MobFalso([
        SlotFalso("Picture", 719, 23.976023976023978),
        SlotFalso("Sound", 1_440_000, 48000.0),
    ])
    ok("⭐⭐ som em samples vira frames@timeline, não lixo",
       _duracao_em_frames(misto, "sound", 23.976023976023978), 719)
    ok("e a imagem dá o mesmo número",
       _duracao_em_frames(misto, "picture", 23.976023976023978), 719)

    # Sem taxa do segmento, o par vira o do próprio slot — e continua coerente.
    ok("sem taxa do segmento, usa a do slot",
       _duracao_em_frames(camera, "picture", None), 1298)
    ok("mob sem slots devolve None", _duracao_em_frames(MobFalso([]), "picture", 24.0),
       None)
    # Espécie ausente cai para qualquer slot com dado, em vez de desistir.
    ok("espécie que não existe cai para outro slot",
       _duracao_em_frames(camera, "data", 23.976023976023978), 1298)

    print("\n── a invariante que o matcher consome ───────────────────────")
    # ⭐ Tudo isto existe para que `duracao_frames / edit_rate` sejam SEGUNDOS. É a única
    # coisa que o portão do matcher pede, e vale para as duas rotas.
    m = MasterFalso(1298, 23.976023976023978)
    ok("⭐ duracao_frames / edit_rate = segundos",
       round(_duracao_do_master(m), 3), 54.137)
    ok("sem duração, o portão fica neutro (era a rota AAF inteira)",
       _duracao_do_master(MasterFalso(None, 23.976)), None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
