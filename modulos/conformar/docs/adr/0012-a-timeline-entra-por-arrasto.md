# ADR 0012 — A timeline entra por arrasto, e o seletor de sequences vira o plano B

**Data:** 2026-08-15
**Situação:** aceita — **implementado e exercitado por um editor no MC 25.6/Windows**
**Contexto:** o [ADR 0011](0011-uma-camada-de-plataforma-e-degradacao-por-versao.md) deixou
`/mc/sequences` caro no MC 25.6. Esta é a saída, e ela não veio da API.

---

## O problema

Para relinkar, o plugin precisa saber **qual timeline**. O caminho construído era:
enumerar as bins (`GetBins`), perguntar as sequences de cada uma
(`GetListOfBinItems`), e mostrar uma lista.

Isso custa **~500 ms por bin** — o piso de latência da API do Media Composer. Com
`GetListOfWindows` era possível perguntar só às bins abertas; **no MC 25.6 esse rpc não
existe**, então a rota degradada pergunta a **todas** as bins do projeto. Um projeto com
30 bins leva 15 s para abrir um seletor, e ainda perde a pré-seleção.

Havia um segundo limite, mais duro: **uma timeline em bin fechada não aparece de jeito
nenhum**, porque `GetListOfBinItems` numa bin fechada falha, e abri-la teria efeito
visível na tela do editor.

## O que se descobriu

Este banco de conhecimento registrava, como `confirmado`, que **não existe caminho
Media Composer → painel** para arrastar clipes, e que o substituto era o evento
`BinRowSelectionChanged`.

**Estava errado.** A dissecação do painel do **ESION Studio** (Acclaim Audio, `.avpi`
assinado pela Avid) mostrou o mecanismo: o Media Composer entrega o arrasto à webview
como um **MIME customizado**, lido por um `ondrop` de DOM comum.

```js
MCAPI_ASSET_LIST_MIME_TYPE = 'text/x.avid.mc-api-asset-list+json'
JSON.parse(dt.getData(MCAPI_ASSET_LIST_MIME_TYPE))
// → [{ id: <MobID>, type: "sequence"|"masterclip"|"subclip", in, out, … }]
```

⭐ **A conclusão errada era metodológica, não factual:** procurou-se `Drop*` nos
símbolos do binário do MC e só apareceram os três de saída. O pressuposto invisível era
*"se a capacidade existe, existe um símbolo para ela"*. **Metade da superfície de um
painel é a do navegador**, e essa metade não aparece em `strings` do executável.

---

## Decisão

**O arrasto passa a ser o caminho principal para dizer "é esta timeline".** O seletor de
sequences continua, como plano B e para quem prefere apontar numa lista.

O painel inteiro é o alvo (não uma caixinha): mirar um alvo pequeno segurando um clipe é
trabalho, e numa janela de 400 px uma zona dedicada roubaria espaço do que já está lá.

Uma rota nova, **`POST /mc/mob`**, converte o MobID no nome — que o payload do drop não
traz e de que precisamos para o arquivo do export e o nome da bin. É **uma** chamada
(~500 ms) num gesto deliberado, contra *N* chamadas para montar uma lista.

### O que isto ganha

| | seletor | arrasto |
|---|---|---|
| custo para escolher | ~500 ms × nº de bins | **zero** (o MobID vem no payload) |
| bin fechada | invisível | **funciona** |
| marcas de in/out | não existem | **vêm no payload** |
| pré-seleção no 25.6 | perdida | não faz falta |
| gesto | apontar numa lista | **arrastar, que é o gesto do editor** |

### Regras que a implementação segue

1. ⭐⭐ **O `dropEffect` tem de ser COMPATÍVEL com o `effectAllowed` da origem.** Medido:
   o Media Composer arrasta com **`effectAllowed = "move"`**, e forçar `"copy"`
   **cancela o drop silenciosamente**. O sintoma é cruel — o realce aparece (o
   `dragenter` viu o MIME) e soltar não faz nada. Foi este o defeito da primeira versão.
2. **Os listeners ficam na fase de CAPTURA.** `<select>` e `<input>` têm tratamento
   próprio de drop e podem consumir o evento antes do documento; na captura o alvo é a
   janela inteira de verdade.
3. **O `preventDefault` do `dragover` é incondicional.** Sem ele, soltar um arquivo faz
   a webview **navegar para o arquivo** e a UI desaparece. O filtro de MIME decide o
   realce, nunca se o navegador assume o controle.
4. ⭐ **Toda resposta ao arrasto é trazida para a vista.** A linha de status mora no
   rodapé da página, fora da área visível de uma janela de 500 px — e *"não aconteceu
   nada"* é indistinguível de *"a resposta apareceu onde você não olha"*. Metade do tempo
   perdido nesta implementação foi isso, não a plataforma.
