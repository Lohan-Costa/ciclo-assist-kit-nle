"""O fluxo de edição de cena NO PAPEL: agentes em sequência, sem nodes, sem Media Composer e sem escrever em bin.

    python spikes/edicao_de_cena/no_papel.py                    # C07 com o roteiro dela
    python spikes/edicao_de_cena/no_papel.py --roteiro X.docx --ate revisor --saida <pasta>   # teste negativo
    python spikes/edicao_de_cena/no_papel.py --refazer dialogo  # refaz uma etapa (as outras vêm do disco)

Gasta turnos do modelo configurado no app (conta do app). Cada etapa grava um JSON na pasta de saída e não roda de novo sem --refazer.
Plano: `docs/plano/2026-11-09-edicao-de-cena.md`.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import cicloassist.avid  # noqa: E402,F401
from cicloassist import documento  # noqa: E402
from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.mcp.ferramentas import fala as _fala, falas as _ferr_falas, roteiro as _roteiro, trama as _trama  # noqa: E402
from cicloassist.midia import falantes as _falantes, frames as _frames  # noqa: E402
from cicloassist.motor import agentes as A, turno_magro as T  # noqa: E402
from cicloassist.plano import esquema as _esquema, falas as _plano_falas, mapa as _mapa  # noqa: E402
from cicloassist.servico import arrastados as _arrastados, config as _config  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bordas as _bordas  # noqa: E402

PASTA = Path(__file__).resolve().parent
BIN = r"%USERPROFILE%\Documents\Avid Projects\PRODUCAO-A_CURTA\CENAS\C07.avb"
ROTEIRO = r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\ROTEIRO\PRODUCAO-A CENA 7 roteiro.docx"
SAIDA = r"D:\MIDIAS DE TESTES\9 SAIDAS DOS APPS\_CICLO ASSIST\2026-11-09 EDICAO C07"
TAKES = ("C07_P01-001 C07_P01-002 C07_P02-001 C07_P02-001.1 C07_P02-002 C07_P02-003 "
         "C07_P02-004 C07_P03-001 C07_P03-002 C07_P03-003").split()

#: Fala "presente" num take a partir daqui. É a `COBERTURA_MINIMA` medida em 2026-09-15 (presentes 75–100%, ausentes 8–50%).
PRESENTE = 0.60
#: ⛔ Abaixo disto de falas presentes em algum take, o CÓDIGO para o fluxo, diga o agente o que disser. Proposta a calibrar com o teste negativo.
COBERTURA_PARA_SEGUIR = 0.70
#: Segmento que se parece menos que isto com qualquer fala do roteiro é candidato a improviso ou equipe.
PARECE_COM_ALGUMA = 0.40
#: ⚠️ O pedido vai na linha de comando do `claude -p`; o Windows corta em 32.767 caracteres.
TETO_DA_LINHA = 30_000
MAX_VOLTAS = 2
MAX_FORA_NA_AMOSTRA = 60
#: Fala curta casa por acaso com qualquer trecho: só acusa fala cortada que tenha ao menos estas palavras.
MIN_PALAVRAS_PARA_ACUSAR = 5
#: A voz continua depois do que o ASR diz: 230 ms em média, 350 ms no pior caso (`spikes/o_respiro_do_corte.py`). 8 quadros cobrem o pior caso.
VOZ_DEPOIS = 8
#: O ASR acerta o ataque com ~10 ms; 3 quadros são margem de ar.
VOZ_ANTES = 3
#: Com a borda medida na forma de onda, a margem é só a de um quadro de arredondamento e um de ar.
MARGEM_MEDIDA = 2
#: Quanto da primeira palavra sempre se preserva ao recuar a entrada para fugir da fala anterior.
MIN_DA_PRIMEIRA = 6
#: Sem fala seguinte no take, a pausa disponível depois.
SEM_VIZINHO = 48
TAKES_COM_PALAVRAS: dict[str, list[dict]] = {}
QPS = 24000 / 1001


def arg(nome: str, padrao: str = "") -> str:
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao


def carregar_takes() -> dict[str, list[dict]]:
    takes = {}
    for nome in TAKES:
        take = resolver(BIN, nome)
        midia = take.som.midia(rotulo=take.rotulo(take.som)) if take.som is not None else None
        if midia is None or not midia.tem_transcricao():
            takes[nome] = []
            continue
        transcricao = _falantes.anexar(midia.ler_transcricao(), _falantes.ler(midia))
        takes[nome] = _fala.falas_do_take(take, transcricao, por_palavra=True)
    TAKES_COM_PALAVRAS.update(takes)
    return takes


def melhor_trecho(texto: str, segs: list[dict]) -> tuple[float, int, int]:
    """Quanto da fala aparece no melhor trecho de até 4 segmentos seguidos."""
    melhor = (0.0, 0, 0)
    for i in range(len(segs)):
        junto = ""
        for j in range(i, min(i + 4, len(segs))):
            junto += " " + str(segs[j]["texto"])
            p = _mapa.parecenca(texto, junto)
            if p > melhor[0] + 1e-9:
                melhor = (p, int(segs[i]["segmento"]), int(segs[j]["segmento"]))
    return melhor


def medir(falas: list, takes: dict[str, list[dict]]) -> dict:
    com_fala = [n for n, s in takes.items() if s]
    linhas = ["fala | " + " | ".join(com_fala)]
    presentes, por_take = 0, dict.fromkeys(com_fala, 0)
    for f in falas:
        celulas = []
        alguma = False
        for nome in com_fala:
            p = melhor_trecho(f.texto, takes[nome])[0]
            celulas.append(f"{p * 100:.0f}")
            if p >= PRESENTE:
                alguma = True
                por_take[nome] += 1
        presentes += alguma
        linhas.append(f"{f.n} {f.personagem} | " + " | ".join(celulas))
    fora = []
    for nome in com_fala:
        for s in takes[nome]:
            texto = str(s["texto"])
            if max((_mapa.parecenca(texto, f.texto) for f in falas), default=0) < PARECE_COM_ALGUMA:
                fora.append(f"{nome} seg {s['segmento']}: {texto.strip()}")
    cobertura = presentes / max(1, len(falas))
    # ⛔ Com o roteiro errado quase tudo é "fora": sem teto, o pedido passou de 30 mil caracteres. O total vai em `numeros`.
    amostra = fora[:MAX_FORA_NA_AMOSTRA]
    if len(fora) > len(amostra):
        amostra.append(f"(e mais {len(fora) - len(amostra)} segmentos que não se parecem com fala nenhuma)")
    return {"matriz": "\n".join(linhas), "fora": "\n".join(amostra),
            "numeros": {"falas_no_roteiro": len(falas), "falas_presentes_em_algum_take": presentes,
                        "cobertura": round(cobertura, 2), "falas_presentes_por_take": por_take,
                        "takes_sem_fala_nenhuma": [n for n, v in por_take.items() if not v],
                        "takes_sem_transcricao_util": [n for n, s in takes.items() if not s],
                        "segmentos_fora_do_roteiro": len(fora),
                        "segmentos_no_total": sum(len(s) for s in takes.values())}}


def texto_das_transcricoes(takes: dict[str, list[dict]]) -> str:
    blocos = []
    for nome, segs in takes.items():
        linhas = [f"## {nome}"]
        for s in segs:
            quem = f" [{s['quem']}]" if s.get("quem") else ""
            linhas.append(f"{s['segmento']} | {float(s['inicio_no_take_frames']) / (24000 / 1001):.1f}s{quem} | {str(s['texto']).strip()}")
        blocos.append("\n".join(linhas if segs else [f"## {nome}", "(sem fala)"]))
    return "\n\n".join(blocos)


USOS: list[dict] = []


def registrar_uso(nome: str, uso: dict, segundos: float) -> None:
    USOS.append({"agente": nome, "segundos": round(segundos, 1), **uso})


def agente(nome: str, entrada: dict, prazo: float = 600) -> dict:
    a = A.ler_texto((PASTA / "agentes" / f"{nome}.md").read_text(encoding="utf-8"))
    pedido = A.montar_pedido(a, entrada)
    if len(pedido) + len(a.instrucao) > TETO_DA_LINHA:
        # ⛔ Medido na revisão do Editor: 28 mil de pedido + a instrução passam do que a linha de comando do Windows comporta.
        print(f"   {nome}: pedido de {len(pedido)} caracteres vai pelo stdin")
        return chamar_com_imagens(a, [{"type": "text", "text": pedido}], prazo)
    r = T.chamar(a.instrucao, pedido, None, prazo)
    try:
        dados = T.objeto_json(r.texto)
        A.conferir_saida(a, dados)
    except (A.AgenteFalhou, T.TurnoFalhou) as e:
        # Medido: o Diretor omitiu uma vez o `parecer`, que nessa etapa é vazio. Uma segunda chance, nunca um valor inventado.
        print(f"   {nome}: {e}; tentando de novo")
        registrar_uso(nome, r.uso, r.segundos)
        r = T.chamar(a.instrucao, pedido, None, prazo)
        dados = T.objeto_json(r.texto)
        A.conferir_saida(a, dados)
    registrar_uso(nome, r.uso, r.segundos)
    print(f"   {nome}: {r.segundos:.0f} s · pedido {len(pedido)} caracteres · uso {json.dumps(r.uso, ensure_ascii=False)}")
    return dados


class Etapas:
    def __init__(self, pasta: Path, refazer: str):
        self.pasta, self.refazer = pasta, refazer
        pasta.mkdir(parents=True, exist_ok=True)

    def rodar(self, nome: str, fazer):
        arq = self.pasta / f"{nome}.json"
        if arq.exists() and self.refazer != nome:
            print(f"· {nome}: do disco")
            return json.loads(arq.read_text(encoding="utf-8"))
        print(f"· {nome}: rodando")
        dados = fazer()
        arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return dados


def conferir_beats(estrutura: dict, n: int) -> list[str]:
    problemas, esperado = [], 1
    for b in estrutura.get("beats", []):
        if b.get("de_fala") != esperado:
            problemas.append(f"beat começa na fala {b.get('de_fala')}, esperava {esperado}")
        esperado = int(b.get("ate_fala", esperado)) + 1
    if esperado != n + 1:
        problemas.append(f"os beats terminam na fala {esperado - 1}, e o roteiro tem {n}")
    return problemas


def fazer_dialogo(falas: list, revisao: dict, takes: dict, caminho_roteiro: str) -> dict:
    _arrastados.autorizar(caminho_roteiro)
    lista = [{"n": f.n, "personagem": f.personagem, "texto": f.texto} for f in falas]
    historico, reprovacao, primeiro = [], "", None
    corrigir = False
    pedido = None
    for volta in range(MAX_VOLTAS + 1):
        dados = agente("agente-de-dialogo", {"falas": lista, "divergencias": revisao.get("divergencias", []),
                                             "transcricoes": texto_das_transcricoes(takes), "reprovacao": reprovacao})
        primeiro = primeiro or dados
        de_fora = dados.get("deixadas_de_fora") or None
        de_fora = [{k: v for k, v in d.items() if v not in (None, "")} for d in de_fora] if de_fora else None
        pedido = _ferr_falas._preparar(BIN, "7", dados["momentos"], de_fora, caminho_roteiro, "", corrigir)
        historico.append({"volta": volta, "momentos_devolvidos": len(dados["momentos"]),
                          "momentos_no_pedido": len(pedido.falas), "problemas": list(pedido.conf.problemas)})
        print(f"   volta {volta}: {len(dados['momentos'])} devolvidos, {len(pedido.falas)} no pedido, {len(pedido.conf.problemas)} problema(s)")
        if pedido.conf.fecha:
            break
        reprovacao = _plano_falas.relatar(pedido.conf)
        corrigir = True
    de_pedido = [{"fala": f.n, "variante": f.variante, "texto": f.texto, "personagem": f.personagem,
                  "trechos": [{"take": t.take, "inicio_no_take_frames": t.inicio, "duracao_frames": t.duracao}
                              for t in f.trechos]} for f in pedido.falas]
    usados = {(t["take"], s) for m in primeiro["momentos"] for t in m["trechos"]
              for s in range(int(t["do_segmento"]), int(t.get("ate_o_segmento") or t["do_segmento"]) + 1)}
    excluidos = {(e["take"], int(e["segmento"])) for e in primeiro.get("segmentos_excluidos", [])}
    sem_destino = [f"{n} seg {s['segmento']}: {str(s['texto']).strip()}" for n, segs in takes.items() for s in segs
                   if (n, int(s["segmento"])) not in usados and (n, int(s["segmento"])) not in excluidos]
    return {"fecha": pedido.conf.fecha, "voltas": historico, "momentos": de_pedido,
            "deixadas_de_fora": primeiro.get("deixadas_de_fora", []), "segmentos_excluidos": primeiro.get("segmentos_excluidos", []),
            "segmentos_sem_destino": sem_destino}


def planos_disponiveis(revisao: dict) -> list[dict]:
    """O que cada take mostra, da decupagem micro. A cabeça (claquete) fica de fora."""
    situacao = {t.get("take"): t for t in revisao.get("takes", [])}
    saida = []
    for nome in TAKES:
        linha = _trama.linha_do_take(resolver(BIN, nome), com_falas=False)
        trechos = [t for t in linha.get("linha", []) if t.get("entrada") != "inicio"] or linha.get("linha", [])
        enquadramentos = sorted({t["enquadramento"] for t in trechos if t.get("enquadramento")})
        descricao = " / ".join(str(t.get("descricao") or "")[:160] for t in trechos[:2])
        saida.append({"take": nome, "plano": nome.split("_")[1].split("-")[0], "duracao_s": linha["duracao_s"],
                      "enquadramentos": enquadramentos, "o_que_se_ve": descricao,
                      "situacao": situacao.get(nome, {}).get("situacao", ""), "cobre": situacao.get(nome, {}).get("cobre", "")})
    return saida


def mapa_de_opcoes(dialogo: dict, takes: dict[str, list[dict]]) -> tuple[str, dict[str, dict]]:
    """O texto que o Editor lê e, por identificador, onde cada leitura está. ⭐ O Editor aponta o identificador; os quadros são conta do código."""
    linhas, por_id = [], {}
    for m in dialogo["momentos"]:
        linhas.append(f"\n[momento {m['fala']}.{m['variante']}] {m.get('personagem') or ''}: {m['texto']}")
        for t in m["trechos"]:
            ini, fim = int(t["inicio_no_take_frames"]), int(t["inicio_no_take_frames"]) + int(t["duracao_frames"])
            segs = takes[t["take"]]
            i = next(k for k, s in enumerate(segs) if int(s["inicio_no_take_frames"]) == ini)
            j = next(k for k, s in enumerate(segs) if int(s["saida_no_take_frames"]) == fim)
            # ⛔⛔ A pausa sai da VOZ dos vizinhos, palavra a palavra. A primeira versão só olhava o vizinho que terminava antes do ponto de
            #    corte: fala encostada (o respiro de uma cruza o da outra) saía da conta, a pausa parecia enorme, e a folga pegava o fim da
            #    fala anterior. O autor ouviu "…fissional" e "comigo" repetidos (2026-11-09).
            # A voz medida pode passar do ponto de corte do ASR: quem manda é ela (senão volta o "sobe co…").
            ini, fim = min(ini, voz(segs[i])[0] - margem_ini(segs[i])), max(fim, voz(segs[j])[1] + margem_fim(segs[j]))
            entrada, saida, atropela_a, atropela_d = ini, fim, False, False
            fim_voz_ant = voz(segs[i - 1])[1] + margem_fim(segs[i - 1]) if i > 0 else 0
            ini_voz_prox = voz(segs[j + 1])[0] - margem_ini(segs[j + 1]) if j + 1 < len(segs) else fim + SEM_VIZINHO
            if fim_voz_ant > ini:
                entrada = min(fim_voz_ant, max(ini, primeira_palavra(segs[i])[1] - MIN_DA_PRIMEIRA))
                atropela_a = fim_voz_ant > entrada
            if ini_voz_prox < fim:
                saida = max(ini_voz_prox, voz(segs[j])[1] + 2)
                atropela_d = ini_voz_prox < saida
            pausa_a, pausa_d = max(0, entrada - fim_voz_ant), max(0, ini_voz_prox - saida)
            ident = f"M{m['fala']}.{m['variante']}:{t['take'].removeprefix('C07_')}"
            por_id[ident] = {"take": t["take"], "inicio": entrada, "fim": saida, "pausa_antes": pausa_a, "pausa_depois": pausa_d, "momento": m["fala"],
                             "seg_de": int(segs[i]["segmento"]), "seg_ate": int(segs[j]["segmento"])}
            aviso = ("" if not atropela_a else " | ⚠ a fala anterior ainda soa no começo") + ("" if not atropela_d else " | ⚠ a fala seguinte já soa no fim")
            linhas.append(f"  {ident} | {saida - entrada} q | pausa antes {pausa_a} q, depois {pausa_d} q{aviso}")
    return "\n".join(linhas), por_id


def voz(s: dict) -> tuple[int, int]:
    """Do início da primeira palavra ao fim da última, em quadros do take: é onde há voz de verdade, sem o respiro do ponto de corte.
    ⭐ A borda medida na lapela (`bordas.py`), quando houver; senão a estimativa do ASR."""
    if s.get("borda"):
        return int(s["borda"]["ini"]), int(s["borda"]["fim"])
    pal = s.get("palavras") or []
    if not pal:
        return int(s["inicio_no_take_frames"]), int(s["saida_no_take_frames"])
    return int(pal[0]["inicio"]), int(pal[-1]["fim"])


def margem_fim(s: dict) -> int:
    """Borda medida precisa de pouca margem; a do ASR, do pior caso medido."""
    return MARGEM_MEDIDA if (s.get("borda") or {}).get("medido_fim") else VOZ_DEPOIS


def margem_ini(s: dict) -> int:
    return MARGEM_MEDIDA if (s.get("borda") or {}).get("medido_ini") else VOZ_ANTES


def aplicar_bordas(takes: dict[str, list[dict]], pasta: Path) -> dict:
    """Pendura a borda medida em cada segmento. Devolve a contagem do que foi medido."""
    medidas, total = 0, 0
    for nome, segs in takes.items():
        if not segs or nome.endswith(".1") or len(segs) < 5:
            continue
        b = _bordas.guardado(pasta, nome, resolver(BIN, nome), segs)
        for s in segs:
            s["borda"] = b.get(int(s["segmento"]))
            if s["borda"]:
                total += 2
                medidas += s["borda"]["medido_ini"] + s["borda"]["medido_fim"]
    return {"medidas": medidas, "total": total}


def primeira_palavra(s: dict) -> tuple[int, int]:
    pal = s.get("palavras") or []
    return (int(pal[0]["inicio"]), int(pal[0]["fim"])) if pal else (int(s["inicio_no_take_frames"]), int(s["saida_no_take_frames"]))


def vazamentos(p: dict, seg_de: int, seg_ate: int, segs: list[dict]) -> list[str]:
    """Voz de segmento que NÃO é deste plano dentro do som dele. É a rede: vale mesmo que o cálculo das pausas erre."""
    achados = []
    for s in segs:
        n = int(s["segmento"])
        if seg_de <= n <= seg_ate:
            continue
        a, b = voz(s)
        if n < seg_de and b + margem_fim(s) > p["som_ini"] and a < p["som_fim"]:
            achados.append(f"plano {p['n']} ({p['take']}): o som começa com o fim de \"{str(s['texto']).strip()[-28:]}\", que não é deste plano. Escolha outra leitura ou inclua essa fala no plano.")
        elif n > seg_ate and a - margem_ini(s) < p["som_fim"] and b > p["som_ini"]:
            achados.append(f"plano {p['n']} ({p['take']}): o som termina com o começo de \"{str(s['texto']).strip()[:28]}\", que não é deste plano. Diminua a folga ou escolha outra leitura.")
    return achados


def traduzir(resposta: dict, por_id: dict[str, dict], falas: list, duracoes: dict[str, int], cortadas_ok: set[int] | None = None,
             segs_dos_takes: dict[str, list[dict]] | None = None) -> tuple[list[dict], list[str]]:
    """Da montagem do Editor (pelo SOM, por identificador) para o corte em quadros, e tudo o que o código reprova."""
    problemas: list[str] = []
    planos = []
    tempo_som = 0
    for i, p in enumerate(resposta["planos"], 1):
        de, ate = por_id.get(str(p.get("de"))), por_id.get(str(p.get("ate")))
        if de is None or ate is None:
            problemas.append(f"plano {i}: identificador inexistente ({p.get('de')} ou {p.get('ate')}).")
            continue
        if de["take"] != ate["take"]:
            problemas.append(f"plano {i}: `de` e `ate` são de takes diferentes.")
            continue
        folga_a, folga_d = int(p.get("folga_antes") or 0), int(p.get("folga_depois") or 0)
        if folga_a > de["pausa_antes"] or folga_d > ate["pausa_depois"] or folga_a < 0 or folga_d < 0:
            problemas.append(f"plano {i}: folga maior que a pausa disponível (antes {de['pausa_antes']}, depois {ate['pausa_depois']}).")
            continue
        som_ini, som_fim = de["inicio"] - folga_a, ate["fim"] + folga_d
        if som_fim <= som_ini:
            problemas.append(f"plano {i}: `ate` vem antes de `de` no take.")
            continue
        n = int(p.get("som_frames") or 0)
        corte_som = str(p.get("corte_de_som") or "junto")
        if corte_som not in ("junto", "antes", "depois"):
            problemas.append(f"plano {i}: corte_de_som {corte_som!r}.")
            continue
        planos.append({"n": i, "take": de["take"], "falas": [int(x) for x in p.get("falas") or []], "som_ini": som_ini, "som_fim": som_fim,
                       "t_som": tempo_som, "corte_de_som": corte_som, "som_frames": n, "porque": str(p.get("porque") or ""),
                       "seg_de": de["seg_de"], "seg_ate": ate["seg_ate"]})
        tempo_som += som_fim - som_ini
    if problemas:
        return [], problemas

    if segs_dos_takes is not None:
        for p in planos:
            problemas.extend(vazamentos(p, p["seg_de"], p["seg_ate"], segs_dos_takes[p["take"]]))

    # A imagem: J entra N depois do som dele; L entra N antes.
    for p in planos:
        p["ajuste"] = p["som_frames"] if p["corte_de_som"] == "antes" else -p["som_frames"] if p["corte_de_som"] == "depois" else 0
        p["x"] = p["t_som"] + p["ajuste"]
    cortes_para_validar = []
    for i, p in enumerate(planos):
        fim_x = planos[i + 1]["x"] if i + 1 < len(planos) else tempo_som
        p["img_ini"] = p["som_ini"] + p["ajuste"]
        p["img_dur"] = fim_x - p["x"]
        if p["img_dur"] < _esquema.DURACAO_MINIMA:
            problemas.append(f"plano {p['n']}: a imagem fica com {p['img_dur']} quadro(s). Reduza o L/J dos vizinhos.")
        if p["img_ini"] < 0 or p["img_ini"] + p["img_dur"] > duracoes[p["take"]]:
            problemas.append(f"plano {p['n']}: a imagem sai dos limites do take {p['take']} (L/J grande demais).")
        cortes_para_validar.append(_esquema.Corte(take=p["take"], duracao_frames=max(p["img_dur"], 1), inicio_no_take=max(p["img_ini"], 0), corte_de_som=p["corte_de_som"], som_frames=p["som_frames"]))
    try:
        _esquema._validar_o_som_entre_cortes(cortes_para_validar)
    except _esquema.PlanoInvalido as e:
        problemas.append(str(e))

    # ⭐ A mesma conferência do `conferir_o_mapa`, com o intervalo do SOM (é ele que carrega a fala).
    atribuicoes = [_mapa.Atribuicao(p["falas"], p["take"], p["som_ini"], p["som_fim"] - p["som_ini"], p["porque"]) for p in planos]
    conf = _mapa.conferir(falas, atribuicoes)
    problemas.extend(conf.problemas)
    problemas.extend(_mapa.ancorar(falas, atribuicoes, _roteiro.falado_no_take(BIN)))
    declaradas = {int(s["fala"]) for s in resposta.get("sacrificadas", []) if s.get("fala") is not None}
    for n in conf.sacrificadas:
        if n not in declaradas:
            problemas.append(f"a fala {n} do roteiro não entrou e não está em `sacrificadas`.")
        elif cortadas_ok is not None and n not in cortadas_ok:
            # ⛔ Quem corta fala é o Diretor. Sem isto, o Editor pode "resolver" uma reprovação tirando material (medido: 33 → 10 momentos).
            problemas.append(f"a fala {n} saiu da montagem, e o Diretor não a cortou. Devolva-a.")
    if cortadas_ok:
        falado = _roteiro.falado_no_take(BIN)
        por_n = {f.n: f for f in falas}
        for p in planos:
            dito = falado(p["take"], p["som_ini"], p["som_fim"] - p["som_ini"]) or ""
            for n in cortadas_ok - set(p["falas"]):
                f = por_n.get(n)
                if f and len(_mapa._palavras(f.texto)) >= MIN_PALAVRAS_PARA_ACUSAR and _mapa.parecenca(f.texto, dito) >= PRESENTE:
                    problemas.append(f"plano {p['n']}: o trecho do take ainda contém a fala {n}, que o Diretor cortou. Passe por ela trocando de take.")
    return planos, problemas


def legivel(planos: list[dict]) -> str:
    linhas = []
    for p in planos:
        ls = "" if p["corte_de_som"] == "junto" else f" · {'J' if p['corte_de_som'] == 'antes' else 'L'} {p['som_frames']} q"
        linhas.append(f"plano {p['n']}: {p['take']} · {p['img_dur'] / QPS:.1f} s · falas {p['falas']}{ls} · {p['porque']}")
    return "\n".join(linhas)


def cortes_do_diretor(*direcoes: dict) -> set[int]:
    return {int(c["fala"]) for d in direcoes for c in d.get("cortes_de_fala", []) if c.get("fala") is not None}


def editar(direcao: dict, falas: list, disponiveis: list, opcoes: str, por_id: dict, duracoes: dict, anterior: dict | None = None, externas: str = "") -> dict:
    """O Editor com as voltas da conferência. ⛔ Teto de voltas: reprovação em laço já fez modelo cortar material para passar."""
    lista = [{"n": f.n, "personagem": f.personagem, "texto": f.texto} for f in falas]
    resposta, reprovacao = anterior, ""
    historico = []
    planos = []
    for volta in range(MAX_VOLTAS + 1):
        try:
            nova = agente("agente-editor", {"direcao": direcao, "falas": lista, "planos_disponiveis": disponiveis, "opcoes": opcoes,
                                            "anterior": json.dumps(resposta, ensure_ascii=False) if resposta else "", "reprovacao": reprovacao, "observacoes_externas": externas})
        except T.TurnoFalhou as e:
            # Modelo que não responde não pode derrubar o fluxo: fica o histórico, e quem chamou decide.
            historico.append({"volta": volta, "planos": 0, "problemas": [f"o Editor não respondeu: {e}"]})
            break
        planos, problemas = traduzir(nova, por_id, falas, duracoes, cortes_do_diretor(direcao), TAKES_COM_PALAVRAS)
        historico.append({"volta": volta, "planos": len(nova["planos"]), "problemas": problemas})
        print(f"   editor volta {volta}: {len(nova['planos'])} planos, {len(problemas)} problema(s)")
        resposta = nova
        if not problemas:
            return {"fecha": True, "resposta": nova, "planos": planos, "historico": historico}
        reprovacao = "\n".join(problemas[:12])
    return {"fecha": False, "resposta": resposta, "planos": planos, "historico": historico}


def chamar_com_imagens(a, blocos: list[dict], prazo: float = 300) -> dict:
    """Um turno com imagens, pelo stdin. O turno magro só leva texto, e a linha de comando não comportaria os quadros."""
    from cicloassist.motor.claude import achar_o_cli, ambiente_do_modelo
    nome, ambiente = ambiente_do_modelo(_config.modelo_guardado())
    comando = [achar_o_cli(), "-p", "--system-prompt", a.instrucao, "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--strict-mcp-config", "--restricted", "--tools", ""] + (["--model", nome] if nome else [])
    entrada = json.dumps({"type": "user", "message": {"role": "user", "content": blocos}}, ensure_ascii=False)
    erro = ""
    for tentativa in range(2):
        t0 = time.monotonic()
        r = subprocess.run(comando, input=entrada, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=prazo, env=ambiente,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for linha in r.stdout.splitlines():
            try:
                ev = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "result":
                continue
            uso = T._uso(ev)
            registrar_uso(a.nome, uso, time.monotonic() - t0)
            texto = str(ev.get("result") or "")
            try:
                dados = T.objeto_json(texto)
                A.conferir_saida(a, dados)
            except (A.AgenteFalhou, T.TurnoFalhou) as e:
                erro = f"{e} · resposta começa com: {texto[:200]!r} · termina com: {texto[-120:]!r}"
                print(f"   {a.nome}: tentativa {tentativa + 1} falhou: {erro}")
                break
            print(f"   {a.nome}: {time.monotonic() - t0:.0f} s · uso {json.dumps(uso, ensure_ascii=False)}")
            return dados
        else:
            erro = f"sem resposta. {r.stderr[-400:]}"
    raise T.TurnoFalhou(f"{a.nome}: {erro}")


def continuidade(planos: list[dict], pasta: Path) -> dict:
    a = A.ler_texto((PASTA / "agentes" / "agente-continuista.md").read_text(encoding="utf-8"))
    (pasta / "continuidade").mkdir(exist_ok=True)
    pedidos: dict[str, list[int]] = {}
    pontos = []
    for i in range(len(planos) - 1):
        sai, entra = planos[i], planos[i + 1]
        pontos.append((i + 1, sai, sai["img_ini"] + sai["img_dur"] - 1, entra, entra["img_ini"]))
    fontes = {n: resolver(BIN, n) for n in {p["take"] for p in planos}}
    for _, sai, q_sai, entra, q_entra in pontos:
        pedidos.setdefault(sai["take"], []).append(fontes[sai["take"]].imagem.inicio_frames + q_sai)
        pedidos.setdefault(entra["take"], []).append(fontes[entra["take"]].imagem.inicio_frames + q_entra)
    jpegs = {}
    for take, posicoes in pedidos.items():
        t = fontes[take]
        jpegs[take] = _frames.extrair_varios(str(t.imagem.arquivos[0]), sorted(set(posicoes)), Fraction(t.fps["num"], t.fps["den"]))
    blocos: list[dict] = []
    descricao = []
    for n, sai, q_sai, entra, q_entra in pontos:
        for lado, p, q in (("sai", sai, q_sai), ("entra", entra, q_entra)):
            bruto = jpegs[p["take"]][fontes[p["take"]].imagem.inicio_frames + q]
            (pasta / "continuidade" / f"corte{n:02d}_{lado}.jpg").write_bytes(bruto)
            blocos.append({"type": "text", "text": f"Corte {n}, quadro que {lado}: {p['take']}"})
            blocos.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(bruto).decode("ascii")}})
        descricao.append(f"corte {n}: {sai['take']} para {entra['take']}")
    blocos.append({"type": "text", "text": "cortes:\n" + "\n".join(descricao)})
    return chamar_com_imagens(a, blocos)


#: A cena 7 no corte final do curta (`PRODA_RELINKER_ALTA.aaf`). ⛔ Só para o placar: nenhum agente vê isto.
REFERENCIA = {"duracao_s": 99.2, "planos": 8, "takes": ["C07_P01-002", "C07_P02-002", "C07_P02-004", "C07_P03-001"], "cortes": 7, "lj": 4}


def placar(planos: list[dict]) -> dict:
    lj = [p["som_frames"] for p in planos[1:] if p["corte_de_som"] != "junto"]
    return {"gerado": {"duracao_s": round(sum(p["img_dur"] for p in planos) / QPS, 1), "planos": len(planos), "takes": sorted({p["take"] for p in planos}),
                       "cortes": len(planos) - 1, "lj": len(lj), "lj_quadros": lj, "duracao_media_s": round(sum(p["img_dur"] for p in planos) / QPS / max(1, len(planos)), 1)},
            "corte_final": REFERENCIA}


def main() -> int:
    caminho_roteiro = arg("--roteiro", ROTEIRO)
    etapas = Etapas(Path(arg("--saida", SAIDA)), arg("--refazer"))
    ate = arg("--ate", "tudo")
    t0 = time.monotonic()

    texto = documento.ler(Path(caminho_roteiro))
    falas = _mapa.estruturar(texto)
    if not falas:
        print("⛔ sem roteiro legível: o fluxo não avança")
        return 2
    takes = carregar_takes()
    medida = medir(falas, takes)
    print(json.dumps(medida["numeros"], ensure_ascii=False, indent=1))
    print(medida["matriz"])
    lista = [{"n": f.n, "personagem": f.personagem, "texto": f.texto} for f in falas]

    estrutura = etapas.rodar("1_roteiro", lambda: agente("agente-de-roteiro", {"roteiro": texto, "falas": lista}))
    for p in conferir_beats(estrutura, len(falas)):
        print("   ⚠️", p)

    revisao = etapas.rodar("2_revisor", lambda: agente("agente-revisor", {
        "estrutura": estrutura, "falas": lista, "matriz": medida["matriz"], "fora_do_roteiro": medida["fora"], "numeros": medida["numeros"]}))
    print(f"   revisor: parar={revisao['parar']} · {revisao['motivo']}")
    para_o_codigo = medida["numeros"]["cobertura"] < COBERTURA_PARA_SEGUIR
    print(f"   código: cobertura {medida['numeros']['cobertura']:.0%}, parar={para_o_codigo}")
    if para_o_codigo or revisao["parar"]:
        print(f"⛔ FLUXO PAROU. Pergunta ao editor: {revisao.get('pergunta') or revisao['motivo']}")
        return 3
    if ate == "revisor":
        return 0

    dialogo = etapas.rodar("3_dialogo", lambda: fazer_dialogo(falas, revisao, takes, caminho_roteiro))
    print(f"   diálogo: fecha={dialogo['fecha']} · {len(dialogo['momentos'])} momentos · "
          f"{len(dialogo['segmentos_excluidos'])} excluídos · {len(dialogo['segmentos_sem_destino'])} sem destino")
    if ate == "dialogo" or not dialogo["fecha"]:
        return 0 if dialogo["fecha"] else 4

    print(f"   bordas medidas na lapela: {aplicar_bordas(takes, Path(arg('--saida', SAIDA)))}")
    disponiveis = planos_disponiveis(revisao)
    opcoes, por_id = mapa_de_opcoes(dialogo, takes)
    duracoes = {n: resolver(BIN, n).duracao_frames for n in TAKES}
    momentos = "\n".join(f"{m['fala']}.{m['variante']} {m.get('personagem') or ''}: {m['texto']} ({len(m['trechos'])} leituras)" for m in dialogo["momentos"])
    entrada_diretor = {"estrutura": estrutura, "falas": lista, "planos_disponiveis": disponiveis, "momentos": momentos}
    direcao = etapas.rodar("4_diretor", lambda: agente("agente-diretor", {**entrada_diretor, "corte_proposto": "", "notas_de_continuidade": ""}))

    corte = etapas.rodar("5_editor", lambda: editar(direcao, falas, disponiveis, opcoes, por_id, duracoes))
    if not corte["fecha"]:
        print("⛔ o Editor não passou na conferência:", corte["historico"][-1]["problemas"][:6])
        return 5
    print(legivel(corte["planos"]))

    pasta = Path(arg("--saida", SAIDA))
    print(f"   cortes do Diretor: {sorted(cortes_do_diretor(direcao))}")
    # ⭐ O parecer vem antes da continuidade: o Continuista tem de ver a versão que será entregue.
    parecer = etapas.rodar("6_parecer", lambda: agente("agente-diretor", {**entrada_diretor, "corte_proposto": legivel(corte["planos"]), "notas_de_continuidade": ""}))
    p = parecer["parecer"]
    # ⭐ A lista do parecer SUBSTITUI a anterior: o Diretor pode voltar atrás num corte que, lido na montagem, quebrou a lógica.
    # O editor tem a última palavra: `--devolver 3` tira a fala da lista de cortes, seja o que for que o Diretor tenha decidido.
    devolver = {int(x) for x in arg("--devolver").split(",") if x}
    direcao_final = {**direcao, "cortes_de_fala": [c for c in parecer.get("cortes_de_fala", []) if int(c["fala"]) not in devolver]}
    print(f"   cortes depois do parecer: {sorted(cortes_do_diretor(direcao_final))}")
    print(f"   diretor: aprovado={p.get('aprovado')} · {p.get('resumo')}")
    if not p.get("aprovado") and p.get("pontos"):
        def rever2():
            texto = "\n".join(f"plano {x['plano']}: {x['o_que']}" for x in p["pontos"])
            if devolver:
                texto += f"\nDecisão do editor: a(s) fala(s) {sorted(devolver)} do roteiro voltam para a montagem."
            novo = editar(direcao_final, falas, disponiveis, opcoes, por_id, duracoes, anterior=corte["resposta"], externas=texto)
            return novo if novo["fecha"] else {**corte, "aviso": "a revisão pelo Diretor não fechou; ficou a versão anterior"}
        corte = etapas.rodar("7_editor_revisao", rever2)

    notas = etapas.rodar("8_continuista", lambda: continuidade(corte["planos"], pasta))
    problemas_de_continuidade = [c for c in notas["cortes"] if c.get("nivel") == "problema"]
    print(f"   continuista: {notas['resumo']} · {len(problemas_de_continuidade)} problema(s)")
    if problemas_de_continuidade:
        def rever():
            texto = "\n".join(f"corte {c['corte']}: {c['o_que']}" for c in problemas_de_continuidade)
            novo = editar(direcao_final, falas, disponiveis, opcoes, por_id, duracoes, anterior=corte["resposta"], externas=texto)
            return novo if novo["fecha"] else {**corte, "aviso": "a revisão pela continuidade não fechou; ficou a versão anterior"}
        corte = etapas.rodar("9_editor_continuidade", rever)

    final = {**corte, "placar": placar(corte["planos"]), "ressalvas": [x for x in p.get("pontos", [])], "continuidade": notas,
             "cortes_de_fala": direcao_final.get("cortes_de_fala", [])}
    (pasta / "corte_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    (pasta / "uso.json").write_text(json.dumps(USOS, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== CORTE ===\n" + legivel(corte["planos"]))
    print("\n=== PLACAR ===\n" + json.dumps(final["placar"], ensure_ascii=False, indent=1))
    print(f"custo desta execução: US$ {sum(float(u.get('custo_usd') or 0) for u in USOS):.3f}")
    print(f"fim em {(time.monotonic() - t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
