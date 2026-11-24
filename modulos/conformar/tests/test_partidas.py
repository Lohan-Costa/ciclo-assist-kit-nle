"""O ciclo do ATUALIZAR TIMELINE no serviço, sem NLE (organograma aprovado em 2026-09-27).

Rodar:

    .venv-win/Scripts/python tests/test_partidas.py

- Trazer a v1 guarda a Carta de PARTIDA nesta máquina, com a timeline que ela gerou;
- chegando a v2, a partida é SUGERIDA (a mesma sequência primeiro; o nome sem a versão depois);
- comparar a v2 com a partida dá o resumo da atualização, sem mexer no NLE;
- as faixas ficam em Ajustes, e fora do intervalo voltam as de fábrica.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"),
                str(RAIZ / "tests")]

from carta_aberta.writer import build_carta_aberta  # noqa: E402
from test_carta_ida_e_volta import leitura_sintetica  # noqa: E402

import partidas as P  # noqa: E402
import sessao_receber as R  # noqa: E402
from api import rotas  # noqa: E402,F401
from api.servidor import _ROTAS, Contexto  # noqa: E402


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

    print("── 0. o nome sem a versão ──")
    ok("PRODA_CORTE.02 / PRODA_CORTE v3 / PRODA_CORTE_03 → cruz_corte",
       {P.base_do_nome(n) for n in ("PRODA_CORTE.02", "PRODA_CORTE v3", "PRODA_CORTE_03", "cruz_corte")},
       {"cruz_corte"})

    with tempfile.TemporaryDirectory() as tmp:
        dados, canal = Path(tmp) / "dados", Path(tmp) / "magic-cor"
        caixa = canal / "para-cor"
        dados.mkdir()
        caixa.mkdir(parents=True)
        cfg = {"cor": str(canal)}
        v1 = leitura_sintetica()
        # A v2: o 2º plano de vídeo sai (sem ripple, para o teste ficar simples) e a sequência é a
        # MESMA (mesmo mob id) — e numa v3 o editor duplicou a sequência (mob id novo, nome .03).
        v2 = copy.deepcopy(v1)
        video = [i for i, s in enumerate(v2["segments"]) if not s["is_audio"] and not s["is_gap"]
                 and not s.get("is_transition")]
        del v2["segments"][video[1]]
        v3 = copy.deepcopy(v2)
        v3["sequence_mob_id"] = "urn:smpte:umid:outra-sequencia"
        v3["composition_name"] = "SINTETICA.03"
        ids = {"v1": "11111111-1111-4111-8111-111111111111", "v2": "22222222-2222-4222-8222-222222222222",
               "v3": "33333333-3333-4333-8333-333333333333"}

        def escrever(leitura, chave, hora):
            build_carta_aberta(leitura, [], str(caixa / f"SINTETICA__{chave}.carta.json"),
                               leitura.get("composition_name") or "SINTETICA", "",
                               envio={"id": ids[chave], "tipo": "timeline", "remetente": {"maquina": "EDIT"},
                                      "enviado_em": f"2026-09-27T{hora}:00-03:00"})

        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados), \
                mock.patch.object(P.plataforma, "pasta_dados", lambda: dados), \
                mock.patch("media.pmr.indice_de", lambda *_a, **_k: SimpleNamespace(por_arquivo={})):
            s = R.SessaoReceber()
            escrever(v1, "v1", "10:00")
            s.caixa(cfg)
            print("\n── 1. trazer a v1 guarda a partida ──")
            r = s.trazido(ids["v1"], True, timeline={"uid": "tl-uid-1", "nome": "SINTETICA"})
            ok("⭐ a partida anotada com a timeline que ela gerou",
               (r["partida"]["timeline_uid"], r["partida"]["timeline_nome"]), ("tl-uid-1", "SINTETICA"))
            ok("…e a cópia da Carta está nesta máquina", (dados / "partidas" / f"{ids['v1']}.carta").is_file(), True)
            ok("⭐ a Carta original desceu para importado (o arquivar segue igual)",
               bool(r.get("arquivado")) and "importado" in r["arquivado"], True)
            ok("um Trazer que falhou não vira partida",
               s.trazido("44444444-4444-4444-8444-444444444444", False)["partida"], None)

            print("\n── 2. chega a v2: a partida é sugerida ──")
            escrever(v2, "v2", "11:00")
            s.caixa(cfg)
            sug = s.partidas_para(ids["v2"])["partidas"]
            ok("⭐ a v1, pela mesma sequência", [(x["id"], x["motivo"]) for x in sug], [(ids["v1"], "mesma_sequencia")])

            print("\n── 3. comparar a v2 com a partida ──")
            c = s.comparar_versoes({"partida": ids["v1"]}, {"envio": ids["v2"]})
            ok("⭐ um plano retirado, nenhum novo", (c["contagem"]["retirado"], c["contagem"]["novo"]), (1, 0))
            ok("o resumo lista o que mudou (não os iguais)", [m["classe"] for m in c["mudados"]], ["retirado"])
            ok("as faixas de fábrica vão junto", c["faixas"], [25.0, 60.0])
            ok("a v2 contra ela mesma não existe como partida", s.partidas_para(ids["v2"])["partidas"][0]["id"], ids["v1"])

            print("\n── 4. o editor duplicou a sequência (v3: mob id novo, nome .03) ──")
            escrever(v3, "v3", "12:00")
            s.caixa(cfg)
            s.trazido(ids["v2"], True, timeline={"uid": "tl-uid-2", "nome": "SINTETICA 2"})
            sug = s.partidas_para(ids["v3"])["partidas"]
            ok("⭐ sugere pelo nome sem a versão, a mais recente primeiro",
               [(x["id"], x["motivo"]) for x in sug], [(ids["v2"], "mesmo_nome"), (ids["v1"], "mesmo_nome")])

            print("\n── 5. pela rota ──")
            def chamar(metodo, rota, corpo=None):
                ctx = Contexto(metodo, rota, {}, json.dumps(corpo).encode() if corpo else b"",
                               SimpleNamespace(receber=s, ultimo_uso_receptor=0))
                return _ROTAS[(metodo, rota)](ctx)
            st, r = chamar("POST", "/receber/comparar", {"id": ids["v3"], "partida": ids["v2"]})
            ok("v3 contra v2: nada mudou na montagem (só a sequência foi duplicada)",
               (st, r["pct_imagem"], r["contagem"]["novo"], r["contagem"]["retirado"]), (200, 0.0, 0, 0))
            st, r = chamar("POST", "/receber/comparar", {"id": ids["v3"], "partida": "99999999-9999-4999-8999-999999999999"})
            ok("partida que não existe: 409 com texto claro", (st, "traga como nova" in r["erro"]), (409, True))
            st, r = chamar("POST", "/receber/comparar", {"id": "../../etc", "partida": ids["v1"]})
            ok("id que não é id: 409, sem tocar disco", st, 409)

            print("\n── 5b. a EXECUÇÃO no serviço: reescrever a timeline de trabalho ──")
            from drp import reescrever as RW
            # a timeline de trabalho: o DRT que o Importar da v1 gerou (o que o Resolve recebeu)
            trab = s.preparar(ids["v1"])["drt"]
            # o que a API do Resolve contaria: itens + transições de cada trilha (medido na PRODA)
            api = RW.contagem(trab)
            st, r = chamar("POST", "/receber/atualizar", {"id": ids["v2"], "partida": ids["v1"], "trabalho": trab,
                                                          "contagem": api, "marcar": True, "colorir": True})
            ok("⭐ a v2 (um plano de vídeo a menos) reescreve a timeline de trabalho",
               (st, r.get("acoes", {}).get("apagar", 0) >= 1, len(r.get("inserir", []))), (200, True, 0))
            ok("o DRT reescrito é um arquivo NOVO em recebidos (a de trabalho não é tocada)",
               (Path(r["drt"]).is_file(), Path(r["drt"]).parent == Path(trab).parent, r["drt"] != trab), (True, True, True))
            ok("⭐ o 'esperado' é o que o arquivo reescrito tem (a casca confere a importação por ele)",
               r["esperado"], RW.contagem(r["drt"]))
            ok("⭐ a atualizada leva o nome que o editor deu à v2, o mesmo do Trazer (autor, 2026-09-28)",
               r.get("nome"), s.preparar(ids["v2"])["nome"])
            errada = dict(api)
            k = next(iter(errada))
            errada[k] += 1
            st, r = chamar("POST", "/receber/atualizar", {"id": ids["v2"], "partida": ids["v1"], "trabalho": trab,
                                                          "contagem": errada})
            ok("⭐ o Resolve exportou OUTRA timeline (contagem não bate): para, sem mexer",
               (st, "nada foi alterado" in r.get("erro", "")), (409, True))
            fora = Path(tmp) / f"{ids['v1']}.drt"
            fora.write_bytes(Path(trab).read_bytes())
            st, r = chamar("POST", "/receber/atualizar", {"id": ids["v2"], "partida": ids["v1"], "trabalho": str(fora),
                                                          "contagem": api})
            ok("⛔ arquivo de trabalho fora de recebidos/: recusado", st, 409)
            aaf = Path(trab).parent / "99999999-9999-4999-8999-999999999999.drt"
            aaf.write_bytes(b"isto nao e um zip, e um AAF")
            st, r = chamar("POST", "/receber/atualizar", {"id": ids["v2"], "partida": ids["v1"], "trabalho": str(aaf),
                                                          "contagem": api})
            ok("⭐ a exportação saiu em outro formato (a constante renumerada): 409 claro, nada alterado",
               (st, "não é DRT" in r.get("erro", "")), (409, True))

            print("\n── 5c. com DOIS ARQUIVOS do disco, sem o canal (organograma de 2026-09-28) ──")
            import atualizar as A
            solto = Path(tmp) / "solto"
            solto.mkdir()

            def arquivo(leitura, nome):
                build_carta_aberta(leitura, [], str(solto / nome), leitura.get("composition_name") or "X", "")
                return s.abrir(str(solto / nome))["chave"]

            # a versão ERRADA: a mesma montagem 7 quadros adiante (tudo desloca, como numa versão vizinha)
            fps = round(float(v1["timeline_fps"]))
            errada = copy.deepcopy(v1)
            for sg in errada["segments"]:
                q = A._quadros(sg["timeline_tc_in"], fps) + 7
                sg["timeline_tc_in"] = f"{q // (3600 * fps):02d}:{q // (60 * fps) % 60:02d}:{q // fps % 60:02d}:{q % fps:02d}"
            k1, k2, kx = arquivo(v1, "v1.json"), arquivo(v2, "v2.json"), arquivo(errada, "errada.json")
            st, r = chamar("POST", "/receber/comparar", {"antiga": {"avulso": k1}, "nova": {"avulso": k2},
                                                         "trabalho": trab, "contagem": api})
            ok("⭐ v1 e v2 escolhidas do disco: o mesmo resumo do canal (1 retirado)",
               (st, r["contagem"]["retirado"], r["contagem"]["novo"]), (200, 1, 0))
            ok("⭐ …e a versão antiga BATE com a timeline de trabalho (100%)",
               (r["encaixe"]["bate"], r["encaixe"]["pct"]), (True, 100.0))
            st, r = chamar("POST", "/receber/comparar", {"antiga": {"avulso": kx}, "nova": {"avulso": k2},
                                                         "trabalho": trab, "contagem": api})
            ok("⭐ a versão antiga ERRADA: o comparar diz que não bate, com o texto para o painel",
               (st, r["encaixe"]["bate"], "não bate" in r["encaixe"]["texto"]), (200, False, True))
            st, r = chamar("POST", "/receber/atualizar", {"antiga": {"avulso": kx}, "nova": {"avulso": k2},
                                                          "trabalho": trab, "contagem": api})
            ok("⭐ …e a execução PARA antes de mexer (a guarda vale mesmo sem o comparar)",
               (st, "Nada foi alterado" in r.get("erro", "")), (409, True))
            st, r = chamar("POST", "/receber/atualizar", {"antiga": {"avulso": k1}, "nova": {"avulso": k2},
                                                          "trabalho": trab, "contagem": api})
            ok("a execução com os dois arquivos certos reescreve a timeline",
               (st, r.get("acoes", {}).get("apagar", 0) >= 1, r.get("encaixe", {}).get("pct")), (200, True, 100.0))
            registro = r.get("registro")
            ok("…e a Carta da versão nova fica em disco para o registro (sobrevive a reiniciar)",
               (dados / "Cache" / "recebidos" / f"{registro}.nova.json").is_file(), True)
            # take trocado: o 1º plano de vídeo passa a usar OUTRO trecho da fonte (sem sobreposição) → plano a
            # INSERIR (o caminho que quebrou no teste do autor, v02 → v03: `usadas` sumiu na refatoração; a
            # remoção pura não passava por ele)
            troca = copy.deepcopy(v1)
            primeiro = next(sg for sg in troca["segments"] if not sg["is_audio"] and not sg["is_gap"]
                            and not sg.get("is_transition"))
            primeiro["source_start_frames"] = int(primeiro.get("source_start_frames") or 0) + 5000
            kt = arquivo(troca, "troca.json")
            st, r = chamar("POST", "/receber/atualizar", {"antiga": {"avulso": k1}, "nova": {"avulso": kt},
                                                          "trabalho": trab, "contagem": api})
            # sem mídia no teste, o plano cai nos avisos ("sem a mídia nesta máquina") — mas passa pelo
            # mesmo laço que quebrou
            ok("⭐ com plano novo a inserir (take trocado), a execução responde e trata o plano",
               (st, bool(r.get("inserir")) or any("sem a mídia" in a for a in r.get("avisos", [])), r.get("erro")),
               (200, True, None))
            st, r = chamar("POST", "/receber/atualizada", {"nova": {"avulso": k2}, "registro": registro,
                                                           "timeline": {"uid": "tl-solta", "nome": "SOLTA"}})
            ok("⭐ depois de atualizar, a v2 do disco vira a partida da timeline (Carta guardada aqui)",
               (st, (dados / "partidas" / f"{r['partida']['id']}.carta").is_file(), r["partida"]["familia"]),
               (200, True, "avid"))
            sug = s.partidas_para(timeline={"uid": "tl-solta", "nome": "SOLTA"})["partidas"]
            ok("⭐ …e a próxima atualização desta timeline a sugere primeiro",
               (sug[0]["id"], sug[0]["motivo"]), (r["partida"]["id"], "desta_timeline"))
            doc_aaf = json.loads((dados / "partidas" / f"{r['partida']['id']}.carta").read_text(encoding="utf-8"))
            pa = P.guardar_doc(doc_aaf, {}, {"uid": "tl-aaf"}, "aaf")
            st, r = chamar("POST", "/receber/comparar", {"antiga": {"partida": pa["id"]}, "nova": {"avulso": k2}})
            ok("⭐ formatos diferentes (AAF antiga, Carta nova): recusado com o motivo",
               (st, "mesmo formato" in r.get("erro", "")), (409, True))
            st, r = chamar("POST", "/receber/comparar", {"antiga": {"avulso": k1}, "nova": {"avulso": k2}})
            ok("sem a timeline de trabalho, o comparar não confere o encaixe (nem exige)",
               (st, "encaixe" in r), (200, False))

            print("\n── 5d. o serviço REINICIOU entre a atualização e o registro (revisão 2026-09-28) ──")
            import canais as C
            C.guardar_canal_na_maquina("cor", str(canal))
            s2 = R.SessaoReceber()                 # sem procura, sem chaves de arquivo: como ao subir
            r2 = s2.atualizada({"envio": ids["v2"]}, {"uid": "tl-reinicio", "nome": "REINICIO"})
            ok("⭐ Carta do canal: o reenvio acha a Carta pelos canais da máquina e guarda a partida",
               r2["partida"]["timeline_uid"], "tl-reinicio")
            r3 = s2.atualizada({"avulso": k2}, {"uid": "tl-r2", "nome": "R2"}, registro=registro)
            ok("⭐ versão do disco: o registro vale com o serviço reiniciado (a Carta ficou em recebidos)",
               r3["partida"]["timeline_uid"], "tl-r2")
            try:
                s2.comparar_versoes({"avulso": k1}, {"avulso": k2})
                veio = None
            except LookupError as e:
                veio = str(e)
            ok("a chave de arquivo que o reinício apagou: recusa clara (409), não KeyError (500)",
               bool(veio) and "escolha o arquivo de novo" in veio, True)
            try:
                s2.atualizada({"avulso": k2}, {"uid": "x", "nome": "X"}, registro="99999999-9999-4999-8999-999999999999")
                veio = None
            except LookupError as e:
                veio = str(e)
            ok("registro que não existe mais: recusa clara (o painel não o reenvia para sempre)", bool(veio), True)

            print("\n── 5e. id repetido pela ponte, na sugestão da versão antiga ──")
            pa_a = P.guardar_doc(doc_aaf, {}, {"uid": "uid-repetido", "nome": "TL A"}, "avid")
            pa_b = P.guardar_doc(doc_aaf, {}, {"uid": "uid-repetido", "nome": "TL B"}, "avid")
            sug = s.partidas_para(timeline={"uid": "uid-repetido", "nome": "TL B"})["partidas"]
            ok("⭐ duas timelines com o mesmo id: a sugestão é a do par id + nome",
               (sug[0]["id"], sug[0]["motivo"]), (pa_b["id"], "desta_timeline"))
            ok("id repetido e nome que nenhuma tem: nenhuma sugestão forte (não chuta)",
               P.da_timeline("uid-repetido", "TL C"), [])
            ok("renomeada no Resolve, id único: o id ainda aponta",
               [x["id"] for x in P.da_timeline("tl-r2", "R2 RENOMEADA")], [r3["partida"]["id"]])
            assert pa_a

            print("\n── 5f. a limpeza de recebidos/ ──")
            import os as _os
            velho = dados / "Cache" / "recebidos" / "12345678-1234-4234-8234-123456789abc.drt"
            velho.write_bytes(b"x")
            _os.utime(velho, (1, 1))
            alheio = dados / "Cache" / "recebidos" / "nao-e-nosso.drt"
            alheio.write_bytes(b"x")
            _os.utime(alheio, (1, 1))
            n = R.limpar_recebidos()
            ok("⭐ apaga só o arquivo de passagem velho que o serviço escreveu",
               (n, velho.exists(), alheio.exists()), (1, False, True))

            # revisão 2026-09-28: depois de atualizar, a partida SUBSTITUÍDA sai da lista (a timeline dela
            # foi para o Backup; oferecê-la levaria a atualizar o backup)
            s.trazido(ids["v3"], True, timeline={"uid": "tl-uid-3", "nome": "SINTETICA 3"}, substitui=ids["v2"])
            ok("⭐ a partida substituída pela atualização sai das sugestões",
               sorted(x["id"] for x in P.listar() if x["id"] in ids.values()), sorted([ids["v1"], ids["v3"]]))

            print("\n── 6. as faixas em Ajustes ──")
            st, r = chamar("POST", "/ajustes/atualizar", {"faixas": [10, 80]})
            ok("gravar 10/80", r["faixas"], [10.0, 80.0])
            ok("…e a comparação usa", s.comparar_versoes({"partida": ids["v1"]}, {"envio": ids["v2"]})["faixas"], [10.0, 80.0])
            st, r = chamar("POST", "/ajustes/atualizar", {"faixas": [70, 20]})
            ok("fora de 0 < a < b ≤ 100: volta o de fábrica", r["faixas"], [25.0, 60.0])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
