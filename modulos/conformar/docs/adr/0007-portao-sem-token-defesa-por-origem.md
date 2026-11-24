# 0007 — O portão não usa token de arquivo; a defesa é `Origin`/`Sec-Fetch-Site`

**Status:** ativa · Data: 2026-08-10

**Contexto:** o serviço sobe um servidor HTTP local em `127.0.0.1:7823` para que o
painel (dentro do Media Composer) dirija o relink. O desenho de portão foi **portado do
Órbita** (`httpserver.rs`, ver ADR 0012 e 0015 do repositório irmão) — mas com uma
tranca a menos, de propósito: **não há token lido de um arquivo em disco.**

**Por que a assimetria é diferente aqui:** no Órbita o servidor é do **app**, e os
painéis de NLE são clientes **externos** — dois deles leem um token do disco
(`fs` do Node no CEP, `io.open` no Lua do Resolve) para provar que não são uma aba de
navegador qualquer. Aqui o servidor é **do próprio plugin**: não existe um segundo
cliente legítimo para distinguir, e o painel do Avid é QtWebEngine puro, sem acesso a
disco — um token protegeria o serviço de si mesmo.

**Decisão:** a defesa contra o ataque que importa (uma página web qualquer, aberta numa
aba, fazendo `fetch("http://127.0.0.1:7823/…")`) é a checagem de `Origin` e
`Sec-Fetch-Site` — os dois são *forbidden headers*: nenhuma página consegue defini-los
por conta própria, então uma origem externa nunca produz o par que o portão aceita.

**O que isto explicitamente não resolve, e não pretende resolver:** um processo local
rodando como o usuário forja qualquer header. Contra ele nada aqui protege — e nada
poderia, porque esse mesmo processo já dirige o Media Composer inteiro por
`[::1]:9100`, que não pede credencial nenhuma (propriedade do produto Avid, não escolha
deste projeto — ver a arquitetura, seção "O que sai da máquina").

**Provado:** `tests/test_portao.py` (22 casos — origem forjada, host externo, header
ausente, corpo acima do limite) e `tests/test_arquivos.py` (14 casos — nada sai de fora
de `ui/`).
