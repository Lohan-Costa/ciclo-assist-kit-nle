"""O motor do ATUALIZAR TIMELINE (organograma aprovado pelo autor em 2026-09-27).

Rodar:

    .venv-win/Scripts/python tests/test_atualizar.py

Confere as regras do autor sem NLE nenhum:
- o plano que só ANDOU (porque algo entrou antes) não mudou;
- novo, retirado, aparado e take TROCADO (vira novo, a correção não é herdada);
- a porcentagem em TEMPO de imagem, com o trocado contado uma vez só;
- o áudio fora da conta por padrão;
- o que a cor devolveu sai da conta, e o render com o reel e o TC do original casa sozinho;
- a PRODA real: comparada com ela mesma dá 0%, e com mudanças feitas de propósito dá o esperado.
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import atualizar as A  # noqa: E402


def tc(q: int, fps: int = 24) -> str:
    return f"{q // (3600 * fps):02d}:{q // (60 * fps) % 60:02d}:{q // fps % 60:02d}:{q % fps:02d}"


def seg(inicio, dur, mob, fonte=0, trilha=1, audio=False, **extra):
    s = {"timeline_tc_in": tc(inicio), "duration_frames": dur, "mob_id": mob, "source_start_frames": fonte,
         "track": trilha, "is_audio": audio, "is_gap": False, "is_transition": False, "clip_name": mob,
         "speed_ratio": 1.0}
    s.update(extra)
    return s


def carta(*segs, masters=None):
    ms = masters or {}
    for s in segs:
        ms.setdefault(s["mob_id"], {"identidade": {"reel": s["mob_id"].upper() + "001_C001", "tc_inicio": 1000}})
    return {"timeline_fps": 24, "segments": list(segs), "masters": ms}


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 62 else f"{repr(obtido)[:59]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    def classes(r):
        return [(p["nome"], p["classe"]) for p in r["planos"]]

    # A partida: a, b, c de 100 quadros cada, na V1
    partida = carta(seg(0, 100, "a"), seg(100, 100, "b"), seg(200, 100, "c"))

    print("── 1. o que não mudou ──")
    r = A.comparar(partida, copy.deepcopy(partida))
    ok("a mesma Carta: tudo igual, 0%", (r["contagem"]["igual"], r["pct_imagem"], r["faixa"]),
       (3, 0.0, "atualizacao"))

    print("\n── 2. entrou um plano no começo: o resto só ANDOU ──")
    nova = carta(seg(0, 50, "x"), seg(50, 100, "a"), seg(150, 100, "b"), seg(250, 100, "c"))
    r = A.comparar(partida, nova)
    ok("⭐ x novo; a, b, c deslocados (não mudaram)", classes(r),
       [("x", "novo"), ("a", "deslocado"), ("b", "deslocado"), ("c", "deslocado")])
    ok("⭐ a mudança é só o tempo do x: 50 de 350", (r["quadros_mudados"], r["quadros_referencia"], r["pct_imagem"]),
       (50, 350, 14.3))

    print("\n── 3. saiu o b (ripple) ──")
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 100, "c")))
    ok("b retirado, c deslocado", sorted(classes(r)), [("a", "igual"), ("b", "retirado"), ("c", "deslocado")])
    ok("100 de 300 = 33,3%, faixa grande", (r["pct_imagem"], r["faixa"]), (33.3, "grande"))

    print("\n── 4. aparado ──")
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 80, "b", fonte=10), seg(180, 100, "c")))
    ok("b aparado 10 na cabeça e 10 no rabo; c deslocado", classes(r),
       [("a", "igual"), ("b", "aparado"), ("c", "deslocado")])
    ok("a mudança do aparado é o que entrou/saiu: 20 quadros", r["quadros_mudados"], 20)

    print("\n── 5. take TROCADO: vira novo, não herda correção ──")
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 100, "b2"), seg(200, 100, "c")))
    ok("⭐ b2 no lugar do b: trocado (uma linha; o b vai dentro dela)", sorted(classes(r)),
       [("a", "igual"), ("b2", "trocado"), ("c", "igual")])
    ok("⭐ o trocado conta UMA vez: 100 de 300", r["quadros_mudados"], 100)
    tr = next(p for p in r["planos"] if p["nome"] == "b2")
    ok("…e aponta o plano que ele substitui (para a execução apagar)", tr["partida"], 1)
    r = A.comparar(partida, carta(seg(0, 50, "x"), seg(50, 100, "a"), seg(150, 100, "b2"), seg(250, 100, "c")))
    ok("trocado mesmo depois de algo entrar antes (desconta o deslocamento)",
       [c for n, c in classes(r) if n == "b2"], ["trocado"])

    print("\n── 6. a mesma mídia, outro trecho (não é o mesmo plano) ──")
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 100, "b", fonte=5000), seg(200, 100, "c")))
    ok("b com trecho sem sobreposição = trocado, não aparado", [c for n, c in classes(r) if n == "b"], ["trocado"])

    print("\n── 6b. o mesmo trecho usado várias vezes, e um ripple MAIOR que o espaço entre eles ──")
    # U01 (2026-09-28): casar pela posição mais próxima errava aqui. u[0,150) + r×4 de 100.
    rep = carta(seg(0, 150, "u"), *[seg(150 + 100 * k, 100, "r") for k in range(4)])
    r = A.comparar(rep, carta(*[seg(100 * k, 100, "r") for k in range(4)]))
    ok("⭐ tirar o u: 1 retirado, as 4 repetições só andam (nenhum novo)",
       (r["contagem"]["retirado"], r["contagem"]["deslocado"], r["contagem"]["novo"]), (1, 4, 0))
    r = A.comparar(rep, carta(seg(0, 150, "u"), *[seg(150 + 100 * k, 100, "r") for k in range(3)]))
    ok("tirar uma das repetições: 1 retirado, sem novo", (r["contagem"]["retirado"], r["contagem"]["novo"]), (1, 0))

    print("\n── 7. velocidade ──")
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 100, "b", speed_ratio=2.0), seg(200, 100, "c")))
    ok("b com outra velocidade = aparado (conferir)", [c for n, c in classes(r) if n == "b"], ["aparado"])

    print("\n── 8. áudio fora da conta por padrão ──")
    p_a = carta(seg(0, 300, "a"), seg(0, 300, "som1", audio=True))
    n_a = carta(seg(0, 300, "a"), seg(0, 150, "som2", audio=True), seg(150, 150, "som3", audio=True))
    r = A.comparar(p_a, n_a)
    ok("⭐ o sound design mudou todo, a imagem não: 0%", (r["pct_imagem"], "pct_audio" in r), (0.0, False))
    r = A.comparar(p_a, n_a, contar_audio=True)
    ok("ligado, o áudio tem a conta dele", r["pct_audio"], 100.0)

    print("\n── 9. o que a cor devolveu ──")
    ms = {"render": {"identidade": {"reel": "B001_C001", "tc_inicio": 1000}, "caminho_na_bin": r"S:\cor\para-edicao\b.mov"}}
    r = A.comparar(partida, carta(seg(0, 100, "a"), seg(100, 100, "render"), seg(200, 100, "c"), masters=ms))
    ok("⭐ o render com o reel e o TC do original casa sozinho (igual)",
       [c for n, c in classes(r) if n == "render"], ["igual"])
    ms2 = {"flat": {"identidade": {"reel": "FILME", "tc_inicio": 0}, "caminho_na_bin": r"S:\cor\para-edicao\filme.mov"}}
    nova = carta(seg(0, 100, "a"), seg(100, 100, "b"), seg(200, 100, "c"), seg(0, 300, "flat", trilha=2), masters=ms2)
    r = A.comparar(partida, nova)
    ok("o arquivo do filme inteiro por cima, sem registro: aparece como novo", r["contagem"]["novo"], 1)
    reg = lambda s, m: "para-edicao" in (m.get("caminho_na_bin") or "")  # noqa: E731
    r = A.comparar(partida, nova, devolvido=reg)
    ok("⭐ com o registro do canal: sai da conta, e a montagem embaixo fica igual",
       (r["contagem"]["novo"], r["contagem"]["igual"], r["devolvidos"], r["pct_imagem"]), (0, 3, 1, 0.0))

    print("\n── 10. faixas ──")
    ok("25 atualização · 25,1 grande · 60,1 nova", [A.faixa(25), A.faixa(25.1), A.faixa(60.1)],
       ["atualizacao", "grande", "nova"])
    ok("faixas editáveis (10/80)", A.faixa(30, (10, 80)), "grande")

    print("\n── 12. o PLANO DE EDIÇÃO do caminho B (a timeline do colorista) ──")
    # Partida: a[0,100) b[100,200) c[200,300). Nova: x entra no começo (50), b perde 10 na cabeça.
    nova = carta(seg(0, 50, "x"), seg(50, 100, "a"), seg(150, 90, "b", fonte=10), seg(240, 100, "c"))
    itens = [
        {"id": "a", "trilha": "V1", "inicio": 0, "dur": 100, "fonte_in": 0},
        # o colorista cortou o b no meio: b1 [100,150) e b2 [150,200)
        {"id": "b1", "trilha": "V1", "inicio": 100, "dur": 50, "fonte_in": 0},
        {"id": "b2", "trilha": "V1", "inicio": 150, "dur": 50, "fonte_in": 50},
        {"id": "c", "trilha": "V1", "inicio": 200, "dur": 100, "fonte_in": 0},
        # e pôs um adjustment clip na V2 sobre o c
        {"id": "ajuste", "trilha": "V2", "inicio": 220, "dur": 40, "fonte_in": 0},
    ]
    pe = A.plano_de_edicao(partida, nova, itens)
    it = pe["itens"]
    ok("a anda 50 (o x entrou antes)", (it["a"]["acao"], it["a"]["inicio"]), ("mover", 50))
    ok("⭐ b1 (a cabeça do corte interno) perde os 10 quadros e anda",
       (it["b1"]["acao"], it["b1"]["inicio"], it["b1"]["dur"], it["b1"]["fonte_in"]), ("aparar", 150, 40, 10))
    ok("⭐ b2 (a outra metade) só anda: o corte interno do colorista sobrevive",
       (it["b2"]["inicio"], it["b2"]["dur"], it["b2"]["fonte_in"]), (190, 50, 50))
    ok("c anda 40 (entrou 50, saíram 10)", it["c"]["inicio"], 240)
    ok("⭐ a camada do colorista anda com a montagem embaixo dela",
       (it["ajuste"]["acao"], it["ajuste"]["inicio"], it["ajuste"]["motivo"]), ("mover", 260, "camada do colorista"))
    ok("o x vai para a lista de inserir", [(x["nome"], x["inicio"], x["classe"]) for x in pe["inserir"]],
       [("x", 0, "novo")])

    pe = A.plano_de_edicao(partida, carta(seg(0, 100, "a"), seg(100, 100, "c")),
                           itens[:3] + [{"id": "ajuste", "trilha": "V2", "inicio": 120, "dur": 40}])
    ok("b retirado: os dois pedaços do colorista saem", (pe["itens"]["b1"]["acao"], pe["itens"]["b2"]["acao"]),
       ("apagar", "apagar"))
    ok("⭐ a camada sobre um trecho que saiu fica e vai para conferir (nada some sem aviso)",
       pe["itens"]["ajuste"]["acao"], "conferir")

    pe = A.plano_de_edicao(partida, carta(seg(0, 100, "a"), seg(100, 130, "b", fonte=-10), seg(230, 100, "c")),
                           itens[:4])
    ok("b esticado 10 na cabeça e 20 no rabo: os itens andam, as pontas novas vão para inserir",
       ([(x["inicio"], x["dur"], x["classe"]) for x in pe["inserir"]], pe["itens"]["b1"]["inicio"],
        pe["itens"]["b2"]["inicio"]), ([(100, 10, "esticado"), (210, 20, "esticado")], 110, 160))

    pe = A.plano_de_edicao(partida, carta(seg(0, 100, "a"), seg(100, 100, "b2"), seg(200, 100, "c")), itens[:4])
    ok("take trocado: os itens do antigo saem e o novo vai para inserir",
       (pe["itens"]["b1"]["acao"], [(x["nome"], x["classe"]) for x in pe["inserir"]]),
       ("apagar", [("b2", "trocado")]))

    print("\n── 12b. de CORTE a CORTE: o plano a inserir e as transições do editor (autor, 2026-10-01) ──")
    # O take trocado do U03: na Carta, o áudio que SAI avança 40 quadros sobre o cross-fade que começa no
    # corte (6670, cutpoint 0). No NLE ele termina no corte; a transição usa a sobra da mídia.
    tr = [{"trilha": "A1000", "inicio": 6670, "dur": 40, "corte": 6670, "nome": "(transition)"}]
    x = {"inicio": 6222, "dur": 488, "fonte_offset": 0, "velocidade": 1.0, "trilha": "A1000"}
    A._de_corte_a_corte(x, tr)
    ok("⭐ o que SAI pela transição termina no corte (488 → 448)", (x["inicio"], x["dur"], x["fonte_offset"]), (6222, 448, 0))
    # centrada (cutpoint 20): o que ENTRA começa antes do corte na Carta; no NLE, no corte, e a fonte anda 20
    tr = [{"trilha": "A1000", "inicio": 6650, "dur": 40, "corte": 6670, "nome": "(transition)"}]
    x = {"inicio": 6650, "dur": 392, "fonte_offset": 0, "velocidade": 1.0, "trilha": "A1000"}
    A._de_corte_a_corte(x, tr)
    ok("⭐ o que ENTRA por uma transição centrada começa no corte, e a fonte anda junto", (x["inicio"], x["dur"], x["fonte_offset"]), (6670, 372, 20))
    x = {"inicio": 100, "dur": 50, "fonte_offset": 0, "velocidade": 1.0, "trilha": "A1000"}
    A._de_corte_a_corte(x, tr)
    ok("sem transição no caminho, nada muda", (x["inicio"], x["dur"]), (100, 50))
    car = {"timeline_fps": 24, "segments": [{"is_transition": True, "is_audio": True, "track": 1000,
           "timeline_tc_in": "00:04:37:22", "duration_frames": 40, "cutpoint": 0, "clip_name": "(transition)"}]}
    ok("as transições da Carta, com o corte", A.transicoes(car),
       [{"trilha": "A1000", "inicio": 6670, "dur": 40, "corte": 6670, "nome": "(transition)", "efeito": ""}])

    print("\n── 10b. a conferência de encaixe (a guarda do Atualizar com dois arquivos) ──")
    antiga = carta(seg(0, 100, "a"), seg(100, 100, "b"), seg(200, 100, "c"))
    it = lambda i, ini, dur: {"id": i, "trilha": "V1", "inicio": ini, "dur": dur, "fonte_in": 0}
    ok("⭐ a timeline que veio desta versão: 100%",
       A.encaixe(antiga, [it("a", 0, 100), it("b", 100, 100), it("c", 200, 100)])["pct"], 100.0)
    ok("o colorista cortou o b em dois e pôs uma camada na V2: continua 100%",
       A.encaixe(antiga, [it("a", 0, 100), it("b1", 100, 40), it("b2", 140, 60), it("c", 200, 100),
                          {"id": "k", "trilha": "V2", "inicio": 30, "dur": 50, "fonte_in": 0}])["pct"], 100.0)
    ok("⭐ outra versão (tirou 30 quadros do começo, tudo andou): quase nada no lugar",
       A.encaixe(antiga, [it("a", 0, 70), it("b", 70, 100), it("c", 170, 100)])["pct"] < A.ENCAIXE_MINIMO, True)
    ok("o colorista apagou o c: 2 de 3 planos no lugar",
       {k: v for k, v in A.encaixe(antiga, [it("a", 0, 100), it("b", 100, 100)]).items() if k != "pct"},
       {"planos": 3, "no_lugar": 2})

    print("\n── 11. a PRODA real ──")
    from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
    cruz = Path(raiz_das_amostras()) \
        / "02 PROJETOS AVID" / "PRODUCAO-A" / "03_OC_EDIT VALENDO.avb"
    if not cruz.is_file():
        print(f"  PULADO — {cruz} não está neste disco")
    else:
        from avb_bin import segmentos as S
        from avb_export.reader import topen
        with topen(str(cruz)) as f:
            leitura = S.ler_timeline(f, next(iter(S.sequencias(f))))
        r = A.comparar(leitura, copy.deepcopy(leitura))
        n_v = sum(r["contagem"].values())
        ok("⭐ a PRODA contra ela mesma: 0%, nenhum novo/retirado/trocado",
           (r["pct_imagem"], r["contagem"]["novo"], r["contagem"]["retirado"], r["contagem"]["trocado"]),
           (0.0, 0, 0, 0))
        # tira o 5º plano de vídeo da V1 e puxa tudo o que vem depois (ripple em TODAS as trilhas)
        fps = 24
        v1 = [i for i, s in enumerate(leitura["segments"]) if not s["is_audio"] and not s["is_gap"]
              and not s.get("is_transition") and s["track"] == 1 and not s.get("disabled")]
        alvo = leitura["segments"][v1[5]]
        ini, dur = A._quadros(alvo["timeline_tc_in"], fps), alvo["duration_frames"]
        nova = copy.deepcopy(leitura)
        nova["segments"] = [s for i, s in enumerate(nova["segments"]) if i != v1[5]]
        for s in nova["segments"]:
            q = A._quadros(s["timeline_tc_in"], fps)
            if q >= ini + dur:
                s["timeline_tc_in"] = tc(q - dur)
        r = A.comparar(leitura, nova)
        ok("⭐ um plano tirado no começo: 1 retirado, NENHUM novo (o resto só andou)",
           (r["contagem"]["retirado"], r["contagem"]["novo"], r["contagem"]["trocado"]), (1, 0, 0))
        ok("…e a porcentagem é pequena (só aquele plano)", r["pct_imagem"] < 5, True)
        print(f"     (a PRODA: {n_v} planos de vídeo; tirar 1 de {dur} quadros = {r['pct_imagem']}%)")

    print("\n── B040: o reel degenerado do BRAW ──")
    braw = {m: {"identidade": {"reel": "1", "tc_inicio": 1000}} for m in ("cam_a", "cam_b")}
    r = A.comparar(carta(seg(0, 100, "cam_a"), masters=dict(braw)), carta(seg(0, 100, "cam_b"), masters=dict(braw)))
    ok("câmera A e B com o mesmo reel '1' e o mesmo TC NÃO são a mesma mídia",
       [c for n, c in classes(r) if n == "cam_b"] != ["igual"], True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
