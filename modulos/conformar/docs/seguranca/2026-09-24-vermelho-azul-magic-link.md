# Revisão de segurança — time vermelho × time azul · Magic Link · 2026-09-24

Escopo: tudo o que o Magic Link acrescentou (ADR 0016/0017): envio pela pasta combinada, Carta
Aberta 1.1, receptor (`sessao_receber.py`, rotas `/receber/*`, token), script do Resolve,
coleta pelo teclado. Mais o portão do serviço, que o receptor passou a expor a um cliente novo.

**Atacante modelado**
- escreve na pasta combinada de rede;
- controla uma página web que o editor visita, incluindo o DNS dela;
- pode subir um programa na porta 7823 antes do serviço.

**Fora do escopo:** um processo rodando como o usuário. Ele já dirige o Media Composer sem
credencial (ADR 0007).

**Método:** cada ataque virou um teste que PROVA a falha antes da correção
(`tests/test_ataques_magic_link.py`). A correção só vale quando o mesmo teste passa. Resultado
final: **15/15 barrados**, suíte 27/27.

| # | ataque (vermelho) | antes | correção (azul) | onde |
|---|---|---|---|---|
| V1 | **DNS rebinding**: página em `127.0.0.1.atacante.com` resolve para 127.0.0.1; o GET para a própria origem vai com `Sec-Fetch-Site: same-origin` e sem `Origin` | ⛔ `/magic`, `/export`, `/receber/caixa` vazavam (o `Host` era testado com `startswith`). **Existia antes do Magic Link** | `Host` com nome EXATO `127.0.0.1`/`localhost` (`portao.host_local`) | `api/portao.py` |
| V2 | Carta com `Source Path` = `\\atacante\…` | ⛔⛔ o caminho ia para o `MediaFilePath` do DRT; ao importar, **o Resolve abriria sessão SMB com o atacante** e entregaria o hash NTLM do colorista | o `Source Path` da Carta só vale se for local e seguro (`caminho_confiavel`, sem `://`); senão a referência offline cai na pasta local | `sessao_receber._pasta_de_referencia` |
| V3 | `media_ref.local_path`/`url` UNC plantados nos segmentos | ⛔ passavam intactos para o motor | o reader zera caminho/URL de mídia (na leitura crua eles são sempre vazios) | `reader._sem_caminhos` |
| V4 | bomba de aninhamento `[[[…]]]` (400 KB) | ⛔ `RecursionError` derrubava a **caixa inteira** (nenhum envio aparecia) | `RecursionError` vira `CartaInvalida`; a caixa isola cada arquivo | `reader.ler_carta`, `SessaoReceber.caixa` |
| V5 | Carta pequena com 300 mil segmentos | ⛔ o writer do DRT rodaria minutos com o Resolve travado | teto de 100 mil segmentos / 50 mil masters (a timeline real mais longa: 1.192) | `reader.LIMITE_SEGMENTOS` |
| V6 | pasta inundada com 2.500 arquivos | ⛔ todo "Procurar novos" leria todos | só os 500 mais recentes, e a caixa diz `cortado` | `sessao_receber.MAX_ARQUIVOS` |
| V7 | temporário previsível `<envio>.parcial` plantado antes (pasta ou link) | ⛔ o envio quebrava, ou escreveria onde o link mandasse | `mkstemp` na mesma pasta: nome aleatório + `O_EXCL` | `writer.build_carta_aberta` |
| V8 | tipos errados no miolo dos segmentos | ⛔ 500 com rastro interno (`TypeError: …`) | vira "a carta tem dados inválidos" | `SessaoReceber.preparar` |
| V9 | **servidor impostor** na 7823 devolve `drt` = `\\atacante\x.drt` | ⛔ o script importaria (SMB para o atacante) | o script só importa `<dados>\recebidos\<uuid>.drt`; pasta do Media Pool só de uma lista fixa | `delapraca_receber.lua: drt_confiavel` → desde 2026-09-25, só na casca: `casca/main.js: drtConfiavel` (o script Lua saiu) |
| V10 | nome de sequência `<img src=…>` no rótulo | ⛔ o `Label` do Qt interpreta HTML sozinho | todo texto do serviço sai sem `<`/`>` | `delapraca_receber.lua: texto_plano` → o script Lua saiu em 2026-09-25 (o painel escapa todo texto: `escapar`) |

**Já barrados na primeira escrita** (o vermelho tentou, e o teste passou de primeira):
- UNC em `arquivo_ama`/`gerenciadas` (tranca `caminho_confiavel` antes do disco);
- token errado ou ausente;
- token numa rota do painel;
- página web com o token certo;
- `id` com `../`;
- tecla com outra janela na frente;
- nome de sequência com `..\` no nome do arquivo de envio.

## Riscos que ficam (aceitos, com motivo)

- **Autenticidade do remetente.** Quem escreve na pasta combinada pode mandar uma Carta dizendo
  ser de `EDIT-02`: o remetente é declarado, não provado. O dano é limitado pelas trancas acima,
  porque a Carta não faz a máquina do Resolve tocar a rede nem escrever fora de `recebidos/`, mas
  ela pode empurrar uma timeline falsa. Remédio: **assinatura** com chave da produção (ver a
  resposta sobre gzip, abaixo). `pendente`.
- **O impostor na porta 7823 recebe o token** que o script manda. O token só vale para o nosso
  serviço, e o V9 impede o impostor de fazer o Resolve importar algo de fora. Mas ele pode
  mostrar uma lista falsa na janela. Remédio completo: o serviço provar que conhece o token
  (desafio/resposta) antes de o script acreditar. `pendente`.
- **Confidencialidade.** A Carta viaja em claro: nomes de arquivo, de câmera e o comentário.
  Numa pasta de rede da produção isso é o normal (o AAF e o DRT viajam do mesmo jeito).

## Lições que valem para a família (registradas no banco)

1. `Host.startswith("127.0.0.1")` **não** defende de DNS rebinding: é igualdade exata do nome.
2. **Um caminho escrito num arquivo de projeto é uma ordem de acesso à rede** para o NLE que o
   abrir: o DRT com `MediaFilePath` UNC leva o Resolve ao host. Vale para AAF, XML e PRPROJ.
3. O `print` do Lua do Resolve não separa argumentos com TAB (medido no `fuscript.exe`).
