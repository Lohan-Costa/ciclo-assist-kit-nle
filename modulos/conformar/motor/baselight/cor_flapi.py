"""A cor da scene do colorista na scene NOVA (atualizar corte, etapa 5; decisões do autor de 2026-11-22). Roda no python
da FilmLight (o que tem a `flapi`), chamado por `enviar.levar_a_cor`. Entrada (stdin, JSON):

    {"nova": "host:job:scene", "colorista": "host:job:scene", "blscene": "<a scene do colorista exportada>",
     "ciclo": {"<ShotId da nova>": "<o BLG que o Ciclo gravou nele>"}, "so_ler": false}

(`casar_por` só para o laboratório: um Multi-Paste errado de propósito prova a correção da conferência.)

1. lê a scene do colorista (só leitura): cada plano (arquivo, fonte, gravação, camada 0) e os markers; as CAMADAS do
   colorista de cada plano vêm do `.blscene` (`camadas.do_blscene`: o plano mascarado — multi-input — não se lê pela
   FLAPI, e o de uma trilha de baixo viria com a pilha de quem está por cima); as do Ciclo ficam de fora (o nome);
2. ``so_ler``: devolve só isso (para os cortes do colorista, ANTES do conform da v2);
3. Multi-Paste na scene nova, casando por ARQUIVO + TC (BL09: 7/7; só pelo nome erra calado);
4. a CONFERÊNCIA do Ciclo, plano a plano: a pilha da nova tem de ser = as faixas do Ciclo DA V2 (`ciclo`, ou a pilha do
   conform) + as do colorista (`camadas.juntar`); o que discordar é REFEITO (`delete_all_layers` + `apply_blg_payload`).
   ⛔ MEDIDO (PRODC, 2026-11-23): o Multi-Paste cola a pilha inteira do colorista "Above" — com o Retime/Transform/
   composição do Ciclo da v1: efeitos DOBRADOS; a correção antiga copiava o BLG inteiro da v1: efeitos VELHOS;
5. os markers do colorista no mesmo quadro de FONTE (`atualizar.mover_marcas`); os grupos.

Saída (stdout, a última linha): JSON com os planos, os markers movidos/perdidos e o log do Multi-Paste.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flapi  # noqa: E402

import atualizar as A  # noqa: E402
import camadas as CA  # noqa: E402

pedido = json.load(sys.stdin)
c = flapi.Connection("localhost")
c.connect()


def _abrir(caminho, leitura):
    s = c.Scene.open_scene(c.Scene.parse_path(caminho), {flapi.OPENFLAG_READ_ONLY} if leitura else set())
    s.wait_until_open()
    return s


def _ler(sh):
    """O texto do BLG do plano, ou None (multi-input: "Allow Multi-Input BLGs" não está ligado)."""
    try:
        payload = sh.get_blg_payload()          # UMA leitura por plano (ler duas vezes já travou a FLAPI, 7.0.3)
    except flapi.FLAPIException:
        return None
    return A._cru(payload) if payload else ""


def _planos(s):
    out = []
    for info in s.get_shot_ids():
        sh = s.get_shot(info.ShotId)
        try:
            try:
                sd = sh.get_sequence_descriptor()
                arq = sd.get_full_filename_with_F() if sd else ""
            except flapi.FLAPIException:            # offline / sem mídia
                arq = ""
            try:
                res = sh.get_blg_resources() or ""
            except flapi.FLAPIException:
                res = ""
            out.append({"id": info.ShotId, "arquivo": arq, "rec": [info.StartFrame, info.EndFrame],
                        "src": [sh.get_src_start_frame(), sh.get_src_end_frame()], "entrada": _camada0(sh), "res": res})
        finally:
            sh.release()
    return out


def _camada0(sh):
    """O que o colorista muda na CAMADA 0 (fora do BLG das camadas): o espaço de cor de entrada e o decode do RAW
    (ISO, balanço… — o BRAW, o R3D). ⛔ MEDIDO (BL09, 7.0.3, 2026-11-22): o Multi-Paste `StackOnly` perdia a entrada do
    colorista e a conferência pela impressão do BLG não via (7/7 com o S2 errado)."""
    try:
        out = {"espaco": sh.get_input_colour_space()}
    except flapi.FLAPIException:             # plano sem mídia (título, preto): "attempt to read a NULL keyed by
        return {"espaco": None, "decode": {}}  # grsr_InputColourSpace" (PRODUCAO-A, 2026-11-22)
    try:
        out["decode"] = sh.get_decode_parameters() or {}
    except flapi.FLAPIException:             # "No decode parameters available for this shot" (ProRes, DNx…)
        out["decode"] = {}
    return out


def _marcas(s):
    out = []
    for i in s.get_mark_ids():
        mk = s.get_mark(i)
        try:
            out.append({"quadro": mk.get_record_frame(), "nota": mk.get_note_text() or "",
                        "categoria": mk.get_category()})
        finally:
            mk.release()
    return out


def _do_colorista(v1, fps):
    """As faixas do colorista de cada plano da v1 (do `.blscene`; o plano que não se achar lá: do BLG, se ele se ler)."""
    db = pedido.get("blscene")
    cols = CA.do_blscene(db, v1, fps) if db and os.path.isfile(db) else [None] * len(v1)
    sc = None
    for p, col in zip(v1, cols):
        if col is None:
            if sc is None:
                sc = _abrir(pedido["colorista"], True)
            sh = sc.get_shot(p["id"]) if p["id"] in {i.ShotId for i in sc.get_shot_ids()} else None
            texto = _ler(sh) if sh else None
            if sh:
                sh.release()
            col = CA.do_blg(texto) if texto else ([] if texto == "" else None)
            p["de_onde"] = "blg" if col is not None else "nenhum"
        else:
            p["de_onde"] = "blscene"
        p["col"] = col or []
        p["ilegivel"] = col is None
        p["cor"] = CA.impressao(col)
        p["kf"] = CA.keyframes(col)
        p["camadas"] = [{"chave": CA.impressao([x]), "nome": x["nome"]} for x in (col or [])]
    if sc is not None:
        sc.close_scene()


try:
    try:
        sc = _abrir(pedido["colorista"], True)
    except flapi.FLAPIException as e:
        # ⛔ MEDIDO (7.0.3, 2026-11-22): com mudança NÃO SALVA na scene aberta na interface, a leitura de fora é recusada
        # ("Scene must be opened read/write to recover or discard autosave data"). Abrir para escrita recuperaria ou
        # descartaria o trabalho do colorista: nunca. Ele salva (⌘S) e o Ciclo tenta de novo.
        print(json.dumps({"erro": "nao_salva" if "autosave" in str(e) else "abrir", "detalhe": str(e)},
                         ensure_ascii=False))
        sys.exit(0)
    try:
        v1, marcas = _planos(sc), _marcas(sc)
        fps1 = float(sc.get_working_frame_rate() or 24)
        # os GRUPOS do colorista, pelo índice do plano na v1 (o id do plano não vale noutra scene)
        idx = {p["id"]: k for k, p in enumerate(v1)}
        grupos_v1 = {g: [idx[i] for i in (sc.get_group(g) or []) if i in idx] for g in (sc.get_groups() or [])}
    finally:
        sc.close_scene()
    _do_colorista(v1, fps1)
    if pedido.get("so_ler"):
        print(json.dumps({"v1": [{k: p[k] for k in ("arquivo", "src", "rec", "cor")} for p in v1]}, ensure_ascii=False))
        sys.exit(0)

    s = _abrir(pedido["nova"], False)
    try:
        fps = float(s.get_working_frame_rate() or 24)
        v2 = _planos(s)
        # a BASE de cada plano da v2 (ANTES do Multi-Paste): o BLG que o Ciclo gravou nele (efeitos, máscaras) ou, sem
        # efeito, a pilha do conform — que se lê (sem composição não há multi-input)
        ciclo = pedido.get("ciclo") or {}
        for p in v2:
            arq = ciclo.get(str(int(p["id"])))
            if arq and os.path.isfile(arq):
                p["base"], p["base_de"] = open(arq, encoding="latin1").read(), "ciclo"
            else:
                sh = s.get_shot(p["id"])
                try:
                    p["base"], p["base_de"] = _ler(sh), "conform"
                finally:
                    sh.release()
                # ⛔ o plano de uma trilha de BAIXO lê a pilha de quem está por cima no 1º quadro (BL11): com faixa do
                #    Ciclo na pilha lida de um plano em que o Ciclo não gravou, ela não é dele — não serve de base
                if p["base"] and any(fx["ciclo"] for fx in CA.faixas(p["base"])):
                    p["base"] = None
            p["base"] = p["base"] or None
            p["base_ciclo"] = CA.impressao_do_ciclo(p["base"]) if p["base"] else None

        # 3. o Multi-Paste (a ferramenta do Baselight, que o colorista conhece; o log dele vai ao resumo)
        ms = flapi.MultiPasteSettings(
            Source="MultipleScenes", SourceScenes=[pedido["colorista"]], MatchBy=pedido.get("casar_por") or ["Filename", "Timecode"],
            # a camada 0 também (o espaço de entrada; o som não): medido no BL09, a mídia e os pontos ficam iguais
            MatchQuality="ExactMatch", PasteGrades=1, LayerZeroBehaviour="LayerZeroAndStack", LayerZeroOverwrite=1,
            LayerZeroAudio=0, InputColourSpace=1, SourceShots="CopyAll",
            DestShots="OverwriteAll", DetectGradeChanges=0, PasteLocation="Above",
            # ⛔ MEDIDO (PRODUCAO-A, 2026-11-22): com MaintainTracks=1 numa scene vinda do AAF (várias trilhas) o
            # Multi-Paste diz "Grades pasted onto 99 shots" e NÃO cola nada (a cor ia para uma trilha que a v2 não tem)
            MaintainTracks=0, PasteMetadata=0,
            PasteGroups=0)
        mp = c.MultiPaste.create()
        s.start_delta("Ciclo Assist: a cor da scene do colorista (Multi-Paste)")
        try:
            colados = mp.multi_paste(s, ms, [i.ShotId for i in s.get_shot_ids()])
            s.end_delta()
        except flapi.FLAPIException as e:
            s.cancel_delta()
            colados, erro_mp = -1, str(e)
        else:
            erro_mp = ""
        log_mp = [{"estado": getattr(x, "Status", ""), "texto": getattr(x, "Summary", ""), "quadro": getattr(x, "Frame", None)}
                  for x in (mp.get_log() or [])]

        # 4. a conferência do Ciclo
        mapa = A.mapear(v2, v1)

        def _confere(texto, base_ciclo, col_esperado, kf_esperado):
            """A pilha lida = a base do Ciclo + o colorista esperado? None = não se lê (multi-input)."""
            if texto is None:
                return None
            col = CA.do_blg(texto)
            return (CA.impressao_do_ciclo(texto) == base_ciclo and CA.impressao(col) == CA.impressao(col_esperado)
                    and A.keyframes_iguais(CA.keyframes(col), kf_esperado))

        def _refazer(sh, p, col, mais, res):
            novo = CA.juntar(p["base"], col, CA.deslocar_chaves, mais)
            sh.delete_all_layers()
            sh.apply_blg_payload(A._gravar(novo), res or p["res"])

        s.start_delta("Ciclo Assist: conferência da cor (atualizar corte)")
        planos = []
        esperado = []                      # (colorista esperado, keyframes esperados) de cada plano da v2
        for p, m in zip(v2, mapa):
            alvo = v1[m["v1"]] if m["v1"] is not None else None
            col = alvo["col"] if alvo else []
            estado = "cor do colorista" if alvo and col else "sem cor"
            aviso = m["aviso"]
            # a cor ANIMADA: os keyframes do colorista presos à FONTE (o plano da v2 pode começar noutra)
            desloc = (alvo["src"][0] - p["src"][0]) / fps if alvo else 0.0
            kf_esp = [[t + desloc for t in curva] for curva in alvo["kf"]] if alvo else []
            esperado.append((col, kf_esp))
            notas = [x["aviso"] for x in col if x.get("aviso")]
            # a nota de LEITURA não vai ao aviso agora: a conferência pela scene exportada (`enviar.conferir_pela_scene`)
            # ainda pode confirmar o plano — só se ela não confirmar a nota vira aviso (e marker)
            leitura = ""
            if alvo and alvo["ilegivel"]:
                leitura = ("a pilha do colorista neste plano não se leu (nem pelo .blscene): a cor ficou a do "
                           "Multi-Paste, sem conferência")
            elif p["base"] is None:
                leitura = "a pilha deste plano na v2 não se lê e o Ciclo não a gravou: a cor ficou a do Multi-Paste"
            else:
                sh = s.get_shot(p["id"])
                try:
                    ok = _confere(_ler(sh), p["base_ciclo"], col, kf_esp)
                    if not ok:                     # errado ou ilegível (a composição da v2): refaz pela base
                        _refazer(sh, p, col, desloc, alvo["res"] if alvo else "")
                        estado = "corrigida" if alvo and col else "limpa"
                finally:
                    sh.release()
            if notas:
                aviso = " — ".join([aviso] + notas) if aviso else " — ".join(notas)
            # a CAMADA 0 do colorista (o espaço de entrada, o decode do RAW): o mesmo arquivo, então vale igual
            # ⛔ LIDA DE NOVO aqui: a correção pelo BLG (`apply_blg_payload`) MEXE no decode — tirou o `fiso` (ISO) de dois
            #    BRAW da PRODUCAO-A (2026-11-22) que o Multi-Paste tinha trazido certo
            camada0 = ""
            if alvo:
                sh = s.get_shot(p["id"])
                try:
                    agora = _camada0(sh)
                    if agora != alvo["entrada"]:
                        if alvo["entrada"]["espaco"] and agora["espaco"] != alvo["entrada"]["espaco"]:
                            sh.set_input_colour_space(alvo["entrada"]["espaco"])
                        if alvo["entrada"]["decode"] and agora["decode"] != alvo["entrada"]["decode"]:
                            sh.set_decode_parameters(alvo["entrada"]["decode"])
                        camada0 = "corrigida"
                finally:
                    sh.release()
            planos.append({"inicio": p["rec"][0], "fim": p["rec"][1], "arquivo": os.path.basename(p["arquivo"]),
                           "estado": estado, "motivo": m["motivo"], "aviso": aviso,
                           "de": alvo["rec"][0] if alvo else None, "camada0": camada0,
                           "entrada": (alvo["entrada"]["espaco"] if alvo else p["entrada"]["espaco"]),
                           "base": p["base_de"] if p["base"] is not None else "ilegível",
                           "cor_esperada": CA.impressao(col), "nota_leitura": leitura})

        # 4b. o LOOK (decisão do autor, 2026-11-22): o plano SEM cor (novo, take trocado) que cai dentro de uma faixa de
        #     cor sobre vários planos recebe SÓ essa camada — por cima das do Ciclo da v2; se não entrar, é dito.
        looks = A.looks_da_scene(v1)
        for i, (p, m) in enumerate(zip(v2, mapa)):
            if m["v1"] is not None or p["base"] is None:
                continue
            chaves = A.look_para(i, v2, mapa, v1, looks)
            if not chaves:
                continue
            fonte = max(range(len(v1)), key=lambda k: len(chaves & looks[k]))
            so = [x for x in v1[fonte]["col"] if CA.impressao([x]) in chaves & looks[fonte]]
            if not so:
                continue
            sh = s.get_shot(p["id"])
            try:
                _refazer(sh, p, so, 0.0, v1[fonte]["res"])
                ok = _confere(_ler(sh), p["base_ciclo"], so, CA.keyframes(so))
                if ok is False:
                    _refazer(sh, p, [], 0.0, "")
                    planos[i]["aviso"] = "o look da cena não entrou (a leitura não confere): o colorista aplica"
                else:
                    planos[i]["estado"] = "só o look"
                    planos[i]["de"] = v1[fonte]["rec"][0]
                    esperado[i] = (so, CA.keyframes(so))
                    planos[i]["cor_esperada"] = CA.impressao(so)
            finally:
                sh.release()

        # 5. os markers do colorista, pela fonte
        movidos, perdidos = A.mover_marcas(marcas, v1, v2)
        cats = {str(x) for x in s.get_mark_categories()}
        for mk in movidos:
            cat = mk["categoria"] if str(mk["categoria"]) in cats else s.get_mark_categories()[0]
            s.add_mark(mk["quadro"], cat, mk["nota"])

        # 6. os GRUPOS do colorista pelo mesmo casamento da cor (o Multi-Paste fica com PasteGroups=0: o dele só leva os
        #    planos que ELE casou, e o take trocado sai calado — BL09, 2026-11-22)
        grupos = A.levar_grupos(grupos_v1, mapa, v2, v1)
        for g in grupos:
            if g["v2"]:
                s.set_group(g["nome"], [v2[j]["id"] for j in g["v2"]])
            for j in g["novos"]:
                nota = f"entrou no grupo “{g['nome']}” do colorista (no lugar do plano que estava nele)"
                planos[j]["aviso"] = (planos[j]["aviso"] + " — " if planos[j]["aviso"] else "") + nota
        s.end_delta()
        s.save_scene()
        # a conferência relida: cada plano (a pilha e a camada 0 depois das correções) e os grupos
        certos, nao_relidos = 0, 0
        for k, (p, m) in enumerate(zip(v2, mapa)):
            sh = s.get_shot(p["id"])
            try:
                ok = _confere(_ler(sh), p["base_ciclo"], *esperado[k]) if p["base"] is not None else None
                entrada_ok = m["v1"] is None or _camada0(sh) == v1[m["v1"]]["entrada"]
            finally:
                sh.release()
            if ok is None:
                nao_relidos += 1
                planos[k]["conferido"] = "gravado (composição: o Baselight não relê)" if p["base"] is not None else "não"
            else:
                planos[k]["conferido"] = "sim" if ok and entrada_ok else "não"
                certos += 1 if ok and entrada_ok else 0
        ids_depois = {i.ShotId: k for k, i in enumerate(s.get_shot_ids())}
        for g in grupos:
            lidos = sorted(ids_depois[i] for i in (s.get_group(g["nome"]) or []) if i in ids_depois)
            g["conferido"] = lidos == sorted(g["v2"])
    finally:
        s.close_scene()
    print(json.dumps({"colados_multipaste": colados, "erro_multipaste": erro_mp, "planos": planos,
                      "conferidos": certos, "nao_relidos": nao_relidos, "de": len(planos),
                      "do_colorista_ilegiveis": sum(1 for p in v1 if p["ilegivel"]),
                      "marcas_movidas": [{"quadro": x["quadro"], "de": x["de"], "nota": x["nota"]} for x in movidos],
                      "marcas_perdidas": [{"quadro": x["quadro"], "nota": x["nota"], "motivo": x["motivo"],
                                           "categoria": str(x.get("categoria") or "")}
                                          for x in perdidos],
                      "grupos": [{"nome": g["nome"], "planos": [planos[j]["inicio"] for j in g["v2"]],
                                  "novos": [planos[j]["inicio"] for j in g["novos"]],
                                  "fora": [v1[k]["rec"][0] for k in g["fora"]], "conferido": g.get("conferido")}
                                 for g in grupos],
                      "log_multipaste": log_mp}, ensure_ascii=False, default=str))
finally:
    c.close()