5. **Só `type === "sequence"` é adotado.** Um masterclip solto recebe uma recusa que
   ensina, dizendo o que veio. Uma **bin** não é arrastável: o payload transporta *mob*.
6. **MobID se valida contando 64 hexadecimais, nunca casando os hifens** — o
   agrupamento muda conforme a superfície (`26-6-16-8-8` na API, `26-6-16-12-4` no
   payload do arrasto). Travado em `tests/test_nomes.py`.
7. **Colunas vazias no `GetMobInfo` = mob inexistente → 404.** O rpc não levanta nesse
   caso: devolve fluxo vazio. Um 200 ali faria o painel exportar coisa nenhuma, e o erro
   apareceria longe da causa. Medido contra o MC aberto.
8. ⭐ **A timeline arrastada não se anuncia como arrastada.** Sem ícone e sem sufixo: ela
   entra no seletor como qualquer outra. Para quem usa, escolher na lista e arrastar da
   bin são o mesmo ato — marcar a origem contaria um detalhe da nossa implementação que
   não muda nada para o editor. (Decisão do usuário, 2026-08-15.)
9. **E ela SOBREVIVE a um `carregarSequences()`.** Sem isso ela sumiria justamente no
   caso que o arrasto existe para resolver — timeline de bin fechada, que a lista não
   traz —, apagada pela reconexão automática que roda a cada 4 s.

---

## Consequências

**Ganhos** — escolher a timeline deixa de depender do rpc que falta no 25.6; bins
fechadas passam a servir; e o gesto fica igual ao dos painéis comerciais do ramo.

**Custos aceitos**

- **Uma capacidade que não controlamos.** Não há contrato público: o MIME e o formato do
  payload vieram de leitura de produto de terceiro. Podem mudar sem aviso — por isso o
  seletor **continua existindo**, e por isso a falha é falante.
- `in`/`out` são **recebidos e ignorados**: o relink usa a timeline inteira. Usá-los para
  relinkar um trecho é trabalho futuro, e agora há de onde tirar os valores.

**Verificado** (2026-08-15, MC 25.6/Windows, gesto de um editor): a sequence saiu da bin,
caiu no painel servido por **`http://`** — ou seja, **o MIME sobrevive à navegação para
fora do `avpi://`** — e o MobID chegou. O `/mc/mob` devolveu o nome, e o seletor ficou
com a timeline escolhida.

**O que fica em aberto**

- ✅ **`asset-list-extended+json` decifrado** (2026-08-15): é a **mesma lista na variante
  Interplay/PAM**, não metadado mais rico. `systemType` é `interplay-pam` nele e
  `mediacomposer` no nosso. Sai do pendente sem virar oportunidade.
- ✅ **`systemID`/`systemType` decifrados**: são o **sistema de origem**, não a bin. Foi
  o que decidiu remover a rota `/mc/bin/sequences` — nada no payload diz de qual bin a
  timeline veio.
- ⛔ **`text/uri-list` + `Files` não servem**: apontam para um `.aaf` no Temp que tem
  **zero bytes** (*delayed rendering* do Windows — só materializa para alvo do shell).
  Teria eliminado o `ExportFile` + preset; não elimina. Segue `pendente` se um processo
  **nativo** consegue materializá-lo.

  ⭐ **Ressalva que a leitura acima quase custou (2026-08-16):** isso vale para o
  `uri-list` **deste** arrasto, o do Media Composer. Num arrasto vindo do **Explorer**,
  o `text/uri-list` traz o **caminho absoluto de verdade** — e é por ele que a **pasta
  de mídia** passou a entrar. O mesmo `drop`, o mesmo tipo MIME, conclusões opostas
  conforme a ORIGEM. *"O `uri-list` não serve" era verdade sobre um arrasto, não sobre o
  mecanismo* — e ⚠️ note que `Files[0].tamanho == 0` aparece nos dois casos por motivos
  diferentes: lá porque o arquivo não existe, aqui porque **pasta não tem tamanho**.
  A regra que separa: **quem vale é o caminho, nunca o objeto `File`.**
- `head` (veio `"0"`) segue não decifrado.
- Se o painel deveria também **arrastar para fora** (`DropFromPluginTo*` +
  `text/x.avid.panel-sdk-plugin-asset-list+json`) — entregaria a bin relinkada direto na
  timeline, em vez de o editor procurá-la.
- A ponte de **eventos** do QWebChannel após navegar para `http://` **continua
  `pendente`**: é outro mecanismo, e o achado do arrasto não diz nada sobre ele.
