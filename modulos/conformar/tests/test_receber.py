"""Magic Link, lado de quem RECEBE — o portão com token e a caixa da pasta combinada.

Rodar:

    .venv-win/Scripts/python tests/test_receber.py

- O token do arquivo abre SÓ `/receber/*`, só sem `Origin`, só se bater (ADR 0016).
- A caixa separa timelines de inserts, lista as Cartas inválidas sem quebrar, e não repete uma
  Carta copiada duas vezes.
- Preparar gera o DRT temporário (timeline inteira, ou só o insert com o nome
  `INSERT PARA VFX — …`), e ⛔ nenhum caminho de dentro da Carta que seja UNC é tocado.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"),
                str(RAIZ / "tests")]

from api.portao import Recusa, portao  # noqa: E402
from carta_aberta.writer import build_carta_aberta  # noqa: E402
from test_carta_ida_e_volta import leitura_sintetica, mid  # noqa: E402

TOKEN = "a" * 64


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 56 else f"{repr(obtido)[:53]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<64} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 1. o portão com o token do arquivo ──")

    def entra(rota, token=None, origin=None, sfs=None):
        return portao("127.0.0.1:7823", origin, sfs, None, rota, token=token, token_esperado=TOKEN)

    ok("script com token certo em /receber/caixa", entra("/receber/caixa", TOKEN), None)
    ok("token errado", entra("/receber/caixa", "b" * 64), Recusa.SEM_CREDENCIAL)
    ok("sem token", entra("/receber/caixa"), Recusa.SEM_CREDENCIAL)
    ok("⭐ o token NÃO abre rota do painel do Avid", entra("/insert/coletar", TOKEN), Recusa.SEM_CREDENCIAL)
    ok("⭐ página web com o token certo continua barrada",
       entra("/receber/caixa", TOKEN, origin="https://site.com"), Recusa.ORIGEM_WEB)
    ok("serviço sem token publicado recusa o script",
       portao("127.0.0.1:7823", None, None, None, "/receber/caixa", token=TOKEN, token_esperado=None),
       Recusa.SEM_CREDENCIAL)
    ok("o painel (same-origin) segue entrando sem token", entra("/insert/coletar", sfs="same-origin"), None)

    print("\n── 2. a caixa e o DRT temporário ──")
    import sessao_receber as R

    with tempfile.TemporaryDirectory() as tmp:
        # O canal Cor, visto pela ilha da COR: ela lê a caixa `para-cor`.
        dados, canal = Path(tmp) / "dados", Path(tmp) / "magic-cor"
        combinada = canal / "para-cor"
        dados.mkdir()
        combinada.mkdir(parents=True)
        cfg = {"cor": str(canal)}
        leitura = leitura_sintetica()
        # ⛔ um AMA apontando para UNC: nunca pode ser tocado
        arquivos = {mid(2): r"\\host-do-atacante\c$\B001_C011.mov"}

        def escrever(nome, envio, selecao=None):
            build_carta_aberta(leitura, [], str(combinada / nome), "SINTETICA", "para a cor",
                               arquivos=arquivos, envio=envio, selecao=selecao)

        id_tl = "11111111-1111-4111-8111-111111111111"
        id_vfx = "22222222-2222-4222-8222-222222222222"
        escrever("SINTETICA__11111111.carta.json",
                 {"id": id_tl, "tipo": "timeline", "remetente": {"maquina": "EDIT-02"},
                  "enviado_em": "2026-09-24T15:00:00-03:00"})
        escrever("SINTETICA__22222222.carta.json",
                 {"id": id_vfx, "tipo": "insert_vfx", "remetente": {"maquina": "EDIT-02"},
                  "enviado_em": "2026-09-24T16:40:00-03:00"},
                 selecao=[{"track": 1, "timeline_tc_in": "00:00:05:00",
                           "timeline_tc_out": "00:00:06:00", "mob_id": mid(3)}])
        (combinada / "copia de SINTETICA__11111111.carta.json").write_bytes(
            (combinada / "SINTETICA__11111111.carta.json").read_bytes())
        (combinada / "estragada.carta.json").write_text("{ nao é json", encoding="utf-8")
        (combinada / "SINTETICA__11111111.carta.json.parcial").write_text("{}", encoding="utf-8")
        (combinada / "sub").mkdir()
        (combinada / "sub" / "escondida.carta.json").write_text("{}", encoding="utf-8")
        # o AppleDouble que um Mac grava ao lado de cada envio numa pasta de rede (4 KB de xattr)
        (combinada / "._SINTETICA__22222222.carta.json").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 4092)

        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados), \
                mock.patch("media.pmr.indice_de", lambda *_a, **_k: SimpleNamespace(por_arquivo={})):
            s = R.SessaoReceber()
            def pendentes(cx, tipo=None):
                return [e for e in cx["envios"] if not e["importado"]
                        and (tipo is None or (e["tipo"] == "timeline") == (tipo == "timeline"))]

            vazio = s.caixa({})
            ok("sem canal conectado, todos os canais aparecem desconectados",
               [(c["setor"], c["conectado"]) for c in vazio["canais"]], [("cor", False), ("vfx", False)])
            ok("…e nenhum envio", vazio["envios"], [])
            cx = s.caixa(cfg)
            ok("uma timeline e um insert", (len(pendentes(cx, "timeline")), len(pendentes(cx, "insert"))),
               (1, 1))
            ok("⭐ a cópia da mesma Carta não aparece duas vezes", len(pendentes(cx, "timeline")), 1)
            ok("a estragada vai para 'invalidas', sem quebrar a caixa (o ._ do Mac nem entra)",
               [i["arquivo"] for i in cx["invalidas"]], ["estragada.carta.json"])
            ok("o .parcial e a subpasta são ignorados",
               any("parcial" in i.get("arquivo", "") or "escondida" in i.get("arquivo", "")
                   for i in cx["envios"] + cx["invalidas"]), False)
            ok("o insert diz quantos clipes", pendentes(cx, "insert")[0]["clipes_insert"], 1)
            ok("o comentário do editor vem junto", pendentes(cx, "timeline")[0]["comentario"], "para a cor")
            ok("⭐ a linha diz o canal e o sentido (da Edição para a Cor)",
               {(e["canal"], e["de"], e["para"]) for e in cx["envios"]}, {("cor", "edicao", "cor")})

            tocados: list[str] = []
            real = os.path.isfile

            def espiao(c):
                tocados.append(str(c))
                return real(c)

            with mock.patch("os.path.isfile", espiao):
                p = s.preparar(id_tl)
            ok("preparar a timeline gera o DRT", Path(p["drt"]).is_file(), True)
            ok("o DRT é nomeado pelo id, nunca pela Carta", Path(p["drt"]).name, f"{id_tl}.drt")
            ok("vai para a pasta 'De Lá Pra Cá' no Resolve", p["pasta_no_resolve"], "De Lá Pra Cá")
            # ⭐ Mídia primeiro, timeline depois (2026-09-26): a lista que a casca pré-importa.
            lista = json.loads(Path(p["drt"]).with_suffix(".midias.json").read_text(encoding="utf-8"))
            ok("⭐ ao lado do DRT, a lista das mídias desta máquina", lista["drt"], f"{id_tl}.drt")
            ok("…só arquivos que existem aqui, e o painel sabe quantos",
               (all(os.path.isfile(m) for m in lista["midias"]), len(lista["midias"])),
               (True, p["midias"]))
            # A régua da lista com arquivos de verdade (o cenário acima não tem mídia online).
            import sessao_receber as SR
            online = Path(tmp) / "A001_C003.braw"
            online.write_bytes(b"x")
            casados = [{"matched_path": str(online)}, {"matched_path": str(online)},
                       {"matched_path": str(Path(tmp) / "B001.mov"), "offline": True},
                       {"matched_path": str(Path(tmp) / "sumiu.wav")},
                       {"matched_path": str(online), "rejected": True}, None]
            alvo = Path(tmp) / "22222222-2222-4222-8222-222222222222.drt"
            ok("⭐ a lista: o online uma vez só; offline, sumido e rejeitado ficam fora",
               (SR._gravar_midias(alvo, casados),
                json.loads(alvo.with_suffix(".midias.json").read_text(encoding="utf-8"))["midias"]),
               (1, [os.path.abspath(online)]))
            # ⛔ O WAV/AIF de 1–2 canais NÃO é pré-importado (duplicava no pool, 2026-09-27):
            # vai para `depois`, e a casca move o item do DRT. O de 3+ canais segue pré-importado.
            import struct as _st

            def wav(nome, canais, antes=b""):
                fmt = _st.pack("<HHIIHH", 1, canais, 48000, 48000 * 3 * canais, 3 * canais, 24)
                corpo = b"WAVE" + antes + b"fmt " + _st.pack("<I", len(fmt)) + fmt + b"data" + _st.pack("<I", 0)
                arq = Path(tmp) / nome
                arq.write_bytes(b"RIFF" + _st.pack("<I", len(corpo)) + corpo)
                return os.path.abspath(arq)

            bext = b"bext" + _st.pack("<I", 603) + b"\0" * 603 + b"\0"   # tamanho ímpar: o byte de pad
            mono, estereo, sd = wav("fx.wav", 1), wav("trilha.wav", 2, bext), wav("SD-T001.WAV", 4, bext)
            ok("o cabeçalho diz os canais (com bext ímpar antes do fmt)",
               [SR._canais_de_audio(x) for x in (mono, estereo, sd, str(online))], [1, 2, 4, None])
            SR._gravar_midias(alvo, [{"matched_path": x} for x in (online, mono, estereo, sd)])
            lista = json.loads(alvo.with_suffix(".midias.json").read_text(encoding="utf-8"))
            ok("⭐ mono e estéreo vão para 'depois'; vídeo e som direto de 4 canais, pré-importados",
               (lista["midias"], lista["depois"]), ([os.path.abspath(online), sd], [mono, estereo]))
            # a rota do .prproj: o som de 3+ canais também duplicou (R04, Resolve 19.1.4, 2026-10-19) → todo som depois
            SR._gravar_midias(alvo, [{"matched_path": x} for x in (online, mono, estereo, sd)], som_depois=True)
            lista = json.loads(alvo.with_suffix(".midias.json").read_text(encoding="utf-8"))
            ok("⭐ .prproj: só o vídeo pré-importado; todo som (o de 4 canais também) vai para 'depois'",
               (lista["midias"], lista["depois"]), ([os.path.abspath(online)], [mono, estereo, sd]))
            ok("⛔ o UNC da Carta NÃO foi tocado", [t for t in tocados if "atacante" in t], [])

            v = s.preparar(id_vfx)
            ok("⭐ o insert chega com o nome que o EDITOR deu (o programa não inventa)",
               v["nome"], "SINTETICA")
            ok("…vai para a pasta Inserts", v["pasta_no_resolve"], "Inserts")
            ok("…e só com o clipe escolhido", v["clipes"], 1)

            for ruim in ("../../x", "", "nao-e-uuid"):
                try:
                    s.preparar(ruim)
                    ok(f"id inválido {ruim!r} recusado", "aceitou", "recusou")
                except ValueError:
                    ok(f"id inválido {ruim!r} recusado", "recusou", "recusou")
            try:
                s.preparar("33333333-3333-4333-8333-333333333333")
                ok("id que não está na pasta", "aceitou", "LookupError")
            except LookupError:
                ok("id que não está na pasta", "LookupError", "LookupError")

            ok("a caixa diz de que programa veio", pendentes(cx, "timeline")[0]["aplicativo"],
               "Avid Media Composer")

            r = s.trazido(id_tl, True, "importado")
            ok("⭐ o trazido desce para importado/timelines",
               Path(r["arquivado"]).parent, combinada / "importado" / "timelines")
            cx = s.caixa(cfg)
            ok("⭐ …sai da fila, com a cópia junto", len(pendentes(cx, "timeline")), 0)
            ok("…e aparece como já importado, marcado nesta máquina",
               [(i["id"], bool(i["trazido_em"])) for i in cx["envios"] if i["importado"]],
               [(id_tl, True)])
            ok("o insert continua na fila, novo",
               [(i["id"], i["trazido_em"]) for i in pendentes(cx, "insert")], [(id_vfx, None)])
            ok("o registro é local", (dados / "recebidos.jsonl").is_file(), True)
            ok("'De novo' traz do importado", Path(s.preparar(id_tl)["drt"]).is_file(), True)
            ok("o .parcial não foi tocado",
               (combinada / "SINTETICA__11111111.carta.json.parcial").is_file(), True)

            print("\n── 2b. os dois sentidos do canal, e a rede que recusa o mover ──")
            # A Cor devolve uma timeline para a Edição: ela cai em `para-edicao`.
            id_volta = "44444444-4444-4444-8444-444444444444"
            build_carta_aberta(leitura, [], str(canal / "para-edicao" / "VOLTA__44444444.carta.json"),
                               "CORRIGIDA", None, envio={"id": id_volta, "tipo": "timeline",
                                                         "canal": "cor", "de": "cor", "para": "edicao"})
            cx = s.caixa(cfg)
            ok("⭐ sem papel: a mesma tabela mostra os dois sentidos do canal",
               sorted((e["de"], e["para"]) for e in pendentes(cx)),
               [("cor", "edicao"), ("edicao", "cor")])
            ok("o que veio da Cor é identificado pela CAIXA, não pelo que a Carta diz",
               next(e["de"] for e in cx["envios"] if e["id"] == id_volta), "cor")
            with mock.patch.object(R.canais, "arquivar", side_effect=PermissionError(13, "Acesso negado")):
                r = s.trazido(id_vfx, True, "importado")
            ok("⭐ rede recusou mover: a timeline já entrou, o aviso explica",
               (r["arquivado"], "fica na fila" in r.get("aviso", "")), (None, True))
            ok("…e a Carta continua na fila", len(pendentes(s.caixa(cfg), "insert")), 1)
            ok("Trazer que falhou não arquiva", s.trazido(id_vfx, False, "erro")["arquivado"], None)
            r = s.trazido(id_volta, True, "importado")
            ok("o que veio da Cor desce para o importado da caixa DELA (para-edicao)",
               Path(r["arquivado"]).parent, canal / "para-edicao" / "importado" / "timelines")

            print("\n── 3. o andamento do Trazer (a barra do painel), cancelar, um por vez ──")
            etapa_real = R.SessaoReceber._etapa
            vistas: list[str] = []

            def espia(self, etapa, *a, **k):
                vistas.append(etapa)
                return etapa_real(self, etapa, *a, **k)

            with mock.patch.object(R.SessaoReceber, "_etapa", espia):
                s.preparar(id_tl)
            ok("as etapas passam na ordem",
               # (a `baselight` é só do destino Baselight, 2026-11-22: o Trazer para o Resolve não passa por ela)
               [e for i, e in enumerate(vistas) if e not in vistas[:i]], [e for e in R.ETAPAS if e != "baselight"])
            ok("no fim o andamento fica inativo", s.progresso(), {"ativo": False})

            def cancela_ao_casar(self, etapa, *a, **k):
                if etapa == "casando":
                    self.cancelar()
                return etapa_real(self, etapa, *a, **k)

            with mock.patch.object(R.SessaoReceber, "_etapa", cancela_ao_casar):
                try:
                    s.preparar(id_tl)
                    ok("⭐ cancelar interrompe o Trazer", "terminou", "Cancelado")
                except R.Cancelado:
                    ok("⭐ cancelar interrompe o Trazer", "Cancelado", "Cancelado")
            ok("depois de cancelar, o andamento fica inativo", s.progresso(), {"ativo": False})
            ok("cancelar com nada rodando devolve False", s.cancelar(), False)
            ok("o Trazer seguinte funciona (a flag não ficou presa)",
               Path(s.preparar(id_tl)["drt"]).is_file(), True)
            s._progresso = {"ativo": True}
            try:
                s.preparar(id_tl)
                ok("um Trazer por vez", "aceitou", "recusou")
            except RuntimeError:
                ok("um Trazer por vez", "recusou", "recusou")
            s._progresso = {"ativo": False}

            print("\n── 4. Abrir arquivo… (Carta solta e bin do Avid, fora da pasta) ──")
            solta = Path(tmp) / "solta"
            solta.mkdir()
            # A Carta do "Daqui Pra Lá" manual não tem `envio`: é uma timeline.
            build_carta_aberta(leitura, [], str(solta / "MANUAL.json"), "MANUAL", None,
                               arquivos=arquivos)
            linhas_antes = (dados / "recebidos.jsonl").read_text(encoding="utf-8").count("\n")
            a = s.abrir(str(solta / "MANUAL.json"))
            ok("a Carta solta é reconhecida", (a["tipo"], a["nome"]), ("carta", "MANUAL"))
            # Redesenho de 2026-10-05 (carregar não é importar): o cartão mostra a leitura rápida.
            # A conta à mão: V1 = 50+50+25+25+25 quadros (a transição se sobrepõe, não soma) = 7 s a
            # 25 fps; planos = os 4 de vídeo com mídia (sem o vazio e a transição); A1 e A2.
            ok("⭐ a leitura rápida vem no abrir (duração, taxa, trilhas, planos)",
               {k: a[k] for k in ("duracao", "fps", "video", "audio", "planos")},
               {"duracao": "00:00:07:00", "fps": 25.0, "video": 1, "audio": 2, "planos": 4})
            # O arquivo SOLTO na área do bloco 1 chega à rota com `caminho` (sem abrir o seletor).
            from api import rotas
            ctx_solto = lambda c: SimpleNamespace(json=lambda: {"caminho": c},  # noqa: E731
                                                  servico=SimpleNamespace(receber=s))
            st, r = rotas.receber_abrir(ctx_solto(str(solta / "MANUAL.json")))
            ok("⭐ soltar: o caminho abre direto, sem o seletor", (st, r.get("tipo")), (200, "carta"))
            st, r = rotas.receber_abrir(ctx_solto(str(solta / "nao-existe.aaf")))
            ok("⛔ soltar um arquivo que não existe: 400 com o motivo", (st, "erro" in r), (400, True))
            st, r = rotas.receber_abrir(ctx_solto("relativo/x.aaf"))
            ok("⛔ soltar um caminho relativo: 400", st, 400)
            tocados.clear()
            with mock.patch("os.path.isfile", espiao):
                p = s.preparar_avulso(a["chave"])
            ok("…e vira DRT", Path(p["drt"]).is_file(), True)
            ok("…com nome de uuid, na pasta recebidos (a casca só importa esse)",
               bool(R.RE_ID.match(Path(p["drt"]).stem)) and Path(p["drt"]).parent.name, "recebidos")
            ok("…na pasta 'De Lá Pra Cá'", p["pasta_no_resolve"], "De Lá Pra Cá")
            ok("⛔ o UNC da Carta solta NÃO foi tocado", [t for t in tocados if "atacante" in t], [])
            ok("⭐ o Trazer avulso não marca nada na caixa",
               (dados / "recebidos.jsonl").read_text(encoding="utf-8").count("\n"), linhas_antes)
            p2 = s.preparar_avulso(a["chave"])
            ok("trazer de novo gera OUTRO DRT (não sobrescreve o que o Resolve leu)",
               p2["drt"] != p["drt"], True)

            ins = s.abrir(str(combinada / "SINTETICA__22222222.carta.json"))
            ok("um insert aberto à mão vai para Inserts, só com o escolhido",
               (s.preparar_avulso(ins["chave"])["pasta_no_resolve"],
                s.preparar_avulso(ins["chave"])["clipes"]), ("Inserts", 1))

            (solta / "montagem.aaf").write_bytes(b"x")
            (solta / "notas.txt").write_text("x", encoding="utf-8")
            for rotulo, alvo in (("um AAF que não é AAF: recusado com o motivo", solta / "montagem.aaf"),
                                 ("extensão que não abro", solta / "notas.txt"),
                                 ("arquivo que não existe", solta / "nao.json"),
                                 ("a Carta estragada", combinada / "estragada.carta.json"),
                                 ("caminho relativo", Path("MANUAL.json"))):
                try:
                    s.abrir(str(alvo))
                    ok(f"{rotulo}: recusado", "aceitou", "ValueError")
                except ValueError:
                    ok(f"{rotulo}: recusado", "ValueError", "ValueError")
            for ruim, erro in (("../x", ValueError), ("33333333-3333-4333-8333-333333333333", LookupError)):
                try:
                    s.preparar_avulso(ruim)
                    ok(f"chave {ruim[:12]!r} recusada", "aceitou", erro.__name__)
                except erro:
                    ok(f"chave {ruim[:12]!r} recusada", erro.__name__, erro.__name__)

            # A bin: a leitura da `.avb` é a de `test_avb_segmentos`; aqui, o encanamento.
            bin_avb = solta / "CENAS.avb"
            bin_avb.write_bytes(b"x")
            seqs = [{"mob_id": mid(90), "nome": "CORTE v2", "duracao": "00:01:00:00"},
                    {"mob_id": mid(91), "nome": "CORTE v3", "duracao": "00:01:02:00"}]
            pedidas: list = []

            def ler_bin(caminho, mob_id=None, nome=None):
                pedidas.append(mob_id)
                lida = leitura_sintetica()
                # ⛔ o AMA que a bin aponta é UNC: não pode ser tocado
                lida["masters"][mid(2)]["caminho_na_bin"] = r"\\host-do-atacante\x\B001_C011.mov"
                return lida

            with mock.patch.object(R, "_sequencias_da_bin", lambda _p: seqs), \
                    mock.patch("avb_bin.segmentos.ler_timeline_de_arquivo", ler_bin):
                b = s.abrir(str(bin_avb))
                ok("a bin lista as sequências", [x["nome"] for x in b["sequencias"]],
                   ["CORTE v2", "CORTE v3"])
                tocados.clear()
                with mock.patch("os.path.isfile", espiao):
                    pb = s.preparar_avulso(b["chave"], mid(91))
                ok("a sequência escolhida é a que se lê", pedidas, [mid(91)])
                ok("a bin vira DRT", Path(pb["drt"]).is_file(), True)
                ok("…com o nome da sequência", pb["nome"], leitura["composition_name"])
                ok("⛔ o UNC da bin NÃO foi tocado", [t for t in tocados if "atacante" in t], [])
            with mock.patch.object(R, "_sequencias_da_bin", lambda _p: []):
                try:
                    s.abrir(str(bin_avb))
                    ok("bin sem sequência: recusada", "aceitou", "ValueError")
                except ValueError:
                    ok("bin sem sequência: recusada", "ValueError", "ValueError")
            try:
                R._sequencias_da_bin(bin_avb)
                ok("bin estragada: recusa clara, não 500", "aceitou", "ValueError")
            except ValueError:
                ok("bin estragada: recusa clara, não 500", "ValueError", "ValueError")
            ok("o andamento fica inativo depois do avulso", s.progresso(), {"ativo": False})

            real = os.environ.get("DLPC_BIN_REAL")
            if real and Path(real).is_file():
                br = s.abrir(real)
                ok("bin real: tem sequências", len(br["sequencias"]) > 0, True)
                pr = s.preparar_avulso(br["chave"], br["sequencias"][0]["mob_id"])
                ok("bin real: a primeira sequência vira DRT", Path(pr["drt"]).is_file(), True)
            else:
                print("  PULADO — defina DLPC_BIN_REAL=<caminho de uma .avb> para abrir uma bin real")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
