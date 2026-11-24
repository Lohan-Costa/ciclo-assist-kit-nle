import os, sys
sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\piloto")
from piloto import maos, olhos, vigia, apps, pontes
S = os.path.dirname(os.path.abspath(__file__))
DLPC = r"D:\PROGRAMAS COM CLAUDE\2 ATIVOS\_CICLO ASSIST\modulos\conformar"
for _p in (DLPC + r"\motor", DLPC + r"\plugins\media-composer\servico"):
    if _p not in sys.path: sys.path.insert(0, _p)
PRODC = r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar\03 CASOS\REAL\R04 PRODUCAO-C\ISOLADO\MIDIA"
