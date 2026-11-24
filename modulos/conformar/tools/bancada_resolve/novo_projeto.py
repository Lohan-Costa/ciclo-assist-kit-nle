"""Cria (ou abre) um projeto vazio no Resolve com a taxa pedida, ANTES de qualquer mídia. Uso: py novo_projeto.py <nome> [taxa]"""
import sys
import bancada_resolve_base as b

nome, taxa = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "23.976")
r = b._b.conectar()
pm = r.GetProjectManager()
atual = pm.GetCurrentProject()
print("versão:", r.GetVersionString(), "| aberto:", atual.GetName() if atual else None)
p = pm.CreateProject(nome) or pm.LoadProject(nome)
print("projeto:", p.GetName() if p else None)
print("taxa:", p.SetSetting("timelineFrameRate", taxa), p.GetSetting("timelineFrameRate"),
      "| playback:", p.SetSetting("timelinePlaybackFrameRate", taxa), p.GetSetting("timelinePlaybackFrameRate"))
print("resolução:", p.GetSetting("timelineResolutionWidth"), "x", p.GetSetting("timelineResolutionHeight"))
