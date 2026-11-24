# ADR 0007 — O `.avpi` carrega só um loader; a interface vem do serviço

**Data:** 2026-09-10 · **Estado:** aceito

## Contexto

O `url` do `uiItem` no manifesto do painel aceita duas coisas: um caminho **relativo**,
servido pelo esquema `avpi://` de dentro do pacote, ou um **HTTP absoluto para
localhost**. Os dois parceiros oficiais da Avid fazem escolhas opostas — o Quickture
serve do pacote, o Jumper serve do backend local (`http://127.0.0.1:6699/...`, com um
`.avpi` de apenas dois arquivos).

## Decisão

**As duas coisas, em ordem:** o `.avpi` carrega um `loader.html` mínimo, e o loader
navega para a interface de verdade, servida pelo serviço em `http://127.0.0.1:7824`.

## Por quê

Servir a UI do serviço torna painel e API **same-origin**, e isso não é conforto — é a
diferença entre três problemas e nenhum:

- sem CORS, sem preflight, sem header bloqueado
- sem segredo de pareamento dentro do `.avpi` (que seria legível por qualquer processo:
  a pasta de plugins é `rwxrwxrwx`)
- **a UI atualiza sem reinstalar o painel** — o `.avpi` fica em uma versão e praticamente
  não muda

O preço do modelo puro do Jumper é que **com o serviço fora do ar o painel não abre, e
não há UI para explicar por quê**. O loader é a resposta: ele mora no pacote, então
sempre abre, procura o serviço e diz o que está acontecendo enquanto não acha.

## O que isto obriga

- `allowedDomains` do manifesto precisa listar `127.0.0.1:7824` e `localhost:7824`.
- A autenticação do painel muda de cabeçalho — ver ADR 0005, defesa 4. **É consequência
  direta desta decisão**, e a confusão que ela evita já foi medida.
- O loader não pode depender de arquivo: o painel **não lê disco**.

## Dois fatos medidos que valem ouro no dia a dia

⭐ **Não há diálogo de consentimento de localhost.** A navegação de topo de `avpi://`
para `http://127.0.0.1:<porta>` passa direto; o `allowedDomains` basta. Era o risco
capaz de derrubar este desenho, e não se materializou (banco, 2026-08-09, MC 25.12).

⭐ **Botão direito numa área vazia do painel → Reload.** Fechar e reabrir o painel pelo
menu Tools **não** recarrega a página: ela fica em cache. O Reload recarrega sem
reiniciar o Media Composer.

Isso muda o ciclo de desenvolvimento inteiro: editar o HTML servido → botão direito →
Reload. Antes da descoberta, cada iteração custava fechar o Media Composer.
