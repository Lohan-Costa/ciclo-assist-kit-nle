"""PRPROJ — leitura de projeto do Adobe Premiere Pro (gzip de XML, grafo plano de objetos).

Produz os MESMOS segmentos que `aaf/parser.py::Segment.to_dict()` produz, para que o resto do
motor (Carta Aberta, `drp/writer.py`) trate uma timeline do Premiere como trata uma do Avid.
Banco: `protocolos/prproj/` (estruturas, relink-e-geometria §1, §2 e §10).
"""
