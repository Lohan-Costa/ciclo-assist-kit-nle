"""O portão — todas as trancas do servidor local num lugar só, como função pura.

Portado do Órbita (`DRAMASYNC/src-tauri/src/httpserver.rs:265-345`), que o mediu dentro
do Media Composer 25.12. A lógica é a mesma; o que muda é uma tranca a menos, e vale
dizer por quê.

## Por que aqui NÃO existe token de arquivo

No Órbita o servidor é do app e os painéis são clientes externos: dois dos três leem o
token de um arquivo em disco (o CEP tem `fs` do Node, o Resolve tem `io.open`). Aqui o
servidor é **do próprio plugin** — não há app externo, não há segundo cliente legítimo, e
o painel do Avid continua sendo QtWebEngine puro, **sem acesso a disco**. Um token
protegeria o serviço de si mesmo.

O que resta é a assimetria que de fato funciona, e ela é suficiente contra o atacante que
importa aqui — uma **página web** que faça `fetch` para `127.0.0.1`:

* `Origin` e `Sec-Fetch-Site` são *forbidden headers*: nenhuma página consegue defini-los.
* Só o painel dentro do MC apresenta `Origin: avpi://`.
* Só uma página **servida por este servidor** chega com `Sec-Fetch-Site: same-origin`;
  um site externo chega com `cross-site`.

⚠️ **O que isto NÃO resolve, e não pretende:** um processo local rodando como o usuário
forja qualquer header. Contra ele nada aqui protege — e nada poderia, porque esse mesmo
processo já dirige o Media Composer inteiro pelo `[::1]:9100`, que não pede credencial
nenhuma. Isso é propriedade do produto da Avid, não escolha nossa. A tranca existe contra
o navegador, que é quem ela realmente barra.

## Emenda (ADR 0016, 2026-09-24): o token existe para quem LÊ disco — o script do Resolve

O Magic Link trouxe um segundo cliente legítimo: o script do Resolve (`plugins/resolve/`), que
fala com este serviço por `curl`, **sem `Origin`** e sem `Sec-Fetch-Site`. Ele lê disco
(`io.open`), então pode provar quem é como no Órbita: um token de 256 bits gerado a cada
início do serviço em `pasta_dados()/token` (`token_local.py`), mandado no cabeçalho
`X-DeLaPraCa-Token` e comparado em tempo constante. ⚠️ Vale **só** nas rotas `/receber/*`
(`ROTAS_DO_SCRIPT`): o token não abre nada do painel do Avid, e uma página web continua
barrada antes (ela manda `Origin` web, e não lê o arquivo). O painel do Avid segue sem token —
ele não lê disco.

## Por que a UI servida não carrega segredo embutido

A primeira carga da UI é uma **navegação de topo** (`window.location` no loader), e
navegação `GET` **não manda `Origin`** — não há como exigir credencial nela sem impedir o
painel de abrir. Por isso o que sai de `/painel` é só HTML e CSS: nenhum dado de projeto,
nenhum caminho de arquivo, **nenhum token**. A UI se autentica pela origem, não por
segredo embutido.
"""

from __future__ import annotations

import hmac

PORTA = 7823

# O prefixo das rotas do receptor (o script do Resolve). É o ÚNICO lugar onde o token vale.
ROTAS_DO_SCRIPT = "/receber/"
CABECALHO_TOKEN = "X-DeLaPraCa-Token"

# A origem do painel `.avpi`. MEDIDA, não suposta: o painel roda em QtWebEngine e manda
# literalmente `Origin: avpi://` — não é `null` nem ausente (medição de 2026-08-08 no
# banco de NLEs, `plugins/avid-panel-sdk/dados/runtime.json` → `rede_do_painel`).
ORIGEM_PAINEL = "avpi://"

# ⭐ As ÚNICAS rotas que o loader dentro do `.avpi` alcança apresentando só a origem.
# A lista é curta de propósito: o loader precisa saber se o serviço está vivo, e nada
# mais. Tudo que lê disco, varre pasta de rede ou dirige o Media Composer exige que a
# requisição venha da UI servida (`Sec-Fetch-Site: same-origin`).
ROTAS_DO_LOADER = frozenset({"/health"})

# A rota que SERVE a interface. (A página da ponte própria do Premiere, `/premiere/ponte`, saiu na fase 4 do plano um
# app só, 2026-11-07: a ponte é a ÚNICA, do Ciclo Assist.)
ROTA_UI = "/painel"
ROTAS_DE_PAGINA = frozenset({ROTA_UI})

# Teto do corpo. Nada que o painel manda chega perto disso; serve para que um corpo
# absurdo seja recusado antes de ser lido.
MAX_CORPO_BYTES = 1 << 20  # 1 MiB


