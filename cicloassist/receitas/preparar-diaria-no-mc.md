---
name: preparar-diaria-no-mc
titulo: Preparar a diária {diaria} no Media Composer
description: Converte os vídeos de uma pasta em OP-Atom no DaVinci Resolve Studio, leva câmera e som direto ao Media Composer, sincroniza pelo Sincronizar e salva.
parametros: {"pasta": {"tipo": "pasta", "rotulo": "A pasta da diária (vídeos e WAV)"}, "diaria": {"tipo": "texto", "rotulo": "Nome da diária", "padrao": "D01"}, "projeto": {"tipo": "texto", "rotulo": "Projeto do Media Composer (abre, ou cria)"}, "formato": {"tipo": "escolha", "rotulo": "Formato do projeto, se for criado", "opcoes": ["1080p/25", "1080p/23.976", "1080p/24", "1080p/29.97", "1080i/50", "1080i/59.94", "720p/50", "720p/59.94"], "padrao": "1080p/25"}, "subclipes": {"tipo": "escolha", "rotulo": "Subclipes", "opcoes": ["nao", "uma_bin", "por_cena"], "padrao": "por_cena"}}
---

## Passos

```json
[
  {"id": "abrir_resolve", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "{diaria}"}},
  {"id": "conv", "op": "converter_para_opatom", "args": {"projeto": "{diaria}", "pasta": "{pasta}"}},
  {"id": "fechar_resolve", "op": "fechar_programa", "args": {"programa": "resolve"}},
  {"id": "abrir_mc", "op": "abrir_programa", "args": {"programa": "media_composer", "projeto": "{projeto}", "formato": "{formato}"}},
  {"id": "camera", "op": "importar_masters_opatom", "args": {"pasta": "{conv.pasta}", "bin": "{diaria} CAMERA"}},
  {"id": "som", "op": "som_direto_gerenciado", "args": {"pasta": "{pasta}", "bin": "{diaria} SOM"}},
  {"id": "sync", "op": "sincronizar", "args": {"fontes": [{"tipo": "camera", "nome": "CAM A", "bins": ["{diaria} CAMERA"]}, {"tipo": "som", "nome": "SOM DIRETO", "bins": ["{diaria} SOM"]}], "nome": "{diaria}", "subclipes": "{subclipes}"}},
  {"id": "salvar", "op": "salvar_tudo", "args": {}}
]
```

## Quando as condições mudam

- A pasta já é OP-Atom (MXF numa `Avid MediaFiles`): os passos conv e fechar_resolve sobram; proponha
  pular os dois e importar a pasta MXF direto.
- A pasta não tem WAV: o som direto falha; pular o passo som e sincronizar só se houver som nos vídeos — senão,
  pergunte ao editor se o sync deve ser pulado.
- O Resolve não fecha (render em curso, diálogo): não force; diga ao editor o que está na tela.
- O sync recusa as bins: confira os nomes que o passo camera e o passo som devolveram e corrija as `fontes`.
- Som sem cena/take no metadado e subclipes por cena: os takes sem cena vão para a bin à parte que o Sincronizar
  faz; diga quantos, nunca adivinhe a cena.
