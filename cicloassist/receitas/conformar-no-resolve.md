---
name: conformar-no-resolve
titulo: Conformar {sequencia} no DaVinci Resolve
description: Leva uma timeline (.prproj, .aaf, .avb, .drt…) para o DaVinci Resolve Studio pelo De Lá Pra Cá e confere contra o vídeo de referência.
parametros: {"timeline": {"tipo": "arquivo", "rotulo": "O arquivo da timeline", "extensoes": ["prproj", "aaf", "avb", "drt", "xml", "fcpxml", "otio", "edl", "json"]}, "sequencia": {"tipo": "timeline", "de": "timeline", "rotulo": "A timeline a conformar"}, "referencia": {"tipo": "arquivo", "rotulo": "Vídeo de referência", "extensoes": ["mov", "mp4", "mxf"], "opcional": true}, "pastas": {"tipo": "pasta", "rotulo": "Pastas das mídias (se o projeto não as achar sozinho)", "multiplos": true, "opcional": true}}
---

## Passos

```json
[
  {"id": "abrir_resolve", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "{timeline_nome}"}},
  {"id": "conform", "op": "conformar_no_resolve", "args": {"projeto": "{timeline}", "sequencia": "{sequencia}", "referencia": "{referencia}", "pastas": "{pastas}"}}
]
```

## Quando as condições mudam

- Mídia faltando no conform: diga quantas e de que pasta; proponha tentar de novo com `pastas` apontando a
  pasta das mídias, se o editor a escolher.
- A conferência contra a referência reprova pontos: não refaça o conform; mostre os pontos ao editor.
- O Resolve aberto é a versão gratuita: recuse com a frase do abrir_programa (só Studio).
- "O servidor de scripts do Resolve não está no ar" logo depois de abri-lo: tente de novo o passo conform uma vez.
