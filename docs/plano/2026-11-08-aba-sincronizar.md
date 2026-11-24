# Redesenho da aba Sincronizar (módulo Preparar)

Autor, 2026-11-08. **Executado no código em 2026-11-08 (ver o fim); falta conferir nos NLEs.** Organograma: https://claude.ai/artifact/2G3tJ9WrEWKaoATqKP5ySy

## O porquê

A separação automática em câmeras (herdada do Órbita isolado) falha sempre que o material foge do de teste. Quem diz o
que é câmera passa a ser: o EDITOR, pela caixa onde solta; ou o CICLO ASSIST, olhando caminhos e bins.

## O que o código mostrou (08/11)

- O palpite pelo nome (`servidor/fontes.py::classificar`, rota `/sources`) só atua no **Premiere**: no arrasto
  (`lerSelecaoPremiere`) e no chat (`mcp/ferramentas/sincronizar.py`, `_sinc.classificar`).
- No MC o arrasto já é uma fonte por arrasto (`adicionarFontes`). No chat do MC cada bin vira uma câmera: dois cartões em
  bins separadas viram duas câmeras.
- O motor de sync já recebe os grupos prontos e não muda. Ele já resolve sobreposição sozinho (`_resolve_source_overlaps`).
- A posição do soltar: `arrasto_win.rs` entrega `x, y` a `window.sincArrasto`. ⬜ Conferir no `arrasto_mac.rs`.
- No Premiere o arrasto não traz dados: a página lê a SELEÇÃO no soltar (`sincGetSelectionPorBin`).

## Decisões do autor

1. **Arrasto:** cada caixa é uma origem. Soltar num card existente soma a ele (cartão 2 da mesma câmera), sem repetir arquivo.
2. **Áudio solto misturado com vídeo** gera a pergunta "Detectamos vídeo e áudio separados. Trazer como duas origens?":
   **Sim** = origens separadas; **Não** = só o tipo aceito na caixa; **Cancelar** = nada entra. Vídeo com áudio embutido é
   câmera e não pergunta.
3. **Áudio solto** = `.wav`, `.aiff`, `.mp3`, `.aac` e, no MC (tudo `.mxf`), master só com trilhas de áudio.
4. **Tipo errado na caixa** (só áudio em Câmera, só vídeo em Som): recusa, com a frase que diz onde soltar.
5. **"Listar bins" sai.** O material entra arrastando os clipes de dentro da bin. A rota de ler bins fica (o chat usa).
   Trabalho SEPARADO: a última abordagem de interceptar o arrasto da bin pelo painel lateral (banco, `arrastar.md`); se der
   certo, a bin inteira vira uma origem, sem mudar este desenho.
6. **Receitas e lote: revisor de IA obrigatório** antes do sync de cada diária (turno magro, como `motor/conselho.py`).
   Incoerente: o fluxo para e pergunta. Sem IA disponível: o sync não roda, e o fluxo diz o motivo.
   ⭐ É um caso da regra geral do autor (2026-11-08): **todo fluxo autônomo tem um agente de revisão, um gerente, que se
   certifica de que o proposto foi entregue como esperado.** Opcional, altamente recomendado e LIGADO POR PADRÃO; sai só se o
   usuário pedir um fluxo sem supervisão. É a garantia de que a IA e os scripts tradicionais entreguem o melhor de cada um.
7. **Chat:** a ferramenta `sincronizar` ganha `fontes` explícitas (`[{tipo, nome, bins|arquivos}]`); `/api/v1/avid/sincronizar`
   aceita mais de uma bin por fonte. Na dúvida, o modelo pergunta.

## A interface

- Coluna centralizada na altura da janela: "Adicionar Câmera" e, abaixo, "Adicionar Som Direto", tracejados.
- Com material, a caixa vira card sólido com ícone (câmera/microfone). A próxima caixa de câmera nasce ACIMA; a de som, ABAIXO.
- **Card:** seta de abrir à ESQUERDA, ✕ à direita (longe, para evitar acidente). Aberto, mostra a tabela e dá para tirar itens.
- **Tabela** como a lista de mídias do De Lá Pra Cá: colunas redimensionáveis pela divisa, duplo clique no cabeçalho ordena,
  responsiva (rola de lado dentro do card). Câmera: nome, TC início, duração, FPS, resolução, codec, canais. Som: nome, TC
  início, duração, cena, plano, take, canais. Dados de `inspector.probe` (cacheado), preenchidos aos poucos, sem travar o
  arrasto. ⬜ **Plano** não é campo próprio hoje (só `scene`/`take`): ver o metadado do gravador; sem ele, "—", nunca chute.