class Recusa:
    HOST_NAO_LOCAL = ("host não-local", 403)
    ORIGEM_WEB = ("origem não permitida", 403)
    SEM_CREDENCIAL = ("credencial ausente", 401)
    CORPO_GRANDE = ("corpo grande demais", 413)


def host_local(host: str | None) -> bool:
    """O `Host` é EXATAMENTE `127.0.0.1` ou `localhost` (com ou sem porta)?

    ⛔ CORRIGE (2026-09-24, revisão vermelho × azul, ataque V1): a versão anterior testava
    `startswith("127.0.0.1")` — e `127.0.0.1.atacante.com` começa assim. Com DNS rebinding a
    página do atacante resolve para 127.0.0.1; num GET para a própria origem o navegador manda
    `Sec-Fetch-Site: same-origin` SEM `Origin`, e o portão a tomava pela UI servida: `/magic`,
    `/export` e `/receber/caixa` vazavam. A defesa contra rebinding é a igualdade EXATA do nome
    (como no Órbita, `httpserver.rs`).
    """
    h = (host or "").strip().lower()
    nome, _, porta = h.rpartition(":")
    if not nome or not porta.isdigit():
        nome = h
    return nome in ("127.0.0.1", "localhost")


def _e_origem_propria(origem: str, porta: int = PORTA) -> bool:
    """A origem que a UI apresenta depois de carregada — que é a do próprio servidor.

    Um site nunca consegue apresentar esta origem: `Origin` é *forbidden header*, e a
    única página que o navegador rotula com `http://127.0.0.1:7823` é uma página servida
    por nós.

    ⛔ CORRIGE (2026-10-28, ficha B033 conferida ao vivo): comparava com a constante `PORTA`; com o serviço em
    outra porta (`--porta 7899`) o PRÓPRIO painel era recusado (403 "origem não permitida"). Vale a porta REAL do
    socket, que o servidor passa.
    """
    o = origem.strip().rstrip("/").lower()
    return o in (f"http://127.0.0.1:{porta}", f"http://localhost:{porta}")


def portao(
    host: str | None,
    origin: str | None,
    sec_fetch_site: str | None,
    corpo_len: int | None,
    rota: str,
    token: str | None = None,
    token_esperado: str | None = None,
    porta: int = PORTA,
) -> tuple[str, int] | None:
    """`None` = a requisição pode entrar. Caso contrário, o motivo e o status.

    A ordem das checagens não é arbitrária: as que não custam nada e não revelam nada
    vêm primeiro.
    """
    if not host_local(host):
        return Recusa.HOST_NAO_LOCAL

    origem_e_nossa = bool(origin) and _e_origem_propria(origin, porta)

    # ⭐ É o `Sec-Fetch-Site`, e NÃO o `Origin`, que identifica os GET da UI servida.
    #
    # A primeira versão do Órbita apostou no `Origin` e estava errada: uma requisição
    # `GET` same-origin **não manda `Origin`** — o navegador só o envia em CORS e em
    # POST. Na prática o painel carregava e todo GET voltava 401, com os POSTs
    # funcionando: sintoma que manda depurar o lugar errado. Medido dentro do MC 25.12
    # em 2026-08-09.
    same_origin = (sec_fetch_site or "").strip().lower() == "same-origin"

    # Um `fetch` de site SEMPRE carrega `Origin: http(s)://…`. Então uma origem com
    # esquema web é, por construção, um cliente que não deveria estar aqui — com a única
    # exceção de sermos nós mesmos.
    if origin:
        o = origin.strip().lower()
        if o.startswith(("http://", "https://")) and not origem_e_nossa:
            return Recusa.ORIGEM_WEB

    # O loader se identifica pela origem `avpi://`, e só nas rotas da lista curta.
    loader = bool(origin) and origin.strip().lower() == ORIGEM_PAINEL and rota in ROTAS_DO_LOADER

    # A primeira carga da UI é navegação de topo e não manda `Origin` (ver docstring).
    # O que sai daqui é HTML e CSS, sem dado de projeto e sem segredo.
    carga_da_ui = rota in ROTAS_DE_PAGINA and origin is None

    # O script do Resolve: sem origem nenhuma, com o token do arquivo, só em /receber/*.
    # `compare_digest` e não `==`: o tempo da comparação não pode contar quantos caracteres
    # acertaram.
    script = (origin is None and rota.startswith(ROTAS_DO_SCRIPT) and bool(token)
              and bool(token_esperado)
              and hmac.compare_digest(token.strip().encode(), token_esperado.encode()))

    if not (loader or same_origin or origem_e_nossa or carga_da_ui or script):
        return Recusa.SEM_CREDENCIAL

    if corpo_len is not None and corpo_len > MAX_CORPO_BYTES:
        return Recusa.CORPO_GRANDE

    return None
