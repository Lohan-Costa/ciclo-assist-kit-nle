"""Um modelo LOCAL decupa tão bem quanto o Haiku? O número, antes de comprar máquina.

    python spikes/o_modelo_local_decupa.py --ollama http://192.168.x.y:11434
    set CICLOASSIST_OLLAMA=http://192.168.x.y:11434   (e aí sem --ollama)
    python spikes/o_modelo_local_decupa.py --modelo qwen2.5vl:7b
    python spikes/o_modelo_local_decupa.py --json-forcado   # ver a nota do final

⛔⛔ **NUNCA contra este notebook.** TELAS AZUIS repetidas rodando modelo local ao lado do
Media Composer (RTX 4050, 6 GB) — a última em 2026-09-13, com o `gemma3:4b` carregando,
antes de escrever uma linha. E o `qwen2.5vl:7b` (6,7 GB) ficou 51% CPU / 49% GPU e
estourou 600 s na primeira mídia. Por isso não há endereço padrão: o servidor é o Mac mini na rede
(`docs/spec/2026-09-13-servidor-de-percepcao-mac.md`), e quem esquecer de dizer onde ele está
recebe um erro — não uma tela azul.

O ADR 0001 rejeitou LLM local com a frase *"a local não dá conta do raciocínio pedido"*.
É afirmação, não medida — e foi escrita quando a **decupagem em lote não existia**. A
decupagem é o único lugar do produto onde a assinatura do editor é gasta sem ele pedir
(US$ 2,48 por 165 mídias, medido em 2026-09-11), e é a tarefa menos parecida com
raciocínio que existe aqui: olhar seis quadros e preencher cinco campos de vocabulário
fechado.

## ⭐⭐ Por que isto é barato de medir

Na conversa, os quadros **não vão no prompt**: o modelo chama `ver_quadros_da_midia` e o
nosso MCP devolve blocos de imagem. Essa indireção existe porque o `claude -p` é um agente
com ferramentas. **Para o Ollama ela desaparece** — nós já sabemos quais seis quadros
mandar. Das quatro coisas que um motor local teria de reimplementar (loop de ferramentas,
portão, `--resume`, tradução de eventos), a decupagem precisa de **zero**.

⇒ Este spike é transporte novo reaproveitando a validação inteira: `_json_da_resposta`,
`notas_da_resposta` e `decupagem.normalizar` são os MESMOS que o produto usa. Se fossem
cópias, o estudo mediria o meu parser em vez do modelo.

## O gabarito, e o que ele aguenta responder

As mídias que já têm nota de `escopo: "midia"` no cache foram decupadas pelo Haiku 4.5 com
os mesmos seis quadros. Comparar os cinco campos FECHADOS é comparação exata, sem
julgamento — e é por isso que eles existem (`midia/decupagem.py`: *prosa não filtra*).

⚠️⚠️ **A amostra é pequena: serve para REPROVAR, não para aprovar com confiança.** Dez
mídias dão 50 campos; um acerto alto aqui autoriza a rodada maior, não a decisão.

⚠️ E o que o placar NÃO cobre: a prosa. *"close noturno no consultório"* é achado pela
`descricao`, e descrição não tem nota automática — por isso o spike imprime as duas lado a
lado para o editor ler.

⛔ **Nada é gravado no cache.** O gabarito é gabarito; e mídia sem seis quadros já prontos é
PULADA, para não haver nem extração de ffmpeg (que gravaria quadro novo).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# ⚠️ E o stderr também: `sys.exit("mensagem")` sai por ele, e sem isto as recusas lá de
#    baixo chegavam como "est� o Ollama" — justamente o texto que precisa ser lido.
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.mcp.ferramentas.midia import quadros_de  # noqa: E402
from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.midia import decupagem as _decupagem  # noqa: E402
from cicloassist.motor import decupador as _dec  # noqa: E402
# ⭐ A persona plana mora no PRODUTO desde 2026-09-13: uma cópia aqui faria o placar medir
#   um prompt que a fila não manda.
from cicloassist.motor.percepcao import persona_plana  # noqa: E402

#: ⛔ Sem padrão de propósito — ver o topo. O endereço vem da bandeira ou do ambiente.
OLLAMA = os.environ.get("CICLOASSIST_OLLAMA", "")
MODELO = "qwen2.5vl:7b"

#: Os cinco campos fechados, na ordem em que o editor pensa neles.
CAMPOS = ["enquadramento", "angulo", "camera", "local", "momento"]

#: ⛔⛔ MEDIDO: o contexto PADRÃO do Ollama é **4096 tokens**, e seis quadros são **6.229** —
#: o pedido volta 400 com `exceed_context_size_error`. Quem não souber disso conclui que o
#: modelo não aguenta a tarefa, quando o que não cabe é o balde.
#: ⚠️ E `num_ctx` maior é KV cache maior, ou seja VRAM: numa placa de 6 GB com o modelo de
#: 6 GB dentro, subir isto é o que empurra a inferência para a CPU.
CONTEXTO = 12288


def pedir(url: str, caminho: str, corpo: dict | None = None, timeout: float = 300.0) -> dict:
    """POST/GET no Ollama com a stdlib. ⚠️ Sem framework — regra da casa."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(
        url.rstrip("/") + caminho, data=dados,
        headers={"Content-Type": "application/json"},
        method="POST" if dados else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def conferir_o_modelo(url: str, modelo: str) -> list[str]:
    """As capacidades do modelo, e um aviso que evita horas de confusão.

    ⛔⛔ Medido no notebook: dos 5 modelos já baixados (`gemma4`, `llama3.1:8b`, `mistral`,
    `gemma2:9b`, `llama3.2:3b`), **nenhum vê imagem**.

    ⚠️ O que um deles FARIA com as imagens **não foi medido** — este spike recusa antes.
    A suposição é que aceitaria calado e responderia uma decupagem plausível e inventada;
    o placar sairia baixo e a conclusão seria "modelo local não serve", quando o certo é
    "este modelo não vê". Conferir custa um pedido; descobrir pelo placar custa a rodada.
    """
    try:
        info = pedir(url, "/api/show", {"model": modelo}, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            tags = pedir(url, "/api/tags", timeout=30)
            tem = ", ".join(m["name"] for m in tags.get("models", []))
            sys.exit(f"o Ollama não tem {modelo!r}.\nbaixe com: ollama pull {modelo}\n"
                     f"modelos presentes: {tem}")
        raise
    return list(info.get("capabilities") or [])


def do_gabarito() -> list[tuple[str, dict]]:
    """`(chave, nota do Haiku)` de cada mídia decupada que tenha quadros prontos."""
    fora = []
    pares = []
    for pasta in sorted(_cache.raiz().iterdir()):
        if not pasta.is_dir():
            continue
        try:
            midia = _cache.Midia(pasta.name)
        except Exception:      # noqa: BLE001 — pasta que não é mídia
            continue
        notas = [n for n in midia.ler_notas() if n.get("escopo") == "midia"]
        if not notas:
            continue
        if len(midia.quadros_guardados()) < _dec.QUADROS:
            # ⛔ Pular em vez de extrair: extrair GRAVA quadro no cache do editor, e este
            #    spike é de leitura.
            fora.append(notas[0].get("trecho") or pasta.name[:12])
            continue
        pares.append((pasta.name, notas[0]))
    if fora:
        print(f"⚠️ {len(fora)} mídia(s) do gabarito ficaram fora por não ter "
              f"{_dec.QUADROS} quadros prontos: {', '.join(fora)}")
    return pares


def decupar_local(url: str, modelo: str, chave: str, forcar_json: bool,
                  contexto: int = CONTEXTO, prazo: float = 300.0) -> tuple[str, dict]:
    """Manda os seis quadros ao Ollama. Devolve `(texto da resposta, medidas)`.

    ⭐ Os quadros saem de `quadros_de()`, a MESMA função que a ferramenta MCP usa — mesmas
    posições, mesmos bytes. Outra amostragem faria o placar medir a escolha de quadro em
    vez do modelo.
    """
    jpegs, posicoes, clipe = quadros_de(chave, _dec.QUADROS)
    # ⚠️ O `fps` do acervo é FRAÇÃO em texto (`24000/1001`), não decimal: `float()` nele
    #    levanta. A ferramenta MCP usa `Fraction` pelo mesmo motivo.
    fps = float(Fraction(str(clipe.get("fps") or 25)))
    # ⚠️ O mesmo cabeçalho que o MCP manda: sem ele o modelo recebe fotos soltas, sem saber
    #    de que material são nem quanto tempo as separa (ver `ferramentas/midia.py`).
    cabecalho = (
        f"{len(jpegs)} quadro(s) da mídia {clipe.get('nome') or chave[:12]}"
        + (f", duração {float(clipe['duracao_s']):.1f}s" if clipe.get("duracao_s") else "")
        + ".\nOs quadros estão em ordem, nos segundos "
        + ", ".join(f"{p / fps:.1f}" for p in posicoes)
        + " do material."
        + "\n\nDecupe esta mídia."
    )
    imagens = [base64.b64encode(j).decode("ascii") for j in jpegs]

    corpo = {
        "model": modelo,
        "stream": False,
        "options": {
            # ⚠️ `temperature: 0` porque o estudo tem de ser repetível: com amostragem,
            #    rodar duas vezes dá dois placares e nenhum deles é o número.
            "temperature": 0,
            "num_ctx": contexto,
        },
        "messages": [
            {"role": "system", "content": persona_plana()},
            {"role": "user", "content": cabecalho, "images": imagens},
        ],
    }
    if forcar_json:
        # ⚠️ `format: "json"` garante JSON sintático. NÃO é o padrão aqui de propósito: o
        #    Claude não recebeu essa ajuda, e "não respondeu em JSON" é um resultado que o
        #    placar precisa mostrar antes de ser consertado. É alavanca para a 2ª rodada.
        corpo["format"] = "json"

    t0 = time.monotonic()
    resposta = pedir(url, "/api/chat", corpo, timeout=prazo)
    segundos = time.monotonic() - t0
    texto = ((resposta.get("message") or {}).get("content") or "")
    return texto, {
        "segundos": segundos,
        "prompt_kb": (sum(len(i) for i in imagens) + len(cabecalho)) / 1024,
        "entrada_tokens": resposta.get("prompt_eval_count") or 0,
        "saida_tokens": resposta.get("eval_count") or 0,
    }


def comparar(local: dict, haiku: dict) -> dict[str, str]:
    """Campo a campo. `igual` · `diferente` · `omitido` · `a_mais`."""
    veredito = {}
    for campo in CAMPOS:
        a, b = local.get(campo), haiku.get(campo)
        if b and a:
            veredito[campo] = "igual" if a == b else "diferente"
        elif b and not a:
            veredito[campo] = "omitido"
        elif a and not b:
            veredito[campo] = "a_mais"
    return veredito


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ollama", default=OLLAMA,
                   help="URL do Ollama NA REDE (o Mac mini); também CICLOASSIST_OLLAMA")
    p.add_argument("--modelo", default=MODELO)
    p.add_argument("--midias", type=int, default=0, help="limita quantas (0 = todas)")
    p.add_argument("--json-forcado", action="store_true", dest="forcar_json")
    p.add_argument("--prazo", type=float, default=300.0,
                   help="segundos por mídia antes de desistir")
    p.add_argument("--contexto", type=int, default=CONTEXTO,
                   help=f"num_ctx do Ollama (padrão {CONTEXTO}; o dele é 4096 e NÃO cabe)")
    args = p.parse_args()
    if not args.ollama:
        sys.exit("diga onde está o Ollama: --ollama http://<ip do Mac>:11434 "
                 "(ou CICLOASSIST_OLLAMA). Não rode modelo local neste notebook.")
    host = args.ollama.split("//")[-1].split(":")[0].lower()
    if host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        # ⛔ Telas azuis repetidas. Recusar aqui custa uma linha; esquecer custa a
        #    sessão de edição de quem está com o Media Composer aberto.
        sys.exit("recusado: este endereço é o próprio notebook. O servidor é o Mac.")

    try:
        capacidades = conferir_o_modelo(args.ollama, args.modelo)
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"não falei com o Ollama em {args.ollama}: {e}\n"
                 f"confira o servidor do Mac (script `status` de lá) e o IP na rede.")
    print(f"modelo ...... {args.modelo}  capacidades: {capacidades or '(nenhuma)'}")
    if "vision" not in capacidades:
        print("⛔⛔ ESTE MODELO NÃO VÊ IMAGEM (não declara 'vision'). Mandar os quadros para ele")
        print("    arriscaria uma decupagem inventada e um placar que diria 'modelo local não")
        print("    serve' — quando o certo é 'este modelo não vê'. Use qwen2.5vl ou gemma3.")
        return 1

    pares = do_gabarito()
    if args.midias:
        pares = pares[:args.midias]
    if not pares:
        sys.exit("não há mídia decupada com quadros prontos no cache — nada a comparar.")
    print(f"gabarito .... {len(pares)} mídia(s) decupadas pelo Claude, "
          f"{_dec.QUADROS} quadros cada")
    print(f"contexto .... num_ctx={args.contexto} · uma mídia por pedido "
          f"(o CLI junta {_dec.POR_TURNO} para amortizar o piso; aqui não há piso)")
    print("=" * 78)

    placar = {"igual": 0, "diferente": 0, "omitido": 0, "a_mais": 0}
    falhou, inventou, segundos, prosa = [], [], [], []
    for chave, haiku in pares:
        nome = haiku.get("trecho") or chave[:12]
        try:
            texto, medidas = decupar_local(args.ollama, args.modelo, chave,
                                           args.forcar_json, args.contexto, args.prazo)
        except urllib.error.HTTPError as e:
            # ⛔ O corpo é onde o Ollama DIZ o que houve: o código 400 sozinho não
            #    distingue "não cabe no contexto" de "modelo não existe".
            corpo = e.read().decode("utf-8", "replace")[:200]
            print(f"⛔ {nome}: HTTP {e.code} — {corpo}")
            falhou.append((nome, corpo[:60]))
            continue
        except (urllib.error.URLError, OSError) as e:
            print(f"⛔ {nome}: não respondeu — {e}")
            falhou.append((nome, str(e)[:60]))
            continue
        segundos.append(medidas["segundos"])

        try:
            cru = _dec._json_da_resposta(texto)
            notas, avisos = _dec.notas_da_resposta(cru, [chave])
        except _dec.DecupagemFalhou as e:
            print(f"⛔ {nome}: não passou pelo validador — {e}")
            print(f"     respondeu: {texto[:120]!r}")
            falhou.append((nome, str(e)[:60]))
            continue

        nota = notas[chave]
        inventou.extend(avisos)
        veredito = comparar(nota, haiku)
        for v in veredito.values():
            placar[v] += 1
        resumo = " ".join(
            f"{c[:4]}={'=' if v == 'igual' else ('≠' if v == 'diferente' else ('-' if v == 'omitido' else '+'))}"
            for c, v in veredito.items())
        iguais = sum(1 for v in veredito.values() if v == "igual")
        print(f"{'OK ' if iguais else 'ruim'} {nome[:34]:34s} {medidas['segundos']:5.1f}s  "
              f"{medidas['prompt_kb']:5.0f}KB  {resumo}")
        for campo, v in veredito.items():
            if v == "diferente":
                print(f"       {campo}: local={nota[campo]!r} gabarito={haiku[campo]!r}")
        prosa.append((nome, nota.get("descricao", ""), haiku.get("descricao", "")))

    total = sum(placar.values())
    comparaveis = placar["igual"] + placar["diferente"] + placar["omitido"]
    print("=" * 78)
    print(f"campos comparados ... {total}")
    for k in ("igual", "diferente", "omitido", "a_mais"):
        print(f"   {k:10s} {placar[k]:3d}")
    if comparaveis:
        print(f"\nACERTO .............. {100 * placar['igual'] / comparaveis:.0f}% "
              f"({placar['igual']} de {comparaveis} campos que o gabarito tem)")
    print(f"não viraram nota .... {len(falhou)} de {len(pares)}")
    print(f"valor fora do vocabulário: {len(inventou)}")
    for a in inventou[:5]:
        print(f"   {a}")
    if segundos:
        print(f"segundos por mídia .. mediana {sorted(segundos)[len(segundos)//2]:.1f}s "
              f"(Haiku mediu ~10 s com 3 mídias por turno)")

    print("\n" + "=" * 78)
    print("A PROSA — é ela que responde 'close noturno no consultório', e não tem nota")
    print("=" * 78)
    for nome, local, haiku in prosa:
        print(f"\n{nome}")
        print(f"  local : {local[:300]}")
        print(f"  Haiku : {haiku[:300]}")

    print("\n⚠️ Critério combinado ANTES de olhar: ≥70% e nenhum valor inventado manda a")
    print("   decupagem para o local; <50% fecha o assunto com medida em vez de frase.")
    print("   Entre os dois, ampliar o gabarito antes de decidir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
