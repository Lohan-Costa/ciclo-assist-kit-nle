"""Carrega uma sequência da bin `B31 EDL SOM_CASOS v01` no Record (pela API; pula se já está lá — o MC responde
"Some mobs was skipped" ao recarregar a mesma). Python do APP (`.venv`), com o MC 25.12 aberto no `LAB COR MC`.

    .venv/bin/python spikes/edl_som_mc/carregar.py "B31 S6 AUTOSYNC"
"""
import sys, os, time
C = "/Volumes/SSD/PROGRAMAS COM CLAUDE/2 ATIVOS/_CICLO ASSIST/modulos/conformar"
sys.path[:0] = [os.path.join(C, "plugins", "media-composer", "servico"), os.path.join(C, "motor")]
from avid.mcapi import MediaComposer
P = "/Volumes/SSD/MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/PROJETO/LAB COR MC/B31 EDL SOM_CASOS v01.avb"
with MediaComposer() as m:
    seqs = {i.name: i.mob_id for i in m.itens_da_bin(m.caminho_relativo_da_bin(P), flags=("sequences",))}
    r = m.sequencia_no_record() or {}
    if r.get("mob_id") != seqs[sys.argv[1]]:
        m.carregar_no_monitor([seqs[sys.argv[1]]], "Record"); time.sleep(1.5)
    r = m.sequencia_no_record(); assert r["mob_id"] == seqs[sys.argv[1]], r; print("no Record:", sys.argv[1])
