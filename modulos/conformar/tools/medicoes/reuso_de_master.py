"""Etapa 3 do handoff: a timeline vem online numa bin NOVA que só COPIA os masters já linkados (mesmo MobID)?"""
import os, sys, time, random
sys.path[:0] = [r"motor", r"plugins\media-composer\servico"]
from avb_export.reader import topen
from avb.mobid import MobID
from avb_bin.segmentos import escolher_sequencia
from avid.mcapi import MediaComposer
from avid.acoes import Acoes
from sessao_export import mob_id_da_api
P = r"%USERPROFILE%\Documents\Avid Projects\DLPC LAB\DLPC LINK LIMPO 2"
origem = os.path.join(P, "DLPC LINK LIMPO 2 1", "DLPC LINK LIMPO 2 1_SEQ.avb")
destino_dir = os.path.join(P, "REUSO_TESTE"); os.makedirs(destino_dir, exist_ok=True)
destino = os.path.join(destino_dir, "REUSO_SEQ.avb")
with MediaComposer() as m:
    Acoes(m).salvar(); time.sleep(3)
with topen(origem) as f:
    seq = escolher_sequencia(f)
    seq.mob_id = MobID.new(); nova = str(seq.mob_id)
    f.content.uid = random.getrandbits(63)
    f.write(destino)
print("sequencia nova", nova)
with MediaComposer() as m:
    m.abrir_bin(destino); time.sleep(3)
    m.carregar_no_monitor([mob_id_da_api(nova)], "Record")
print("ok")
