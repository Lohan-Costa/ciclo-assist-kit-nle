# 0020 — No Resolve, o relink aos originais acontece AO IMPORTAR

**Status:** decidido com o usuário (2026-09-26) · implementado (Windows) e conferido pelo autor
no Resolve 19 com um DRT gerado pelo mesmo caminho do Importar; falta o Importar pelo painel ·
Data: 2026-09-26
**Relaciona-se com** o [ADR 0016](0016-magic-link-pasta-combinada.md), o
[ADR 0018](0018-magic-link-em-canais-por-setor.md) e o relink do Avid (`relink.py`,
[ADR 0013](0013-a-rota-avb-volta-a-existir.md)).
Organograma aprovado: https://claude.ai/artifact/4iV1Yrv1BVusJAfDq1QnP8

---

## Contexto

A timeline que a edição manda chega ao Resolve apontando para a mídia da EDIÇÃO: a
gerenciada do Avid (DNx) ou referências offline ao original, com reel e TC. A cor precisa
trabalhar sobre os **originais em alta**, que estão nas pastas dela. Até aqui, o colorista
religava à mão.

## Decisão

1. **O relink acontece ao importar** (decisão do autor). No Importar do Resolve (uma linha do
   Magic Link, uma Carta solta ou uma bin), o colorista pode apontar as pastas dos originais.
   O serviço casa cada master com o arquivo em alta, e o DRT **já nasce apontando para os
   originais**. Não depende da API de relink do Resolve, que o banco dá como "não mapeada".
   Relinkar uma timeline que já está no Resolve (o "do Resolve") fica para depois.
2. **O motor é o do relink do Avid.** Só o leitor muda. `relink.preparar` ganha a rota
   `carta`, que lê os masters com `sessao_receber.masters_da_carta`. A varredura
   (`indexer.index_folder`), a cascata do `matcher_masters` e a revisão (o mesmo resumo e a
   mesma janela larga) são as mesmas.
   - O nome procurado é o do **arquivo original** (`Source File`, a coluna do Avid) e, sem ele,
     o nome do master.
   - O AMA da Carta que existe nesta máquina vira o degrau "caminho".
3. **O original decidido vence a gerenciada.** `montar_midia(…, preferir=)` põe o original na
   frente de tudo, porque a cor quer a alta. O som do original lê o canal que o Avid usava
   (`canal_arquivo` intacto; a gerenciada é MXF mono, lida no canal 1). Sem `preferir`, a ordem
   de sempre (`test_carta_ida_e_volta`).
4. **A trava é a origem, não o caminho.** Os originais vêm do índice das pastas que o
   colorista escolheu. Por isso a trava não é `caminho_confiavel`, que recusa `\\servidor\…`,
   e originais em NAS são o caso comum. A regra é `originais_validos`: um original só entra se
   estiver DENTRO das pastas escolhidas e existir. O Importar confere que as decisões são
   daquela timeline (`Trabalho.pedido`).
5. **Na dúvida, não chuta** (a regra do matcher): dois arquivos igualmente plausíveis vão para
   a revisão. No Resolve importar sempre pode: o que não casou entra como hoje (mídia do Avid
   ou offline).
6. A lista de pastas vive só enquanto o painel está aberto, como no Avid (decisão de
   16/08). O banco de mídia no Resolve fica para depois.

## Consequências

- **Ajuste no matcher:** dois masters com o MESMO nome procurado deixam de disputar o arquivo
  (`_suprimir_duplicatas`). No Avid há vários masters de um mesmo original (o `Source File`
  igual), e a supressão deixava o segundo offline. A disputa entre nomes DIFERENTES (CAM B ×
  CAM A) continua.
- **Janela larga no Resolve:** é aberta pela casca (`dlpc:revisao`), porque o aplicativo que a
  abre no Avid não existe lá.
- **O item do pool declara o formato do original** (conferência de 2026-09-26). Na 1ª ida ao
  Resolve os clipes entraram Media Offline: todo item era clonado da forma MXF do esqueleto, e
  o Resolve decodifica pelo formato declarado ("of type MXF OP-Atom"). O writer passou a gerar
  o item de mp4/mov da forma NATIVA do Resolve 19 (`motor/drp/formas_r19.xml`), com o codec, a
  resolução e o áudio do arquivo, e a corrigir o formato do WAV/AIF. Conferido pelo autor: a
  PRODA_CORTE abriu nos originais com imagem e som. Banco: `drt-drp/estruturas.md` §"O item do
  pool declara o FORMATO".
- **Testes:** `tests/test_relink_carta.py` e `tests/test_drt_formato.py`.
