"""Utilitários que os writers precisam em runtime (não são scripts de linha de comando).

Só `inspect_drp` veio do RELINKER: `drp/writer.py` importa dele os codecs de blob
(fieldsblob/timemap/protobuf) do formato do Resolve. O resto de `tools/` no RELINKER
é bancada de estudo e ficou lá.
"""