- **Embaixo:** caixa do nome da sequência; configuração da timeline (dimensão e taxa), ativa no Premiere e (quando chegar) no
  Resolve, **desativada e cinza no MC** (herda do projeto); método. **Timeline, Taxa e Método são dropdowns.** Timeline:
  `1920×1080` · `3840×2160` · `Outro` (aparecem duas caixas sem texto, com um "x" entre elas: horizontal x vertical) ·
  `Baseado na mídia` (janela e fps do PRIMEIRO arquivo de vídeo informado; é a única opção que muda o valor da Taxa).
- **Alerta de TC, dentro de cada card.** Três conflitos: **TC sobreposto** (o início cai antes do fim do anterior; os dois
  lados); **mais de uma mídia com TC zerado** no mesmo card; **TC contínuo** (começa exatamente no quadro seguinte ao fim do
  anterior: costuma não servir, mas pode ser câmera que subdivide sessões longas, e aí está certo). A linha fica amarela, o card
  FECHADO mostra a soma ("2 em conflito") e, aberto, uma linha abaixo da lista explica o conflito. Só sinaliza, não bloqueia.
  Resolver fica para testes de laboratório (o Órbita já teve resoluções planejadas).
- **Som monofônico:** identificar e agrupar os `.wav` de um canal cada do mesmo take (mesmo TC e mesma duração), para cada canal
  ir à sua trilha em vez de um sobrescrever o outro. ⛔ Agrupar ANTES do alerta de TC: esses arquivos se sobrepõem por natureza,
  e não é conflito. Critério e comportamento atual do motor com eles: ⬜ a medir com material real (ou receita do laboratório).

## Ordem proposta

1. Tela de caixas e cards, com o arrasto caindo na caixa certa.
2. Tabela de metadados (redimensionar, ordenar, alerta de TC) e o agrupamento do som monofônico.
3. Nome da sequência e configuração da timeline.
4. Tirar o palpite pelo nome.
5. Chat com `fontes` explícitas.
6. Revisor de IA nas receitas.

Cada etapa testada no Windows; no fim, conferir no Mac (a posição do soltar).

## O que foi feito (2026-11-08, Windows)

1. **Caixas e cards** (`pagina/painel.html`): o soltar vai à caixa pela posição (`x, y` do `arrasto_win.rs`/`arrasto_mac.rs`). Saíram "Listar
   bins", as setas de ordem e o "Enviar".
2. **Tabela e alertas** (`servidor/fichas.py`, rotas `/midia/fichas` e `/midia/analise`, fora da trava do motor). **Som mono:** medido que o motor
   empurrava o 2º canal para depois do 1º; agora só o 1º entra no sync, e os outros voltam na posição dele, um por trilha
   (`separar_mono`/`devolver_mono`, `avid/adapter.py::trilhas_do_som_mono`, a pilha no `planoDoPremiere`).
3. **Timeline:** dropdowns, "Outro" e "Baseado na mídia" (o padrão: herda da 1ª mídia, como antes); cinza no MC; `sincAplicarFormato` no `host.jsx`.
4. **Palpite pelo nome fora:** saíram `/sources`, `servidor/fontes.py` e `sincronizar.classificar`.
5. **Chat:** `fontes` em `sincronizar` e `criar_merged` (no Premiere, obrigatório; a mesma bin pode servir à câmera e ao som, cada uma pega o
   seu tipo); `/api/v1/avid/sincronizar` aceita várias bins por fonte (`fundir_selecoes`). `bin` e `bins` continuam valendo no MC.
6. **Revisor:** `motor/revisor_do_sync.py`, chamado por `fluxo._revisar_antes_do_sync` em `sincronizar` e `criar_merged`; sem IA o passo falha e
   diz o motivo; `sem_supervisao` só a pedido. As duas receitas passaram a declarar `fontes`.
