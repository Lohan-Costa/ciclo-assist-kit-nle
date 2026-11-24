#!/usr/bin/env python3
"""
regua.py — roda o sync de uma diária do Media Composer e mede contra o gabarito.

## Por que existe

O as notas internas manda, em maiúsculas, **começar qualquer mexida no motor
rodando a régua** — e não havia como rodá-la. O `gabarito_avb.py` mede um
`resultado.json` contra um gabarito, mas produzir esse `resultado.json` exigia
abrir o app, arrastar as bins no painel e esperar; ou seja, a régua que existe para
ser barata custava uma sessão de interface.

Isto fecha o ciclo: **bins do MC → sync → medição**, num comando, sem GUI.

## Uso

    python tools/regua.py <gabarito.json> "<BIN DE CÂMERA>" "<BIN DE SOM>" [mais bins…]

Os caminhos de bin são as CHAVES relativas do projeto aberto, como o painel as
mostra (`O PRODUCAO-A/D03/D03_CAM A`). Sem argumento de bin, lista as do projeto
aberto e para.

    --resultado <arquivo.json>   guarda o payload do sync (para remedir sem ressincronizar)
    --metodo hybrid|tc|waveform  o mesmo seletor do painel (padrão: hybrid)

⚠️ **Precisa do Media Composer ABERTO** no projeto da diária: é dele que saem os
MobIDs, o `Name`/`Tracks` de cada master e o caminho da mídia gerenciada.

⚠️ **A bin de som vem DEPOIS da de câmera.** A ordem dos argumentos é a ordem das
fontes, e é ela que decide qual cartão é CAM A — igual ao painel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def rotulo(indice: int, e_som: bool, ja_som: int) -> str:
    """CAM A, CAM B… para vídeo; SOM DIRETO para áudio — a regra do painel."""
    if e_som:
        return "SOM DIRETO" if ja_som == 0 else f"SOM DIRETO {ja_som + 1}"
    return "CAM " + chr(ord("A") + indice)


def montar_clipes(mc, chaves: list[str]) -> tuple[list[dict], dict[str, str]]:
    """As bins pedidas viram a lista de clipes do motor, e o mapa arquivo→MobID.

    É o mesmo caminho do painel: `resolver_mobs` acha os arquivos (agora por busca
    dirigida) e `e_som` diz, pela ESSÊNCIA, quem é som — a extensão não serve,
    porque a mídia gerenciada do Avid é toda `.mxf`, som inclusive.
    """
    from avid.masters import e_som, resolver_mobs
    from main import mapa_arquivo_para_mob

    mapa_bins = {mc.chave_de_bin(b): b for b in mc.bins()}
    clipes: list[dict] = []
    todos_caminhos: dict[str, list[str]] = {}
    cameras = 0
    sons = 0

    for chave in chaves:
        alvo = mapa_bins.get(chave)
        if not alvo:
            raise SystemExit(f"bin não encontrada: {chave!r}")
        itens = mc.itens_de(alvo)
        r = resolver_mobs(mc, [i.mob_id for i in itens])
        caminhos, so_audio = r["caminhos"], r["so_audio"]
        todos_caminhos.update(caminhos)

        arquivos = [q for i in itens for q in caminhos.get(i.mob_id, [])]
        if not arquivos:
            print(f"  ⚠ {chave}: nenhum arquivo resolvido — pulada")
            continue
        com_arquivo = [i for i in itens if caminhos.get(i.mob_id)]
        som = all(e_som(i.mob_id, caminhos, so_audio) for i in com_arquivo)
        rot = rotulo(cameras, som, sons)
        cameras += 0 if som else 1
        sons += 1 if som else 0
        print(f"  {rot}: {len(com_arquivo)} clipes · {len(arquivos)} arquivos ({chave})")
        for ordem, caminho in enumerate(arquivos):
            c = {"path": caminho, "group_id": rot, "group_order": ordem}
            if som:
                c["kind"] = "sound"
            clipes.append(c)

    return clipes, mapa_arquivo_para_mob(todos_caminhos)


def sincronizar(clipes: list[dict], nome: str, metodo: str) -> dict:
    """O MESMO caminho do sidecar (`_sync_one_daily`), sem a ponte de IPC."""
    from sync.engine import run as sync_run
    from sync.serialize import daily_to_dict

    ultimo = [""]

    def progresso(msg, cur, tot, overall=None):
        linha = f"  [{(overall or 0) * 100:5.1f}%] {msg} ({cur}/{tot})"
        if linha != ultimo[0]:
            ultimo[0] = linha
            print(linha, end="\r", flush=True)

    daily = sync_run(clipes, progress=progresso, project_name=nome,
                     sync_method=metodo)
    print(" " * 78, end="\r")
    return {"name": nome, "groups": [{**daily_to_dict(daily), "id": nome}]}


def main() -> int:
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    # ⭐ A régua escreve no MESMO `sincronizar.log` do app, marcada como `regua`. Ela roda
    # exatamente o caminho de resolução de mídia que o painel roda — então é o jeito
    # mais barato que existe de LER a instrumentação sem abrir a interface, e é aqui
    # que se confere que uma mudança no log diz o que devia antes de ela ir a campo.
    #
    # ⚠️ Chamado ANTES de qualquer `import main`: o `main.py` também configura o log
    # (como `sidecar`), e quem chega primeiro é quem nomeia a execução.
    import registro
    registro.configurar("regua")

    args = [a for a in sys.argv[1:]]
    metodo, resultado_em = "hybrid", None
    for flag, destino in (("--metodo", "metodo"), ("--resultado", "resultado")):
        if flag in args:
            i = args.index(flag)
            valor = args[i + 1]
            args = args[:i] + args[i + 2:]
            if destino == "metodo":
                metodo = valor
            else:
                resultado_em = valor

    from avid.mcapi import MediaComposer

    if not args:
        with MediaComposer() as mc:
            print("Bins do projeto aberto:")
            for b in sorted((mc.chave_de_bin(x) for x in mc.bins()), key=str.casefold):
                print("  ", b)
        print(__doc__.split("## Uso")[1].split("⚠️")[0])
        return 2

    gabarito = Path(args[0])
    chaves = args[1:]
    if not chaves:
        print("faltam as bins — rode sem argumentos para vê-las")
        return 2

    print(f"Lendo {len(chaves)} bin(s) do Media Composer…")
    with MediaComposer() as mc:
        clipes, mob_ids = montar_clipes(mc, chaves)
    if not clipes:
        print("nenhum clipe resolvido")
        return 1

    print(f"\nSincronizando {len(clipes)} arquivos (método: {metodo})…")
    resultado = sincronizar(clipes, gabarito.stem, metodo)

    if resultado_em:
        Path(resultado_em).write_text(
            json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"resultado guardado em {resultado_em}")

    # A `selecao` que o `gabarito_avb` pede é só o `mob_ids`: é ele que liga um
    # arquivo de nome de HASH ao masterclipe que o gabarito nomeia. Sem ele, a
    # medição compararia `V01.E69CCF0F…` com `projeto exemplo - 05-04 c11 p1-t001` e
    # acusaria o motor de 37 erros que são do instrumento.
    from tools.gabarito_avb import medir

    gab = json.loads(gabarito.read_text(encoding="utf-8"))
    print()
    # O código de saída É o nº de erros CALADOS — o número que mais importa.
    return medir(gab, resultado, {"mob_ids": mob_ids})


if __name__ == "__main__":
    raise SystemExit(main())
