---
name: preparar-diaria-no-premiere
titulo: Preparar a diária {diaria} no Premiere
description: Gera proxies ProRes Proxy 1080 da diária no DaVinci Resolve Studio, leva a diária ao Premiere (o proxy como mídia original, ou a alta com o proxy anexado) e sincroniza câmeras e som pelo Sincronizar.
parametros: {"pasta": {"tipo": "pasta", "rotulo": "A pasta da diária (vídeos e WAV)"}, "diaria": {"tipo": "texto", "rotulo": "Nome da diária", "padrao": "D01"}, "destino": {"tipo": "pasta", "rotulo": "Onde gravar os proxies"}, "modo": {"tipo": "escolha", "rotulo": "Como a mídia entra no Premiere", "opcoes": ["proxy_anexado", "original"]}, "projeto": {"tipo": "arquivo", "rotulo": "O projeto do Premiere (.prproj; abre, ou cria)"}}
---

## Passos

```json
[
  {"id": "abrir_resolve", "op": "abrir_programa", "args": {"programa": "resolve", "projeto": "{diaria}"}},
  {"id": "conv", "op": "converter_para_proxy", "args": {"projeto": "{diaria}", "pasta": "{pasta}", "destino": "{destino}"}},
  {"id": "fechar_resolve", "op": "fechar_programa", "args": {"programa": "resolve"}},
  {"id": "abrir_premiere", "op": "abrir_programa", "args": {"programa": "premiere", "projeto": "{projeto}"}},
  {"id": "importar", "op": "importar_no_premiere", "args": {"modo": "{modo}", "diaria": "{pasta}", "proxies": "{conv.pasta}", "bin": "{diaria}"}},
  {"id": "sync", "op": "sincronizar", "args": {"fontes": [{"tipo": "camera", "nome": "CAM A", "bins": ["{diaria}"]}, {"tipo": "som", "nome": "SOM DIRETO", "bins": ["{diaria}"]}], "nome": "{diaria}"}}
]
```

## Quando as condições mudam

- ⛔ O modo (proxy como ORIGINAL, ou a ALTA com o proxy anexado) e a pasta dos proxies são do editor, a cada
  diária (decisão do autor, 2026-11-07). Faltando um dos dois, pergunte — nunca escolha.
- Algum proxy não conferiu (o converter devolve `problemas`; o importar, `sem_proxy`): no modo anexado aquela
  alta entra SEM proxy, e é isso que se diz ao editor, clipe a clipe. Proxy errado anexado é pior que nenhum: o
  Premiere aceita calado outra duração e outro TC.
- Os vídeos misturam taxas: o converter recusa. Proponha separar a diária por taxa (uma rodada por taxa).
- O Resolve não fecha (render em curso, diálogo): não force; diga ao editor o que está na tela.
- O Sincronizar não está ligado ao Premiere (a aba Preparar é quem monta, pela ponte do Sincronizar): o sync recusa antes de
  começar. Peça ao editor para abrir a aba Preparar uma vez e conferir o Premiere conectado nela; sem a ponte, ela se
  instala na ⚙ da Preparar (e o Premiere reabre). Tente o passo de novo.
- O editor pediu os MERGED clips (um por câmera de cada take, em bins por cena): depois do fluxo, `criar_merged`
  com `fontes` = as mesmas do passo sync e, no modo anexado, `proxies` = a pasta que o converter devolveu (cada merged leva o proxy
  conferido da sua câmera). Ele sincroniza de novo (o Sincronizar guarda o sync só 2 min) e o painel do Sincronizar importa
  em `CENAS/<cena>`; se o projeto já tinha uma bin `CENAS`, eles entram nela — diga isso ao editor.
