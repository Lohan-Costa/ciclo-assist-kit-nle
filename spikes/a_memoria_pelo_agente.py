"""A3: o agente de metadado de verdade, pela mesma ferramenta do chat, nos materiais reais. Sai 0 se nenhuma regra aprovada contradiz o metadado.

Gasta um turno magro por material com dúvida (~2 mil tokens). Não grava memória: a pasta de dados é temporária.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# ⭐ A conta do app mora na pasta de dados real: só a memória fica no temporário.
os.environ["CICLOASSIST_CLAUDE_CONFIG"] = os.environ.get("LOCALAPPDATA", "") + r"\CicloAssist\claude"
os.environ["CICLOASSIST_DADOS"] = tempfile.mkdtemp(prefix="a3_")

from cicloassist.mcp import ferramentas  # noqa: E402,F401
from cicloassist.mcp.ferramentas import metadado as M  # noqa: E402
from cicloassist.servico import arrastados  # noqa: E402

materiais = [Path(a) for a in sys.argv[1:]]
falhas = 0
for pasta in materiais:
    arrastados.autorizar(pasta)
    r = M.entender_metadados_da_diaria(str(pasta))
    print("=" * 90, "\n", pasta.name, json.dumps(r.get("resumo"), ensure_ascii=False), "| uso", r.get("uso"))
    if r.get("erro"):
        print("  ERRO:", r["erro"])
        falhas += 1
    print("  produção:", json.dumps(r.get("producao"), ensure_ascii=False))
    print(" ", r.get("manchete", ""))
    for x in r.get("regras_aprovadas", []):
        print("  ✅", x["forma"], "|", x["molde"], "|", x["certeza"], "|", x["exemplo"], "|", json.dumps(x["campos"]))
        falhas += sum(c["contradiz"] for c in x["campos"].values())
    for x in r.get("regras_reprovadas", []):
        print("  ⛔", x["forma"], "|", x["molde"], "|", x["problemas"])
    for p in r.get("perguntas", []):
        print("  ?", p["sobre"], p["formas"], "—", p["texto"], "| atalhos:", p["opcoes"])
    print("  sem regra:", r.get("formas_sem_regra"))
sys.exit(1 if falhas else 0)
