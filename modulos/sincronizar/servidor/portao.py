"""O PORTÃO do servidor do Sincronizar — todas as trancas numa função pura, testável sem subir servidor.

Porte do `portao_com_fetch_site` do `httpserver.rs` do Órbita (`d57904e`), fase 1 do plano
`docs/plano/2026-11-06-um-app-so.md`. As quatro trancas, e por que cada uma existe (o porquê longo está no Rust e na
auditoria de 2026-08-23 do Órbita):

1. **Escuta só em 127.0.0.1** (no `servidor.py`).
2. **`Host` local, por IGUALDADE EXATA** — o prefixo de antes aceitava `localhost.evil.com:7817` (DNS-rebinding).
3. **Token (`X-Sincronizar-Token`; era `X-Sincronizar-Token`)**: a checagem de `Host` não derrota uma página comum fazendo `fetch` para 127.0.0.1.
4. **Recusa de `Origin` http(s)** que não seja a nossa: o CEP vem de `file://`, o Resolve de curl, sem `Origin`.

Quem entra SEM token:
- a página que NÓS servimos: `Sec-Fetch-Site: same-origin` (o `GET` same-origin não manda `Origin` — medido no
  MC 25.12 em 2026-08-09) ou `Origin` igual à nossa (os POSTs dela);
- o painel `avpi://` do MC, só em `/health` e `/avid/painel` (`Origin` é forbidden header: site nenhum o apresenta);
- a PRIMEIRA carga da UI do MC e da página da ponte do Premiere (navegação de topo, sem `Origin`): só HTML.

⛔ Os conceitos "a origem é a nossa" e "veio da nossa página" ficam SEPARADOS: juntos, `Origin: https://site` +
`Sec-Fetch-Site: same-origin` passaria pela recusa de origem web — combinação que navegador não produz, processo sim.
"""
from __future__ import annotations

from typing import Callable, Optional

#: Teto do corpo: os reais são listas de caminhos (KB). Sem teto, um `Content-Length` de 8 GB derruba o processo.
MAX_BODY_BYTES = 8 * 1024 * 1024

#: A origem do painel `.avpi` do Media Composer — MEDIDA (2026-08-08, MC 25.12): literalmente `avpi://`.
ORIGEM_PAINEL_AVID = "avpi://"
#: As ÚNICAS rotas que o painel `avpi://` alcança sem o token (ele é QtWebEngine puro, sem disco para lê-lo).
ROTAS_DO_PAINEL_AVID = ("/health", "/avid/painel")
#: A página da Preparar (que é também o painel do MC) e a da ponte invisível do Premiere.
ROTA_UI_PAINEL_AVID = "/avid/panel"
ROTA_PONTE_PREMIERE = "/premiere/ponte"

#: (status, mensagem) de cada recusa — os textos são os do Rust: os clientes os conhecem.
HOST_NAO_LOCAL = (403, "host não-local")
ORIGEM_WEB = (403, "origem não permitida")
SEM_TOKEN = (401, "token ausente ou inválido")
CORPO_GRANDE = (413, "corpo grande demais")


def e_origem_propria(origem: str, porta: int) -> bool:
    o = origem.strip().rstrip("/").lower()
    return o in (f"http://127.0.0.1:{porta}", f"http://localhost:{porta}")


def _host_local(host: Optional[str], porta: int) -> bool:
    if host is None:
        return False
    v = host.strip().lower()
    return v in ("127.0.0.1", "localhost", "[::1]",
                 f"127.0.0.1:{porta}", f"localhost:{porta}", f"[::1]:{porta}")


def portao(host: Optional[str], origin: Optional[str], sec_fetch_site: Optional[str], token: Optional[str],
           body_len: Optional[int], rota: str, *, porta: int,
           token_confere: Callable[[str], bool]) -> Optional[tuple[int, str]]:
    """`None` = pode entrar; senão `(status, mensagem)`.

    A ordem não é arbitrária: o que não custa nem revela nada vem primeiro, e o token antes do tamanho do corpo
    (quem não se identificou não merece nem que se olhe o `Content-Length`)."""
    if not _host_local(host, porta):
        return HOST_NAO_LOCAL
    origem_e_nossa = origin is not None and e_origem_propria(origin, porta)
    same_origin = sec_fetch_site is not None and sec_fetch_site.strip().lower() == "same-origin"
    if origin is not None:
        o = origin.strip().lower()
        if (o.startswith("http://") or o.startswith("https://")) and not origem_e_nossa:
            return ORIGEM_WEB
    painel_avid = (origin is not None and origin.strip().lower() == ORIGEM_PAINEL_AVID
                   and rota in ROTAS_DO_PAINEL_AVID)
    carga_da_ui = rota in (ROTA_UI_PAINEL_AVID, ROTA_PONTE_PREMIERE) and origin is None
    if not (painel_avid or origem_e_nossa or same_origin or carga_da_ui or token_confere(token or "")):
        return SEM_TOKEN
    if body_len is not None and body_len > MAX_BODY_BYTES:
        return CORPO_GRANDE
    return None
