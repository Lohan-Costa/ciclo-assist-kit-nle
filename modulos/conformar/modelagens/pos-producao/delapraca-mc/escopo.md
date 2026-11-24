# Escopo — De Lá Pra Cá (plugin do Media Composer)

Modelagem STRIDE do plugin de relink. Guia de Desenvolvimento Seguro, §14.

**Última revisão:** 2026-08-16 · **Próxima:** até 2027-02-16 (janela de 3–6 meses)

## O que é

Plugin que roda **dentro** do Avid Media Composer, na estação do editor. Um painel
(`.avpi`, webview QtWebEngine) conversa com um **serviço Python local**, que por sua vez
dirige o Media Composer por **gRPC em loopback** e lê arquivos de mídia do acervo.

## Fronteiras de confiança

```
  editor  →  painel (webview, origem avpi:// ou http://127.0.0.1:7823)
                │  HTTP em loopback
                ▼
           serviço Python  ──gRPC──►  Media Composer ([::1]:9100)
                │
                ├──►  acervo de mídia (SSD externo / share SMB)   ← ENTRADA DE TERCEIRO
                ├──►  banco de mídias compartilhado (share SMB)   ← ENTRADA DE TERCEIRO
                └──►  ffprobe / MediaInfo / ffmpeg (subprocessos)
```

⭐ **As duas fronteiras que mais importam não são a rede, são o DISCO:**

1. **Nome e caminho de arquivo de mídia.** O acervo vive em storage compartilhado de
   produção — quem nomeia um arquivo não é quem executa o plugin.
2. **O banco de mídias.** É gravado por várias máquinas e lido por todas; um fragmento é
   entrada não confiável, mesmo vindo "de dentro de casa".

## Ativos

| ativo | por que importa |
|---|---|
| O trabalho do editor (timeline, bins do projeto) | dias de montagem; corromper uma bin custa mais que qualquer dado nosso |
| A estação do editor | acesso ao acervo inteiro da produção e à rede interna |
| O acervo de mídia | material bruto não publicado, sob embargo comercial |
| O banco de mídias | não tem segredo, mas envenená-lo direciona relinks de toda a equipe |

## Fora de escopo

- Autenticação de usuário (OIDC/ID da emissora): **não há usuários**. O serviço atende um
  processo local, na sessão do próprio editor, sem contas nem sessões.
- HTTPS/TLS: o transporte é `127.0.0.1`; não há salto de rede a proteger. Um certificado
  para loopback traria gestão de chave sem ganhar superfície coberta.
- LGPD: o plugin não trata dado pessoal. Caminhos de arquivo contêm o nome de usuário do
  sistema (`C:\Users\<nome>`) e ficam só em log local.
- Rate limiting: não há endpoint público; o portão por origem é a defesa (ADR 0007).

## Decisões de segurança já tomadas

| onde | decisão |
|---|---|
| ADR 0007 | O portão não usa token em arquivo: a defesa é `Origin` + `Sec-Fetch-Site`, que são *forbidden headers* e nenhuma página consegue forjar |
| `media/safepath.py` | `ensure_local_file` + `ff_input` — todo caminho vindo de fora passa por ali antes de virar argumento de ffmpeg/MediaInfo |
| `api/servidor.py` | `nosniff`, `X-Frame-Options: deny`, CSP restritiva, `Cache-Control: no-store` |
| `ui/painel.js` | `escapar()` cobre `&<>` **e aspas** — o painel monta atributos com nome de arquivo |
| `publish.py` | Allowlist (não denylist) + `gitleaks` como gate obrigatório no CI |
| `requirements.lock` | Versões exatas; `requirements.txt` fica como a lista legível |
