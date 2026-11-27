"""O "Importar para o Premiere" de uma TIMELINE da Carta, no projeto ABERTO do editor (decisões do autor, 2026-11-14:
plano `docs/plano/2026-11-11-carta-aberta.md`, "LEVAR para o NLE").

O caminho (cada passo medido no 26.0.2 Mac):
1. a mídia que falta entra no projeto do editor pelo PRÓPRIO Premiere (`cicloImportar`; o que já está lá é usado —
   `importSequences` não duplica), e o projeto dele é SALVO (decisão de 12/11);
2. uma CÓPIA de trabalho do projeto salvo, na pasta interna da Carta (nunca ao lado do projeto do editor);
3. os MOLDES que faltam (`moldes_prproj`): o Premiere abre a cópia AO LADO, monta-os nela (`cicloMontar`), salva e
   a fecha; ⭐ o que toca o projeto do editor vai pelo CAMINHO dele (o objeto do projeto, à frente ou não): pôr um
   projeto à frente pela API não é confiável, e a volta dele à frente, no fim, é só cortesia;
4. a timeline escrita numa SEGUNDA cópia, versionada (`entrega_prproj.escrever_timeline`);
5. `importSequences` traz só a sequência (e o que ela usa) para o projeto do editor.
⛔ Nada é escrito no arquivo do editor por nós: quem o muda é o Premiere (importar, salvar, `importSequences`).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import entrega_prproj as _ep
from . import moldes_prproj as _mo
from .projeto import CartaErro, Projeto


#: onde a mídia da timeline entra no projeto do editor (autor, 2026-11-15): `Midias`, repartida por tipo em Video
#: (Movie e Video do Premiere), Audio e Fotos (Still Image), e os subclipes em `Subclipes` — cada subpasta só existe
#: quando há o que pôr nela (`cicloArrumarMidias` e `cicloImportarSequencias` no host)
BIN_MIDIAS = "Carta Aberta/Midias"
#: o prazo da importação da mídia (mais 1 s por arquivo): 259 arquivos levam ~2,4 s no 27.0 e ~2,5 min no 23.6
PRAZO_DA_MIDIA_S = 180.0
#: quando a importação da mídia não volta: quase sempre o aviso "File Import Failure" do Premiere, que SEGURA a resposta
#: até o OK (medido no 27.0, 2026-11-15) — um arquivo de mídia que ele não lê (BRAW sem o plugin da Blackmagic, por
#: exemplo). O gesto vem na frase: erro que não diz o gesto vira adivinhação.
AVISO_NA_IMPORTACAO = ("O Premiere não terminou de importar a mídia: ele deve estar com um aviso aberto (\"File Import "
                       "Failure\"), que aparece quando um arquivo não pode ser lido — por exemplo, BRAW sem o plugin da "
                       "Blackmagic. O que ele aceitou já entrou no projeto. Feche o aviso com OK e clique de novo em "
                       "Importar para o Premiere: o que já entrou não se repete.")


#: a cor do marker do Avid (`_ATN_CRM_COLOR`) → o índice do Premiere (`setColorByIndex`: Green 0, Red 1, Magenta 2,
#: Orange 3, Yellow 4, White 5, Blue 6, Cyan 7). ⚠️ O Premiere não tem preto: o Black do Avid vai como White.
CORES_DE_MARKER = {"Green": 0, "Red": 1, "Magenta": 2, "Yellow": 4, "White": 5, "Black": 5, "Blue": 6, "Cyan": 7}


def plano_de_marcadores(item: dict) -> tuple[str, list[str]]:
    """O texto do `cicloMarcarSequencia` (início e duração em SEGUNDOS, cor, nome, comentário) e as cores que não têm
    par exato (ditas no relatório). O nome é o comentário do Avid; o comentário leva de onde veio (a trilha — o marker
    de sequência do Premiere não tem trilha), quem pôs e quando."""
    from fractions import Fraction
    fps = Fraction(str(item.get("fps") or "24"))
    linhas, sem_par = [], []
    limpo = lambda s: str(s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()  # noqa: E731
    for m in item.get("marcadores") or []:
        cor = str(m.get("cor") or "")
        if cor == "Black" or (cor and cor not in CORES_DE_MARKER):
            sem_par.append(cor)
        de_onde = " · ".join(x for x in ("Avid", m.get("trilha"), m.get("usuario"), m.get("data")) if x)
        linhas.append("\t".join([f"{float(Fraction(int(m['q'])) / fps):.6f}",
                                  f"{float(Fraction(int(m.get('duracao_q') or 0)) / fps):.6f}",
                                  str(CORES_DE_MARKER.get(cor, 0)), limpo(m.get("comentario")), limpo(de_onde)]))
    return "\n".join(linhas) + ("\n" if linhas else ""), sem_par


#: o Warp Stabilizer (índices dos menus, banco `laboratorio-de-midia/resultados/B19_ESTABILIZADOR/PREMIERE.md`)
WARP_METODO_POSICAO = 0          # Method 0 = Position (o Avid rastreia UM ponto: só desloca)
WARP_SUAVIZAR = 0                # Result 0 = Smooth Motion (o Avid remove o tremor, não trava a câmera)
WARP_AUTO_ESCALA = 2             # Framing 2 = Stabilize, Crop, Auto-scale (o Auto-Zoom do Avid)
WARP_SO_ESTABILIZAR = 0          # Framing 0 = Stabilize Only (o Avid sem Auto-Zoom)


def plano_de_estabilizacao(item: dict) -> str:
    """O texto do `cicloEstabilizar`: o Stabilize do Avid → o Warp Stabilizer (decisão do autor, 2026-11-20:
    estabilizador → estabilizador). Um clipe por linha: a trilha (do 0), o MEIO do segmento em segundos, Method, Result,
    Smoothness (o filtro do Avid × 100 — `hipotese`) e Framing.
    ⚠️ O Warp ANALISA o clipe sozinho: o resultado é parecido, não igual (medido na PRODA contra a correção do Avid, a
    conta do lab com resíduo 0,1 px: até ~10 px e +1,2 % de escala no plano que mais treme)."""
    from fractions import Fraction
    from .entrega_prproj import estabilizacao_do_efeito
    fps = Fraction(str(item.get("fps") or "24"))
    linhas = []
    for t in item.get("trilhas") or []:
        if t.get("tipo") != "V":
            continue
        for c in t.get("clipes") or []:
            if (c.get("velocidade") or {}).get("classe"):
                continue
            for e in c.get("efeitos") or []:
                d = estabilizacao_do_efeito(e)
                if d is None:
                    continue
                meio = Fraction(int(c["inicio_q"]) + int(c["fim_q"]), 2) / fps
                auto = (e.get("params") or {}).get("auto_zoom")
                linhas.append("\t".join([str(int(t["k"]) - 1), f"{float(meio):.6f}", str(WARP_METODO_POSICAO),
                                         str(WARP_SUAVIZAR), f"{round(float(d.get('filtro') or 0.5) * 100, 3)}",
                                         str(WARP_AUTO_ESCALA if auto is not False else WARP_SO_ESTABILIZAR)]))
    return "\n".join(linhas) + ("\n" if linhas else "")


def _pasta_de_trabalho(proj: Projeto) -> Path:
    p = proj.interna / "premiere"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _versao_nova(pasta: Path, base: str) -> Path:
    n = 1
    while (pasta / f"{base} v{n:02d}.prproj").exists():
        n += 1
    return pasta / f"{base} v{n:02d}.prproj"


def transcricao_nos_merged(versao: str) -> bool:
    """O merged leva a transcrição VAZIA? Medido no Mac (2026-11-15): reimportar a mesma timeline repete os merged no
    23.6, no 25.6.5 e no 26.0.2 (+36 por vez); com ela, 0 nos três. Abaixo do 23: ⬜ não medido — desligada. Versão
    desconhecida: não."""
    try:
        return int(str(versao).split(".")[0]) >= 23
    except ValueError:
        return False


def importar_timeline(proj: Projeto, item: dict, chamar, quadro: tuple[int, int] | None = None,
                      forma: str = "avid", relatar=None, modelo: str | None = None,
                      transcricao: bool | None = None) -> dict:
    """Leva a timeline `item` ao projeto ABERTO no Premiere. `chamar(funcao, *args, prazo=)` é a ponte. Devolve o
    relatório (passos com o tempo de cada um, o que ficou de fora, a contagem do projeto antes/depois)."""
    rel: dict = {"passos": []}
    t0 = time.monotonic()

    def passo(nome: str, **extra) -> None:
        rel["passos"].append({"passo": nome, "s": round(time.monotonic() - t0, 1), **extra})
        if relatar:
            relatar(nome)

    editor = (chamar("cicloProjetosAbertos", prazo=30.0) or {}).get("ativo") or ""
    if not editor.endswith(".prproj"):
        raise CartaErro("não há projeto aberto no Premiere")
    rel["editor"] = editor
    rel["premiere"] = str((chamar("cicloProjeto", prazo=30.0) or {}).get("versao") or "")
    # o DESTINO (autor): a bin selecionada, ou a aberta por último — lida ANTES, porque abrir a cópia muda o foco
    b = chamar("cicloBinDeInsercao", editor, prazo=30.0) or {}
    rel["bin"] = "" if b.get("raiz") else (b.get("caminho") or "")
    # 1. a mídia que falta, pelo Premiere, e o projeto do editor salvo
    arquivos, offline = _ep.arquivos_da_timeline(proj, item, forma)
    rel["offline"] = offline
    R = _ep._ler_prproj(editor)
    ja = _ep.midia_do_projeto(R)
    faltando = [a for a in arquivos if _ep._norm(a) not in ja]
    # ⭐ o molde do SOM precisa de um clipe MONO montado pelo Premiere; numa timeline só de som ESTÉREO (B32, 2026-11-26)
    #   não havia nenhum e a timeline inteira era recusada: a Carta põe um WAV mono de silêncio no projeto, junto da mídia
    pede_mono = R is not None and {"som", "ganho", "transicao_A"} & set(
        _mo.faltam(_mo.inventario(R), _mo.o_que_a_timeline_pede(proj, item)))
    if pede_mono and _mo.som_mono(R, arquivos) is None:
        molde_som = str(_mo.gravar_som_molde(proj.interna / "moldes"))
        if _ep._norm(molde_som) not in ja:
            faltando.append(molde_som)
        rel["som_molde"] = molde_som
    # ⭐ UM pedido com a lista inteira (autor, 2026-11-15: um por arquivo fazia a janela de importar piscar centenas de
    #   vezes); o host importa a lista de uma vez por bin e confere arquivo a arquivo o que entrou
    recusados = []
    if faltando:
        plano_midia = f"bin\t{BIN_MIDIAS}\n" + "".join(f"arq\t{a}\t\n" for a in faltando)
        try:
            r = chamar("cicloImportar", plano_midia, prazo=PRAZO_DA_MIDIA_S + 1.0 * len(faltando)) or {}
        except Exception as e:  # noqa: BLE001 — a ponte desistiu de esperar: o que costuma ser, e o gesto
            if "não respondeu" not in str(e):
                raise
            # ⛔ com o aviso aberto o Premiere não atende a ponte (um pedido por vez): não dá para conferir daqui o que
            #   entrou. Medido no 27.0 (2026-11-15): o que ele aceita JÁ entrou antes do aviso, e reimportar não repete.
            raise CartaErro(AVISO_NA_IMPORTACAO) from e
        if r.get("erro"):
            raise CartaErro(f"o Premiere não importou a mídia: {r['erro']}")
        # ⛔ o que o Premiere recusou é DITO, pelo nome (antes, o erro de um arquivo se perdia calado)
        recusados = [f"{Path(f.get('arquivo') or '').name}: {f['erro']}" for f in (r.get("feitos") or [])
                     if f.get("erro")]
    rel["midia_recusada"] = recusados
    if faltando:
        rel["pastas"] = chamar("cicloArrumarMidias", editor, BIN_MIDIAS, prazo=120.0 + 0.2 * len(faltando)) or {}
    s = chamar("cicloSalvar", editor, prazo=120.0) or {}
    if not s.get("salvo"):
        raise CartaErro("o Premiere não salvou o projeto do editor")
    passo("midia", importados=len(faltando) - len(recusados), recusados=len(recusados),
          ja_estavam=len(arquivos) - len(faltando))
    # 2. a cópia de trabalho, e o que ela já tem de molde
    pasta = _pasta_de_trabalho(proj)
    base = f"{Path(editor).stem} - {item.get('nome') or 'timeline'}"
    copia = _versao_nova(pasta, f"{base} TRABALHO")
    shutil.copyfile(editor, copia)
    R = _ep._ler_prproj(str(copia))
    inv = _mo.inventario(R)
    falta = _mo.faltam(inv, _mo.o_que_a_timeline_pede(proj, item))
    plano, nao = _mo.plano(R, falta, arquivos)
    rel.update({"moldes_do_editor": inv, "moldes_montados": falta, "moldes_fora": nao})
    passo("copia", copia=str(copia))
    # 3. o Premiere monta os moldes na cópia, aberta AO LADO; depois o editor volta à frente e a cópia fecha
    try:
        a = chamar("cicloAbrirProjeto", str(copia), prazo=180.0) or {}
        if not _ep._norm(a.get("caminho") or "") == _ep._norm(str(copia)):
            raise CartaErro(f"o Premiere não abriu a cópia de trabalho ({a.get('erro') or a})")
        # a CALIBRAGEM do merged (opção A do autor: calada, só na cópia): o projeto-modelo do app entra e dá o molde
        mod = Path(modelo) if modelo else _mo.modelo_para(rel["premiere"])    # o modelo que ESTE Premiere abre
        if "merged" in falta and mod.is_file():
            # ⭐ uma cópia com a mídia apontando para onde ela está NESTA instalação (o modelo guarda o caminho de
            #   quando foi feito); o nome do modelo é mantido — é o que a bin da calibragem mostra
            no_lugar = pasta / "calibragem" / mod.name
            rel["modelo_midia"] = _mo.modelo_no_lugar(mod, no_lugar)
            c = chamar("cicloImportarProjeto", str(no_lugar), _mo.BIN_DO_MODELO, prazo=300.0) or {}
            if c.get("erro") or not c.get("ok") or not (c.get("depois") or {}).get("merged"):
                # ⛔ calibragem que falha NÃO para a importação: os sincronizados vão pela mídia nativa, e é dito
                rel["moldes_fora"] = nao + [f"calibragem: o Premiere não trouxe o merged do modelo ({c.get('erro') or c})"]
            else:
                rel["moldes_fora"] = [n for n in nao if not n.startswith("merged:")]
            passo("calibragem", modelo=str(mod), antes=c.get("antes"), depois=c.get("depois"))
        if "titulo" in falta:
            # o molde do TÍTULO (2026-11-20): um gráfico de texto do próprio Premiere, só na cópia
            mt = _mo.molde_de_titulo_para(rel["premiere"])
            if mt is None or not mt.is_file():
                rel["moldes_fora"] = list(rel["moldes_fora"]) + [
                    f"titulo: não há molde de título para o Premiere {rel['premiere']} (os títulos ficam de fora)"]
            else:
                c = chamar("cicloImportarProjeto", str(mt), _mo.BIN_DO_TITULO, prazo=120.0) or {}
                if c.get("erro") or not c.get("ok"):
                    rel["moldes_fora"] = list(rel["moldes_fora"]) + [
                        f"titulo: o Premiere não trouxe o molde ({c.get('erro') or c})"]
                passo("molde_do_titulo", molde=str(mt))
        m = chamar("cicloMontar", plano, prazo=300.0) or {}
        if m.get("erro"):
            raise CartaErro(f"o Premiere não montou os moldes: {m['erro']}")
        chamar("cicloSalvar", str(copia), prazo=120.0)
        passo("moldes", transicoes=m.get("transicoes"), ajustes=m.get("ajustes"), cores=m.get("cores"))
    finally:
        # ⭐ a frente é CORTESIA: tudo o que toca o projeto do editor daqui em diante vai pelo CAMINHO dele (o objeto do
        #   projeto), porque pôr um projeto à frente pela API não é confiável (medido, 2026-11-14)
        chamar("cicloFecharProjeto", str(copia), editor, prazo=60.0)
    # o que o Premiere de fato gravou (um molde pedido e não gravado vira "sem molde" na escrita — e é dito aqui)
    rel["moldes_na_copia"] = _mo.inventario(_ep._ler_prproj(str(copia)))
    # 4. a timeline escrita numa segunda cópia, versionada
    saida = _versao_nova(pasta, base)
    nome = item.get("nome") or "timeline"
    rel["escrita"] = _ep.escrever_timeline(proj, item, str(copia), str(saida), _mo.NOME_DOS_MOLDES, nome,
                                           None, forma=forma, quadro=quadro,
                                           transcricao_vazia=(transcricao_nos_merged(rel["premiere"])
                                                              if transcricao is None else transcricao))
    passo("escrita", saida=str(saida))
    # 5. só a sequência volta, para o projeto do editor
    uid = rel["escrita"]["uid"]
    r = chamar("cicloImportarSequencias", str(saida), uid, "" if b.get("raiz") else str(b.get("nodeId") or ""),
               editor, BIN_MIDIAS + "/Subclipes", prazo=600.0) or {}
    if r.get("erro") or not r.get("ok"):
        raise CartaErro(f"o Premiere não importou a sequência: {r.get('erro') or r}")
    rel["contagem"] = {"antes": r.get("antes"), "depois": r.get("depois")}
    # os MARKERS da timeline do Avid, na sequência que acabou de entrar (autor, 2026-11-15: "completar a troca")
    plano_m, sem_par = plano_de_marcadores(item)
    if plano_m:
        seq_nova = next((s["id"] for s in (r.get("novas") or []) if s.get("nome") == nome), "")
        if seq_nova:
            mk = chamar("cicloMarcarSequencia", seq_nova, editor, plano_m, prazo=120.0) or {}
            rel["marcadores"] = {"pedidos": len(item.get("marcadores") or []), "criados": mk.get("criados", 0),
                                 "falhas": mk.get("falhas") or ([mk["erro"]] if mk.get("erro") else []),
                                 "cor_sem_par": sorted(set(sem_par))}
        else:
            rel["marcadores"] = {"pedidos": len(item.get("marcadores") or []), "criados": 0,
                                 "falhas": ["a sequência importada não foi achada pelo nome"]}
    rel["novas"] = r.get("novas") or []
    rel["movidos"] = {"para": r.get("destino") or "", "itens": r.get("movidos", 0), "na_raiz": r.get("na_raiz", 0),
                      "subclipes": r.get("subclipes", 0)}
    passo("importada", uid=uid)
    rel["voltou"] = (chamar("cicloAtivarProjeto", editor, prazo=60.0) or {}).get("ativo")
    # o STABILIZE do Avid → o Warp Stabilizer, na sequência que entrou (o QE pede o projeto do editor À FRENTE)
    plano_e = plano_de_estabilizacao(item)
    if plano_e:
        seq_nova = next((s["id"] for s in (r.get("novas") or []) if s.get("nome") == nome), "")
        if seq_nova:
            es = chamar("cicloEstabilizar", seq_nova, editor, plano_e, prazo=180.0) or {}
            rel["estabilizacao"] = {"pedidos": plano_e.count("\n"), "aplicados": es.get("aplicados", 0),
                                    "falhas": es.get("falhas") or ([es["erro"]] if es.get("erro") else []),
                                    "aviso": "Warp Stabilizer do Premiere: ele analisa o clipe sozinho — parecido "
                                             "com o Stabilize do Avid, não igual"}
        else:
            rel["estabilizacao"] = {"pedidos": plano_e.count("\n"), "aplicados": 0,
                                    "falhas": ["a sequência importada não foi achada pelo nome"]}
        passo("estabilizacao", aplicados=rel["estabilizacao"]["aplicados"])
    return rel
