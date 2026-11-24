"""Confere, num BRAW de verdade, que o decodificador do fabricante está de pé.

    python tools/conferir_braw.py <arquivo.braw> [--quadros 6]

⭐ Existe porque o teste da suíte não pode: ele roda em máquina sem o SDK, sem BRAW e sem
o binário construído. Isto é o "com os olhos" — o JPEG sai numa pasta e o caminho é dito.

⚠️ **Olhe o quadro.** O BRAW é gravado em log, e um decodificador que não aplique gamma de
vídeo devolve uma imagem LAVADA — que decodifica sem erro nenhum e faz o modelo descrever
*"luz sem cor"* de um dia de sol. Erro que não levanta exceção só aparece no olho.
"""

from __future__ import annotations

import sys
import time
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import decodificadores as sdk  # noqa: E402
from cicloassist.midia import frames  # noqa: E402
from cicloassist.midia import identidade as ident  # noqa: E402


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if not a.startswith("--")]
    quantos = 6
    if "--quadros" in sys.argv:
        quantos = int(sys.argv[sys.argv.index("--quadros") + 1])
    if not argumentos:
        print(__doc__)
        return 2
    arquivo = Path(argumentos[0])
    if not arquivo.is_file():
        print(f"não achei {arquivo}")
        return 2

    print("decodificadores instalados:")
    for tipo, d in sdk.situacao().items():
        print(f"  {tipo:6s} {'SIM' if d['temos'] else 'não'}   {d['nome']}")
    tipo = sdk.tipo_de(arquivo)
    if not tipo:
        print(f"\n{arquivo.name} não é RAW de câmera conhecido ({arquivo.suffix})")
        return 2
    print(f"\n{arquivo.name} → {sdk.NOMES[tipo]}")

    sonda = ident.sondar(arquivo)
    print(f"  o ffprobe lê do contêiner: {sonda.get('quadros')} quadros, "
          f"{sonda.get('fps')} fps, TC {sonda.get('tc') or '—'}")
    # ⭐ A pergunta que vem ANTES de decodificar: será que este material já foi analisado
    #   pelo transcode dele? (`identidade.achar`, que casa RAW pelo SOM.)
    achado = ident.achar(arquivo)
    if achado.midia is not None:
        print(f"  ⭐ este clipe já está no cache como {achado.midia.nome!r} "
              f"(por {achado.como}) — os quadros dele podem já existir")

    quadros_no_arquivo = int(sonda.get("quadros") or 0)
    posicoes = frames.distribuir(0, quadros_no_arquivo, quantos) or [0]
    saida = Path.cwd() / "quadros_braw"
    saida.mkdir(exist_ok=True)

    comecou = time.time()
    try:
        achados = frames.extrair_varios(arquivo, posicoes,
                                        Fraction(sonda.get("fps") or "24000/1001"))
    except sdk.SdkIndisponivel as e:
        print(f"\n⛔ {e}")
        return 1
    except sdk.DecodificacaoFalhou as e:
        print(f"\n⛔ {e}")
        return 1
    gasto = time.time() - comecou

    for posicao, jpeg in achados.items():
        destino = saida / f"{arquivo.stem}_{posicao:06d}.jpg"
        destino.write_bytes(jpeg)
        marca = "JPEG" if jpeg[:2] == b"\xff\xd8" else "⛔ NÃO É JPEG"
        print(f"  quadro {posicao:6d}: {len(jpeg):7d} bytes  {marca}")
    print(f"\n{len(achados)} quadro(s) em {gasto:.2f}s → {saida}")
    print("⚠️ Abra os JPEG: quadro lavado quer dizer gamma de log, e isso não levanta erro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
