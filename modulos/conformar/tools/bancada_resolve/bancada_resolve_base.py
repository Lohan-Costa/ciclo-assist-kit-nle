"""O que as bancadas do Resolve compartilham: conectar, abrir o projeto, o `passo` cronometrado e gravar o json."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\laboratorio-de-midia")
from lab.bancadas import resolve as _b  # noqa: E402

S = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S, "bancada_out")
os.makedirs(OUT, exist_ok=True)


def abrir(nome):
    res = []

    def passo(rotulo, fn):
        t = time.time()
        try:
            v = fn()
            res.append({"passo": rotulo, "ok": v is not None and v is not False, "s": round(time.time() - t, 2),
                        "ret": repr(v)[:200]})
        except Exception as e:  # noqa: BLE001
            v = None
            res.append({"passo": rotulo, "ok": False, "s": round(time.time() - t, 2),
                        "erro": f"{type(e).__name__}: {e}"[:300], "tb": traceback.format_exc()[-400:]})
        print(("OK " if res[-1]["ok"] else "-- ") + rotulo, res[-1].get("ret", res[-1].get("erro")), flush=True)
        return v

    r = _b.conectar()
    pm = r.GetProjectManager()
    p = pm.GetCurrentProject()
    if p is None or p.GetName() != nome:
        p = pm.LoadProject(nome)
    return r, pm, p, p.GetMediaPool(), passo, res


def gravar(arq, r, res):
    json.dump({"resolve": r.GetVersionString(), "passos": res},
              open(os.path.join(S, arq), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(sum(x["ok"] for x in res), "de", len(res), "passos ok", flush=True)
