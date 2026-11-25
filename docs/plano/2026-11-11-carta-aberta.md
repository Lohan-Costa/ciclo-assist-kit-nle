# Carta Aberta — a pasta de trabalho compartilhada entre editores (era o "Magic Link")

**Estado:** proposta, à espera das respostas do autor (fim do arquivo). Nada de código ainda.
**Data:** 2026-11-11 (Mac mini). **Substitui**, quando aprovado, os ADRs 0016 e 0018 do Conformar
(`modulos/conformar/docs/adr/`); o 0020 (relink aos originais ao importar) continua valendo.
**Inspiração:** o Avid Production Manager (Production Management Best Practices Guide 2022.3): cada editor
trabalha no próprio projeto, sobe só a timeline para um painel com árvore de pastas à esquerda e itens à direita,
e quem puxa leva uma CÓPIA, mexe e devolve uma versão nova.

## 1. Decisões do autor (2026-11-11)

1. **O nome é Carta Aberta**, o mesmo nome do envelope que já existe (`docs/carta-aberta.md` do Conformar). Nada de
   nome em inglês.
2. **O botão fica logo abaixo de "Fluxos e Agentes"** (`#botaoOficina`, `cicloassist/painel/index.html:322`): os dois
   botões que abrem janela própria ficam juntos. A janela é nova (como `app/src-tauri/src/oficina.rs`).
3. **Uma pasta em rede por projeto.** Dentro dela, as pastas são do usuário (`Cenas Editadas/C07`…). A separação por
   setor (cor, VFX: o ADR 0018) **sai**; se um dia houver necessidade, será outro desenho.
4. **A mídia não é copiada nem movida. Nunca.** A Carta Aberta só **registra** os caminhos que a mesma mídia tem:
   - o **original de câmera** (BRAW, num NAS ou num HD);
   - a **OP-Atom** do `Avid MediaFiles`;
   - a **versão de trabalho** para o Premiere (mov/mp4/wav).
5. **Primeiro par: Avid ⇄ Premiere**, nos dois sentidos.
6. **Conteúdo:** as **diárias** (o material) e as **timelines das cenas**.
7. **Quem puxa a diária recebe a forma do programa dele:** no Avid, a OP-Atom; no Premiere, a versão de trabalho.
8. **Quem devolve devolve SÓ a timeline**, numa pasta que ele mesmo cria.
9. **A experiência é a mesma no Media Composer e no Premiere.** Adaptações naturais, mas tem de parecer que todos
   estão no mesmo programa.
10. **O programa não cria pasta nenhuma sozinho.** "Novo projeto" pede nome e local (uma pasta em rede); a pasta
    escolhida é a raiz. As pastas de dentro o editor cria, pelo painel ou pelo Finder/Explorer (§4.1).
11. **Na raiz só moram arquivos nossos; o resto vai para a Quarentena**, como a `Avid MediaFiles` faz (§4.1).
12. **A mídia entra pelo NLE**, das bins: masterclipes no Avid, clipes no Premiere. Arrastar do Finder/Explorer fica
    para o futuro (§4.2).
13. **Os outros formatos se anexam**: selecionar os clipes de uma diária e apontar uma pasta; o programa casa por nome
    do material, duração e quadros inicial e final, e guarda o casamento como memória compartilhada (§4.2, §4.5).
14. **Subclipe, merged clip, multicâmera e group clip viajam VIVOS** (§4.6). ⛔ Nada de achatar para o master, como o
    conform do De Lá Pra Cá faz (ADR 0006 de lá): aqui a troca é para EDITAR, e o editor do outro lado precisa do
    subclipe e do grupo para continuar. Subclipe sincronizado do Avid chega como merged clip no Premiere, e o
    contrário; group clip chega como sequência multicâmera, e o contrário.
15. **Primeira versão sem efeitos.**
16. **A mesma mídia tem um caminho POR MÁQUINA** (como o Premiere guarda mais de um caminho por mídia): quem está no
    Windows informa o dele, quem está no Mac o dele, e o programa usa o da máquina em que está (§4.7).
17. **Relink é parte do app**, não um extra (§4.7).
18. **Começa no Mac mini**, Premiere ⇄ Media Composer na mesma máquina. O Windows e a rede vêm quando o autor preparar.
    A versão de trabalho da PRODUCAO-A é MP4 (+ WAV), confirmado pelo autor.

> 🆕 Decisões de 2026-11-12: o "Puxar" no Premiere SALVA o projeto do editor sozinho, sem perguntar (é o que permite
> o enxerto sem duplicar a mídia); o TC do merged é o da mídia de VÍDEO.

## 2. A história que o plano tem de cumprir (o teste de aceitação)

Com **PRODUCAO-A** (`MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A`):

1. O editor A (Avid) cria o projeto "PRODUCAO-A" numa pasta em rede, cria `Diarias/D01` e manda para lá os
   masterclipes da bin D01 do `PRODUCAO-A_CURTA`. Depois seleciona a D01 e anexa a pasta dos convertidos (MP4/WAV)
   e a dos originais (BRAW): cada mídia fica com as três formas.
2. O editor B (Premiere, outra máquina, a mesma rede, a mesma pasta) **traz uma diária**: entram os convertidos, nas
   mesmas bins que o A vê.
3. B monta a C07 e **leva a timeline** para `Cenas Editadas/C07`.
4. O editor C (Media Composer, outra máquina) **traz a timeline**: ela abre no Avid de C apontando as OP-Atom, corte
   a corte igual ao que B montou. C faz uma versão nova e **leva de volta**: `C07 v2`, ao lado da v1, sem apagar
   nada.

## 3. O que já existe e será reaproveitado (não reescrever)

| peça | onde | o que dá |
|---|---|---|
| O envelope, **sem perdas**, Avid → JSON | `modulos/conformar/motor/carta_aberta/writer.py` / `reader.py` | timeline + masters com `arquivo_original` (Source File), `arquivo_ama`, `gerenciadas` (OP-Atom por essência). Teste: DRT da bin ≡ DRT da Carta em 80 sequências |
| A leitura de `.prproj` | `modulos/conformar/motor/prproj/leitura.py` | a base do Premiere → Carta |
| A cópia de `.prproj` + `importSequences` | `motor/prproj/copia.py` | o jeito medido de pôr uma sequência NOVA no projeto do editor, sem mexer na dele (23.2 e 26.5.2) |
| **Casar o original com a conversão** | `cicloassist/midia/identidade.py` | ⭐ já medido **neste material**: 202 de 203 arquivos do Premiere acharam o OP-Atom do Avid; o BRAW casa pelo som (5 de 5) |
| Banco de mídias por produção, chaveado por NOME | ADR 0014 do Conformar | a regra da chave (o `mob_id` do AMA muda a cada link: 83 de 118) |
| Escrita em pasta de rede sem trava | banco `transversal/banco-de-midias-compartilhado.md` §4 | gravar ao lado + `os.replace`; nunca dois escrevendo o mesmo arquivo |
| A Carta como texto de terceiro | `reader.py`, ameaças T-15 a T-17 | teto de tamanho, forma conferida, nenhum caminho de dentro tocado sem conferência |
| Escrever sequência numa bin do Avid | `cicloassist/avid/` (`montar_corte`, `edicao.py`, `avb_fiel.py`) | `CloseBin` → pyavb → `OpenBin`, a bin do editor preservada |
| Falar com os programas por fora | MC pelo gRPC 9100, Premiere pela ponte CEP | o "Trazer" abre a coisa no programa sem o editor importar à mão |

## 4. O desenho

### 4.1 O projeto: o programa não cria pasta nenhuma sozinho (autor, 2026-11-11)

- **"Novo projeto"**: o editor dá um NOME e escolhe um LOCAL (uma pasta em rede, para as outras máquinas alcançarem).
  A pasta escolhida é a **raiz** do projeto. **"Abrir projeto"** aponta uma raiz que já existe.
- As pastas são do editor: ele cria pelo painel ou pelo Finder/Explorer, e a janela mostra o que houver.
- **Dentro da raiz só moram arquivos nossos.** Uma mídia ali é uma REFERÊNCIA (um arquivo nosso que aponta a mídia),
  nunca a mídia. ⛔ Atalho do sistema não serve (symlink não atravessa exFAT/SMB entre os dois sistemas — regra da família).
- **Quarentena** (como a `Avid MediaFiles` faz com o que não é OP-Atom): todo arquivo que não é nosso vai para
  `<raiz>/Quarentena/<data>/<o caminho de onde veio>` e sai da leitura. Nada é apagado.
  - ⛔ **Não vão para a quarentena:** as sombras e os arquivos do sistema (`._*`, `.DS_Store`, `Thumbs.db`,
    `desktop.ini`): voltam sozinhos a cada gravação, e a quarentena encheria de lixo. São só ignorados.
  - ⛔⛔ **Nem o temporário de OUTRA máquina escrevendo agora** (`*.parcial`, a gravação atômica): movê-lo corromperia
    a escrita dela. Ele só vai para a quarentena se estiver parado há mais de um dia.
  - Pasta vazia fica (é estrutura do editor).

```
<raiz>/                       (o nome e o local, escolhidos pelo editor)
├─ .carta/                    o que faz o programa funcionar (oculto para não ser mexido à mão)
│   ├─ projeto.json           nome, taxa, quando nasceu: escrito UMA vez
│   └─ registro/              ⭐ a memória compartilhada: UM arquivo por máquina e usuário (§4.5)
│       ├─ MAQUINA-1.jsonl
│       └─ EDITOR2-WIN.jsonl
├─ Diarias/D01_230403/        pastas do EDITOR
│   └─ A002_03170703_C003.ref.json      a referência de UMA mídia (§4.2)
├─ Cenas Editadas/C07/
│   ├─ C07__2026-11-11T1502__MAQUINA-1.carta.json     a janela mostra "C07 v1"
│   └─ C07__2026-11-12T1040__EDITOR2-WIN.carta.json       a janela mostra "C07 v2"
└─ Quarentena/
```

### 4.2 A mídia entra pelo NLE; os outros formatos se ANEXAM depois (autor, 2026-11-11)

1. **Trazer do NLE** (a única porta na v1; arrastar do Finder/Explorer, talvez no futuro): os masterclipes das bins
   do Avid, os clipes das bins do Premiere. Cada um vira um `.ref.json` na pasta onde o editor o pôs.
2. **Anexar outro formato:** o editor seleciona clipes (uma diária inteira) e aponta uma pasta — a `Avid MediaFiles`,
   a dos MP4, a dos originais em alta. O programa varre e **casa**, e cada casamento vira um vínculo no registro.
   - A régua do casamento: **nome do material** (`material_package_name` / reel) + **duração** + **quadro inicial e
     final** (TC de entrada e saída). Medido no `identidade.py`: é a porteira certa, e quando ela deixa dois
     candidatos o desempate é pelo conteúdo (pixel na imagem, a onda no som; o BRAW, pelo som). Empate que nem
     isso resolve vai para o editor.
3. O `.ref.json` é **imutável**: guarda a IDENTIDADE da mídia (nome, reel, TC, duração, taxa, a forma pela qual ela
   entrou) e um `id`. Ele não guarda os vínculos. ⭐ Por isso o editor pode mover e renomear as referências no
   Finder à vontade: os vínculos são do `id`, não do caminho.

```json
{ "carta_aberta": "ref/1", "id": "…", "nome": "A002_03170703_C003", "tipo": "video",
  "identidade": { "reel": "A002_03170703_C003", "tc_in": "03:14:14:17", "tc_out": "03:18:02:10",
                  "fps": "24000/1001", "quadros": 5480 },
  "entrou_por": { "nle": "premiere", "forma": "trabalho", "arquivo": "A002_03170703_C003.mp4" } }
```

- ⛔⛔ **O caminho é DICA; a identidade é a verdade.** `D:\` no Windows é `/Volumes/SSD` no Mac, e cada
  máquina monta o NAS de um jeito: guarda-se o rótulo do volume + o relativo, e o absoluto observado (banco §5).
  Caminho vindo da rede é entrada não confiável (UNC dispara SMB só com um `stat`: matriz, linha "caminho UNC").
- ⛔ Um vínculo só entra se o quadro N for o mesmo quadro N (mesma taxa, mesmo TC, mesmo número de quadros ±1). A
  conversão que é um RECORTE do original (consolidate com alças) não entra na v1, e o motivo é dito.

### 4.3 Os quatro gestos

| gesto | Avid | Premiere |
|---|---|---|
| **Mandar mídia** (da bin para a Carta) | os masterclipes da bin → `.ref.json` com a forma `avid` (+ o `original` que o Source File já diz) | os clipes da bin → `.ref.json` com a forma `trabalho` |
| **Anexar formato** (na janela) | igual nos dois: selecionar clipes, apontar uma pasta, varrer, casar (§4.2) | |
| **Puxar mídia** (da Carta para o NLE) | bins com os masters apontando as OP-Atom | importa os arquivos de `trabalho` nas mesmas bins (`importFiles`) |
| **Mandar timeline** | `writer.py` (existe) | **novo:** `.prproj` → Carta (sobre `leitura.py`) |
| **Puxar timeline** | **novo:** Carta → sequência numa bin, apontando os masters da diária | **novo:** Carta → `.prproj` temporário → `importSequences` (o caminho medido do `copia.py`) |

Escolha da forma ao trazer: o padrão é a do programa (decisão 7). Um seletor "trazer com: original / OP-Atom /
trabalho" fica para quando o conform entrar; o registro já guarda tudo para isso. E a conta é sempre dita: *"38 de
40 na versão de trabalho, 2 sem conversão vieram no original"*. Nunca trocar de forma sem avisar.

### 4.4 O que a timeline leva na v1 ("1:1")

- **Entra:** cortes, trilhas de vídeo e de áudio, sincronia, TC de início, taxa, nome, ganho de clipe.
- **Fora, e DITO na própria Carta** (`avisos`, que já existe): efeitos, transições além do dissolve, velocidade,
  multicâmera, títulos. Cada um entra depois, com medição nos dois programas.
- ⛔ Não alterar um quadro da edição (regra do De Lá Pra Cá): o que não dá para traduzir é recusado com aviso, nunca
  "aproximado".

### 4.5 Dois editores ao mesmo tempo: sem trava de arquivo

⛔ **Trava de arquivo (file lock) não é o indicado**, e o banco já tinha isso (`banco-de-midias-compartilhado.md` §4,
*"em SMB lock não é confiável"*):
- a trava do SMB se comporta diferente no servidor Windows, no NAS e no cliente do Mac (`smbfs` guarda cache);
- um arquivo `.lock` fica ÓRFÃO quando a máquina cai, dorme ou perde a rede, e trava todo mundo até alguém apagar
  à mão; uma trava com prazo depende dos relógios das máquinas baterem;
- e travar não basta: quem leu antes da trava e grava depois apaga o que o outro fez do mesmo jeito.

⭐⭐ **O desenho: ninguém regrava nada, e cada um escreve só no SEU arquivo.**
1. **O registro é um diário de fatos**, um `.jsonl` por máquina e usuário, em que só se ACRESCENTA linha:
   *"a mídia X tem a forma `trabalho` no arquivo Y, casada por nome+duração+TC, medida 0,998, por Fulano, às 15:02"*.
   Desfazer também é uma linha (*"tirei o vínculo Z"*), nunca apagar a de antes.
2. **O estado é a SOMA dos diários**, lida por cada máquina. Leitura defensiva: linha que não parseia (pode estar
   sendo escrita agora) é pulada.
3. **Um consolidado é só atalho de leitura**, regravável por qualquer um a partir dos diários; perdê-lo não perde nada.

**O caso do autor:** A aponta os MP4 da D01 e B, ao mesmo tempo, os MOV. ⇒ **Não há conflito.** São duas linhas em
dois arquivos, e a mídia fica com as DUAS formas de trabalho (`trabalho: mp4` e `trabalho: mov`). Ao trazer no
Premiere, o editor escolhe qual (ou o padrão do projeto). É o seu próprio desenho — uma mídia com vários caminhos —
que faz o conflito sumir: acrescentar nunca briga com acrescentar.

**Quando há conflito de verdade, e o que se faz:**

| situação | o que o programa faz |
|---|---|
| dois vínculos para a MESMA forma da mesma mídia, com arquivos DIFERENTES (dois MP4 diferentes para o mesmo clipe) | mostra os dois com quem fez e a medida; ⛔ não escolhe sozinho (empate é do editor) |
| A tirou um vínculo que B acabou de confirmar | os dois fatos ficam; vale o mais novo, e a janela diz *"B confirmou às 15:03 depois que A tirou às 15:02"* |
| dois editores levam a C07 ao mesmo tempo | dois arquivos com nome único (data + máquina), nunca o mesmo nome: viram v3 e v4, em ordem de data |

- ⚠️ "O mais novo" usa o relógio de cada máquina. Uma diferença de minutos entre as máquinas inverteria a ordem num
  caso raro, e por isso a janela mostra quem fez e quando, em vez de esconder.
- ⚠️ Gravar o diário: acrescentar ao fim do próprio arquivo. ⬜ **Medir na C0:** acrescentar num `.jsonl` aberto pelo
  OUTRO sistema enquanto ele lê (Windows escrevendo, Mac lendo pelo SMB, e o contrário), e quanto tempo o cache do
  `smbfs` do Mac leva para mostrar a linha nova.

### 4.6 Os itens que juntam mídias: subclipe, merged clip, multicâmera (autor, 2026-11-11)

Além da referência de UMA mídia, a pasta guarda a referência de um item que JUNTA mídias (`.item.json`, também
imutável, também na pasta do editor). Ele não aponta arquivo nenhum: aponta os `id` das mídias e diz como se juntam.

| no Avid | na Carta | no Premiere |
|---|---|---|
| subclipe de UM master | `recorte`: mídia + entrada e saída (no tempo do MASTER) | subclipe |
| subclipe SINCRONIZADO (imagem de um master, som de outro) | `sincronizado`: imagem (mídia + início) e som (mídia + início + canais), cada um com o SEU início | merged clip |
| group clip (multicâmera) | `grupo`: os ângulos (cada um uma mídia ou um `sincronizado`) + o ponto de sincronia + o ângulo de áudio | sequência multicâmera (a fonte) |

- ⛔⛔ **Cada lado leva o seu início**, nunca "o offset do take": medido no Avid, imagem em 0 e som em 234 quadros
  (`avid/take.py`, banco `avb/sincronizacao-e-subclipes.md`). Um valor único dessincroniza calado.
- ⛔ A timeline que usa o item aponta o ITEM, não as mídias de dentro: no Avid o segmento é do subclipe ou do group
  clip (com o ângulo escolhido no `Selector`), no Premiere do merged clip ou da sequência multicâmera (com o ângulo
  escolhido). É o que mantém o trabalho do outro editor vivo: ele pode trocar o ângulo, reabrir o subclipe.
- O que o banco já tem: o Avid sincronizado e a autoria de subclipe por pyavb (`confirmado`, MC 2025.6 e 24.6); o
  Premiere: merged clip e sequência multicâmera escritos no `.prproj` (`prproj/escrita.md` §2 e §5, `confirmado` no
  25.6.5, pelo Órbita). ⚠️ **O que NÃO tem:** group clip do Avid por dentro, lido ou escrito (nenhuma bin medida tinha
  um: `avb/fontes.md`); e como pôr merged clip e multicâmera num projeto do Premiere JÁ ABERTO (não há API; o
  `importSequences` traz sequências, e não se sabe se traz o merged clip que elas usam). Os dois vão para a C0.

### 4.7 Um caminho por máquina, e o relink dentro do app (autor, 2026-11-11)

- O diário (§4.5) guarda, para cada forma de cada mídia, **onde ela está em cada máquina**: *"a forma `trabalho` da
  mídia X, no MAQUINA-1, está em `/Volumes/SSD/…/A002_…mp4`"*. O editor do Windows acrescenta a linha
  dele com `D:\…`. Não há caminho "certo": há o desta máquina.
- **Puxar** usa o caminho DESTA máquina. Sem caminho dela, tenta traduzir o de outra máquina pelo rótulo do volume
  (`/Volumes/SSD/x` ⇄ a letra cujo volume se chama `SSD`, já medido no De Lá Pra Cá: matriz, linha
  "caminho do OUTRO SO") e confere a identidade.
- **Relink** quando nem isso acha: o editor aponta pastas e o programa casa pela mesma régua do "anexar formato", com
  o motor do Conformar (`indexer`, `matcher_masters`, o banco por produção do ADR 0014, a revisão de empates). ⭐ O
  que um relink acha vira linha no diário: o próximo editor da mesma plataforma já encontra.
- ⛔ Mídia que não se acha entra OFFLINE, com o nome e o TC certos, e a conta é dita (*"3 de 40 offline: …"*). Nunca
  uma mídia parecida no lugar.

## 5. Fases

| fase | entrega | pronto quando |
|---|---|---|
| **C0** medir | (a) MC de outra máquina enxerga a OP-Atom pela rede? (b) uma bin escrita por nós com masters de OUTRO projeto linka a OP-Atom? (c) diária no Premiere: arquivos soltos ou sincronizados? (d) ⭐ **como a mídia sai da bin para a NOSSA janela**: o arrasto do MC entrega o MobID ao painel de dentro (banco `arrastar.md`), mas a janela do app é outra webview e nunca foi medida; o arrasto da bin do Premiere não entrega nada (banco). Reserva: um botão "mandar a seleção" que lê a seleção da bin pela API. (e) acrescentar linha no diário pelo SMB, Windows escrevendo e Mac lendo e o contrário, e o atraso do cache do Mac (fica para quando o Windows entrar). (f) ⭐ group clip do Avid: ler e escrever por pyavb, com um grupo feito à mão num projeto de teste. (g) ⭐ pôr merged clip e sequência multicâmera num projeto do Premiere ABERTO | as respostas no banco, com versão do programa e do sistema |
| **C1** o projeto e o registro | Novo/Abrir projeto, `.carta/`, `.ref.json`, o diário, a quarentena, mandar mídia do Avid e do Premiere, anexar formato | PRODUCAO-A D01: N mídias, quantas com as 3 formas, quantas sem vínculo e por quê; dois processos anexando ao mesmo tempo sem perder nada |
| **C2** a janela | botão abaixo de Fluxos e Agentes, árvore + lista, criar pasta, ver versões | conferida no app, no Mac e no Windows |
| **C3** Premiere ⇄ Carta | levar e trazer timeline e diárias no Premiere | a C07 vai e volta no Premiere com corte idêntico em ticks |
| **C4** Avid ⇄ Carta | trazer timeline no Avid; levar no Avid já existe | a C07 do Premiere abre no MC online, corte a corte |
| **C5** a história do §2 | no Mac mini, Premiere ⇄ MC (dois projetos fazendo papel de dois editores), com subclipes e um grupo; depois Windows e rede | o autor assiste à v2 no MC e à v1 no Premiere |

Depois: o seletor de forma e o conform aos originais (ADR 0020), o Resolve, efeitos.

### C1 — andamento

- ✅ (2026-11-12) **O núcleo, sem tela**: `cicloassist/carta/` — `projeto` (novo/abrir sobre a raiz que o editor
  escolheu, `.carta/projeto.json`, a máquina, a quarentena), `diario` (um `.jsonl` por máquina, só acrescenta, `tirar`
  desfaz, soma defensiva), `referencias` (`.ref.json` imutável e idempotente, `onde()` = rótulo do volume + relativo),
  `anexar` (`mandar_arquivos` e `anexar` pela régua do `identidade.e_candidato`; empate não grava, vai na conta).
  `tests/test_carta.py`, 13 testes: dois processos × 300 linhas no MESMO diário sem perder nenhuma.
- ✅ **Mandar do Avid por MASTER** (`anexar.mandar_do_avid`, sobre o `acervo.Clipe`): uma referência por master, a forma
  `avid` com os N arquivos; a identidade da SONDA, não do nome da bin. ✅ O `anexar` agrupa a OP-Atom pelo UMID e separa
  pela forma (`avid` só OP-Atom). ✅ O `tirar` vale em qualquer ordem (o teste pegou o vínculo "ressuscitando").
- ✅ **A prova na D01 da PRODUCAO-A** (`spikes/carta_aberta_c1_d01.py`, projeto em `9 SAIDAS DOS APPS/_CICLO ASSIST/
  2026-11-12 CARTA ABERTA D01`): **26 mídias — 5 com avid + trabalho, 21 com trabalho; 0 com as 3 formas.** Por quê: o
  original BRAW está no NAS (desligado) e a OP-Atom da câmera A não está no disco do Mac (o projeto do MC é do Windows).
  O som tem DUAS cópias da forma avid (a da `Avid MediaFiles` e a OP-Atom dos convertidos): fica com as duas, e quem
  puxa escolhe (empate é do editor). Tudo em < 1 s por gesto.
- ✅ **As rotas** (`servico/rotas_carta.py`): `/carta/novo` e `/carta/abrir` (a raiz pelo SELETOR do sistema, guardada como
  autorizada no `estado.json`), `/carta/projetos`, `/carta/estado`, `/carta/mandar` (Premiere: a SELEÇÃO da bin pela ponte;
  Avid: `mob_ids` → acervo) e `/carta/anexar` (a pasta de mídia pelo seletor). ⭐ Mandar a mesma mídia pelo OUTRO NLE acha
  a referência que já existe (a régua do anexar) e só acrescenta a forma.
- ✅ **De ponta a ponta com os programas, pilotado (2026-11-12, Mac):** "novo projeto" pelo diálogo do sistema →
  `2026-11-12 CARTA ABERTA G01`; mandar do Avid (4 masters do G01 no MC 25.12: 4 referências, forma `avid`, 33 s — a 1ª
  varredura das `Avid MediaFiles`); mandar do Premiere (a seleção da bin no 26.0.2: as MESMAS 4 ganharam `trabalho`,
  0,04 s; o merged selecionado volta em `sem_arquivo`). Cada mídia do G01 com OP-Atom + versão de trabalho.
- ✅ O UMID como prova antes da régua (igual = prova; diferente não reprova) e o desempate pelo CONTEÚDO
  (`identidade._conferir` contra um arquivo que a referência já tem nesta máquina; só um passando = vínculo com a medida).
  ⚠️ Na D01 nenhum par tem UMID dos dois lados (o WAV não tem: corrigido no banco).
- ✅ **Os itens do AVID** (`carta/itens.py`, `.item.json` imutável e idempotente pelo conteúdo): `recorte` (subclipe),
  `sincronizado` (subclipe sincronizado, cada lado o seu início) e `grupo` (as fontes INTEIRAS com o deslocamento, o
  ângulo e o ângulo do som), lidos da bin. Provado na `CARTA ABERTA G01 AVID v01` contra a verdade do laboratório:
  deslocamentos 72/240/144/0 (= 3/10/6/0 s), som do sync no 240, recorte 200–400.
- ✅ **Os itens do PREMIERE** (`itens.do_premiere`, do `.prproj` SALVO): merged → `sincronizado`, multicâmera → `grupo`
  (início − entrada = o deslocamento), o arquivo → a referência pelo caminho do diário NESTA máquina. ⭐ Lidos do
  `G01 ARRASTO MAC v01`, deram os MESMOS números do lado Avid e foram RECONHECIDOS como os mesmos itens (a identidade
  é a estrutura; ângulo e duração são estado de edição). ⛔ A multicâmera recém-criada não tem a chave que o Conformar
  procurava: a marca é o `Multicam.Enabled` do MasterClip (banco `relink-e-geometria.md` §10.5).
- ✅ **`/carta/mandar` do Avid leva os ITENS** (subclipe, sincronizado, grupo pelos MobIDs → a bin pelo
  `bins.bins_dos_mobs` → os masters de que dependem mandados ANTES → o item). Provado no MC 25.12: projeto VAZIO
  (`2026-11-12 CARTA ABERTA ITENS`, pelo diálogo) + só os 3 itens da `CARTA ABERTA ITENS v01` → 4 referências + 3 itens,
  0,56 s.
- ✅ **`/carta/mandar` do Premiere leva os ITENS** (merged e multicâmera da seleção, lidos do `.prproj` SALVO pelo nome; os
  arquivos das trilhas deles vão ANTES). Provado no 26.0.2: no projeto `ITENS` (itens vindos do Avid), a seleção
  multicâmera + merged → CAM 1–3 e o som ganharam `trabalho` (conferidos pelo conteúdo) e os 2 itens foram RECONHECIDOS
  como os do Avid (`ja_estavam`), 3,6 s.
- ✅ **O subclipe do Premiere** (2026-11-12, `itens._subclipes`, do `.prproj` SALVO): o `MasterClip` com
  `StartBoundary`/`EndBoundary` no `MediaSource` (ticks desde o 1º quadro do arquivo) → `recorte`. A seleção da API
  entrega o subclipe com o arquivo do master, então o `/carta/mandar` agora olha o projeto salvo para TODOS os nomes
  selecionados (antes só para os sem arquivo) e avisa (`itens.avisos`) quando um nome que não é o do arquivo não foi
  achado como subclipe ("salve o projeto"). Provado pilotado no 26.0.2: `G01 SUBCLIPE v01` (cópia nova do v02) →
  `G01_CAM3.sub.01` mandado ao projeto `ITENS` = RECONHECIDO como o subclipe do Avid (200–400, `ja_estavam`).
  Banco `premiere-cep/subclipe-e-merged-clip.md`. Suíte 1971/38.
- ✅ **O ângulo ativo da multicâmera do Premiere** (2026-11-12): `Source.Monitor.Multicam.TrackIndex` do MasterClip
  (a trilha de vídeo, do 0) → `angulo`. MEDIDO pilotado no 26.0.2 com o gesto do autor (duplo clique na bin → mosaico
  no Origem, borda amarela = ativo): CAM 2 + Salvar → 0 → 1 (`G01 ANGULO v01.prproj`). `angulo_do_som` fica vazio do
  lado do Premiere (sem equivalente medido). Banco `prproj/escrita.md` §5. Suíte 1973/38.
- ✅ **O ângulo vigente é o do ÚLTIMO "mandar"** (decisão do autor, 2026-11-12, opção b): o ângulo continua fora da
  identidade do item; o grupo já registrado mandado com outro ângulo gera um fato `angulo` no diário (só se acrescenta,
  vale o mais recente; `None` — o som do Premiere — mantém o vigente), e `itens.todos` devolve o vigente
  (`itens.registrar`, `itens.angulos`; a conta diz `angulos`). Provado: o `G01-GRUPO-SOM` do Avid (CAM 1) no projeto
  `ITENS` mandado do `G01 ANGULO v01` → CAM 2, som segue CAM 1; mandado de novo → nenhum fato novo. Achado junto: o
  WAV de duas trilhas de áudio entrava duas vezes na lista do "mandar" (corrigido; a conta dizia a mídia em dobro).
- ✅ **C1 fechada no Mac** (fora a D01 com as 3 formas, à espera do NAS e da OP-Atom do Windows). Próxima: a C2 (a janela).
- ✅ **O conteúdo decide também no "mandar"** (`anexar._referencia`): achada pela régua e havendo arquivo dela nesta
  máquina, a imagem/o som confirma; discordou = HOMÔNIMO; várias pela régua = fica a que o conteúdo confirmar. Testado
  com vídeo (testsrc × smptebars). ✅ (2026-11-12, decisão do autor) o homônimo vai para o EDITOR como empate: nada é
  criado nem vinculado, `empates` traz a medida e `homonimos` o porquê. ⬜ Na C2 a janela pergunta "é a mesma ou outra?"
  (outra = `referencias.criar(…, distinta=True)`).
- ❓ **Pergunta ao autor (som):** o WAV da `G01_CANAIS` tem o canal L IDÊNTICO ao do G01 (+1,000) e o R trocado por um tom
  (−0,005). A régua de som da casa ("o MELHOR par de canais decide", feita para o BRAW cujo transcode processou um canal:
  0,789 × 1,000) o aceita como a MESMA mídia. Opções: (a) manter; (b) exigir TODOS os canais acima de um piso baixo
  (0,5): reprova o tom no lugar da cena e ainda aceita o BRAW. Não mudado.
  ✅ **Respondida (2026-11-12): (a), não muda.** O caso é sintético; a régua dura daria falso negativo no convertido
  (mixdown, canal mudo, compressão). Piso de identidade só se calibra com material real. E o homônimo do "mandar" passa
  a ir para o editor (como empate), em vez de virar referência nova sozinho — ✅ feito; banco §8b(f).
- ⬜ A D01 com as 3 formas quando o NAS e a OP-Atom da câmera estiverem à mão. Depois a C2 (a janela).

### C2 — proposta (2026-11-12, respondida pelo autor no mesmo dia)

**O que a C2 entrega:** a janela da Carta Aberta, sobre o núcleo da C1 (que já funciona sem tela). Ela NÃO traz
timeline nem puxa mídia para o NLE: isso é C3 (Premiere) e C4 (Avid). ⛔ Botão de gesto que ainda não funciona não
aparece (regra "não inchar o app").

**A janela** (o formato da de Fluxos e Agentes: `app/src-tauri/src/carta.rs` + página servida `/carta`, sem IPC):

```
┌ Ciclo Assist — Carta Aberta ──────────────────────────────────────────────────────────────────┐
│ PRODUCAO-A ▾   (Novo… · Abrir… · recentes)        /Volumes/NAS/PRODUCAO-A   ⟳ há 5 s       │
├──────────────────────┬────────────────────────────────────────────────────────────────────────┤
│ ▾ PRODUCAO-A       │ Diarias/D01                                   [Anexar formato…]          │
│   ▾ Diarias          │ nome                    tipo         TC início    dur.    Avid Trab Orig  │
│     ▸ D01   26       │ A002_03170703_C003      vídeo        03:14:14:17  3:48     ●    ●    ○   │
│     ▸ D02            │ …C14 P1-T010            som          11:42:00:00  2:01     ●    ●    —   │
│   ▸ Cenas Editadas   │ C07_P03-T001            subclipe     (de A002_…)  0:12                   │
│   + Nova pasta       │ G01-GRUPO-SOM           multicâmera  4 fontes · ângulo CAM 2             │
│                      │                                                                          │
│ ⚠ 2 a decidir        │ solte aqui o que vier da bin do Avid ou do Premiere                      │
└──────────────────────┴────────────────────────────────────────────────────────────────────────┘
```

1. **Projeto:** Novo (nome + taxa; o LOCAL pelo seletor do sistema), Abrir (o seletor), e os recentes (`/carta/projetos`).
   Um projeto por vez na janela.
2. **A árvore à esquerda** = as pastas do editor (a quarentena e a `.carta/` não aparecem; a contagem ao lado).
   **Nova pasta** dentro da selecionada (rota nova `/carta/pasta`: só cria DENTRO da raiz, nome conferido).
3. **A lista à direita** = o que mora na pasta: referências (uma mídia) e itens (subclipe, sincronizado/merged,
   multicâmera/grupo), com as FORMAS que cada mídia tem NESTA máquina (● tem · ○ não tem · — não se aplica).
   Clique numa linha: o detalhe embaixo (de onde veio, quem mandou, os caminhos por máquina, a medida do casamento).
4. **Mandar = arrastar da bin para a janela** (o `arrasto_mac`/`arrasto_win` já entregam MC e Premiere: C0(d)). Soltar
   sobre uma pasta da árvore manda para ELA; soltar na lista manda para a pasta aberta. A conta aparece numa faixa
   (`3 novas · 1 já estava · 1 subclipe · ⚠ 1 a decidir`) e fica no histórico da sessão.
5. **Anexar formato:** selecionar linhas (ou nenhuma = a pasta inteira) → escolher a forma → o seletor de pasta →
   a conta (vinculadas, sem par, fora da forma, a decidir).
6. **"A decidir"** (empates e homônimos): uma lista própria, nunca diálogo que interrompe. Cada caso mostra os
   candidatos com a medida e dois botões: **"é a mesma"** (vincula) / **"é outra"** (`referencias.criar(…, distinta=True)`).
   ⚠️ Hoje o empate não é GUARDADO (volta só na conta do gesto): para a lista sobreviver a fechar a janela, o empate
   vira um fato `pendente` no diário (os outros editores também o veem).
7. **Atualizar:** reler a pasta e os diários ao focar a janela e a cada ~10 s com ela à vista (o outro editor manda
   pela rede); a hora da última leitura no topo.
8. **A quarentena** roda ao abrir o projeto (já existe) e é DITA: *"2 arquivos que não são da Carta foram para a
   Quarentena"*.

**Pronto quando** (o critério da tabela de fases): no Mac, com o app, criar o projeto, criar `Diarias/D01`, arrastar a
bin G01 do MC e a do Premiere, anexar uma pasta, resolver um homônimo — tudo pela janela, pilotado e com fotos. O
Windows quando o autor preparar (o `arrasto_win` já tem os dois NLEs).

Protótipo visual: `docs/plano/prototipos/janela-carta-aberta.html` (publicado em https://claude.ai/artifact/592Whremh9kyWjUkDzF8kF).

**Respostas do autor (2026-11-12):**
1. A lista: **nome, tipo, TC de início, duração e as três formas** (Avid · Trabalho · Original); o detalhe ao clicar.
2. Empates e homônimos: a **lista "A decidir", GUARDADA** no registro (fato `pendente` no diário; "é a mesma" / "é outra"
   viram fatos que o resolvem): sobrevive a fechar a janela e os outros editores veem.
3. Anexar formato: **o editor escolhe a forma no gesto** (Avid / Trabalho / Original), nada deduzido.
4. Pastas e referências: **tudo pela janela** — criar, renomear e mover (pastas e referências, arrastando entre pastas),
   e **tirar** (⛔ nunca apaga: vai para a `Quarentena/<data>/…`, como o resto que sai da raiz).
   ⚠️ A medir antes: o arrasto INTERNO da página (linha → pasta) passa pelo mesmo `NSDraggingDestination`/`IDropTarget`
   que o `arrasto_mac`/`arrasto_win` registram para o NLE — ele não pode virar um "mandar" do Premiere (`public.data`).
   ⚠️ Mover/renomear é `os.replace` dentro da raiz (o vínculo é do `id`); pasta de destino conferida dentro da raiz;
   em rede, outro editor pode estar lendo: a lista dele se relê e acha a referência no lugar novo.

**Retorno do autor sobre o protótipo (2026-11-12, noite, Windows)** — a referência é o *Production Manager* do Media
Composer (foto de uma ilha real; não guardada no repo: é tela de terceiro, com marca d'água e IP):
- A árvore de pastas à esquerda **fica como estava**.
- O conteúdo à direita é **CLARO**, com linhas ímpares e pares em cores um pouco diferentes.
- Colunas, nesta ordem: **status** (a bolinha da lista de mídias do De Lá Pra Cá: verde encontrada, âmbar a conferir,
  vermelho sem mídia; anel = item sem arquivo próprio; MINIMALISTA: 8 px, cor chapada e suave, sem sombra) · **miniatura** · **ícone do tipo** · **nome** · **TC de início** ·
  **duração** · **codec**. ⛔ Saem as colunas Avid / Trab. / Orig. e a legenda "nesta máquina / só em outra / não tem".
  ⇒ isto SUBSTITUI a resposta 1 acima.
- Linhas NEUTRAS (branco e cinza claro, sem tom quente). Colunas REDIMENSIONÁVEIS pela borda do título; DUPLO CLIQUE no
  título ordena por ela (outro duplo clique inverte; status do mais grave ao item; duração pelo tempo). ⚠️ Lido como
  "ordenar" o pedido de "organizar a hierarquia" — confirmado? (perguntado no comentário do protótipo).
- ⭐ REGRA do app inteiro (autor): toda parte CLARA é branco + cinza claro NEUTROS, sem tom quente. O "marrom" que ele
  viu vinha das miniaturas de mentira (bege/terracota), não das superfícies (já eram cinza puro, medido por CDP).
- O detalhe mostra "CAMINHOS CONHECIDOS": só a lista de caminhos da mídia, sem a máquina e sem a forma (o registro guarda
  as duas coisas; a tela não mostra).
  É uma TABELA com linhas alternadas; DUPLO CLIQUE num caminho abre a pasta com o arquivo marcado (Windows
  `explorer /select,`, macOS `open -R`; matriz, linha nova `pendente`). ⬜ Caminho de OUTRA máquina: traduzir pelo rótulo
  do volume (`referencias.onde`); disco não montado → dizer, não abrir.
- O detalhe é de DUAS colunas no mesmo topo: à esquerda os metadados da mídia (nome, tipo, codec, TC, duração, status,
  mandado por, como), à direita os caminhos conhecidos. O botão da árvore diz só "+ Nova pasta".
- ⭐ **v3: a identidade do MSync** (`9 ARQUIVADOS/MSYNC`, a pedido do autor): a JANELA INTEIRA clara (barra lateral
  #f5f5f5, área branca), linhas finas, rótulo de seção em versalete, status em pílula; cinzas do MSync NEUTRALIZADOS
  (eram levemente quentes). O casting que restava eram superfícies tingidas: a seleção (verde-água) e a faixa (lilás);
  agora são cinza. Varredura por CDP: cor só em bolinha, etiqueta de origem e pílula.
  ⇒ **Ajuste do autor (mesmo dia): a MOLDURA volta ao escuro do Ciclo Assist** — barra de título, barra do projeto e
  árvore de pastas (a pasta aberta em verde-água cheio); o MSync vale para o CONTEÚDO (lista, detalhe, menus, gaveta).
- A janela tem o RODAPÉ do app (`app/ui/rodape.*`): "Idealizado por Lohan Costa, edt." no centro e a versão à direita.
- ⭐⭐ **A PASTA VIRTUAL** (autor, o recurso do DaVinci Resolve): Ctrl/Cmd soma ou tira pastas na árvore, Shift pega o
  intervalo (na ordem da árvore, a partir da última clicada); a lista mostra TUDO junto, como uma pasta só, cada linha
  dizendo de que pasta veio (e o detalhe ganha "Pasta"). Ex.: as Câmeras e o Som direto de uma diária lado a lado.
  **Regras respondidas pelo autor (12/11):** (1) pode ficar SEM pasta selecionada: aí nada é mostrado; (2) "+ Nova pasta"
  nasce DENTRO da pasta selecionada e fica DESATIVADO com várias (ou nenhuma); (3) soltar um arrasto na lista com várias
  pastas NÃO adivinha o destino, pede uma pasta da árvore; (4) a pasta-mãe mostra só o que está DIRETO nela, como a bin
  do Resolve (não as subpastas).
- ⛔ **"Anexar formato" sai da tela**: o conceito tem de ser mais bem pensado (a resposta 3 fica suspensa). O registro (C1)
  continua guardando as formas; o que muda é como o editor as vê e as liga.
- O painel de DETALHE, a cabeça da lista e a faixa do envio também são claros (comentários do autor no protótipo); só a árvore e a barra do projeto ficam escuras. Protótipo v2 publicado no mesmo endereço. ⬜ Repensar com o autor: as formas e o "anexar"; de onde vêm miniatura e
  codec (miniatura: o cache de quadros quando houver; codec: a sondagem do acervo).

**Fora da C2:** trazer/levar timeline e puxar mídia (C3/C4).

### C2 — andamento

- ✅ (2026-11-13, Mac) **Parte 1: a janela de verdade.** Botão "Carta Aberta" na linha de baixo da barra de status (abaixo
  de "Fluxos e Agentes") → `POST /app/carta` → `--carta-aberta` → `app/src-tauri/src/carta.rs` (o formato da
  `oficina.rs`) → página `/carta` (`painel/carta.{html,css,js}`, o CSS veio do protótipo v3.4). Rotas novas em
  `servico/rotas_carta.py`: `/carta/arvore` (com `abrindo`, roda a quarentena e a DIZ), `/carta/conteudo` (a pasta
  virtual: várias pastas, só o direto de cada), `/carta/pasta` (nova pasta conferida dentro da raiz), `/carta/revelar`
  (só caminho que o DIÁRIO conhece; `open -R` / `explorer /select,`). A leitura em `carta/vista.py`: status (ok = alguma
  forma existe NESTA máquina; err = nenhuma; anel = item), TC, duração, codec (ffprobe do primeiro arquivo que existe,
  na memória; o som OP-Atom conta os canais pelos arquivos), caminho de outra máquina traduzido pelo rótulo do volume.
  Testes em `tests/test_carta.py` (+5); suíte Mac **1979/38**. Visto na tela com o projeto `CARTA ABERTA ITENS`.
- ⭐ **Decisão: puxar uma LINHA para uma pasta (mover) NÃO usa o arrasto HTML**, e sim o movimento do mouse dentro da
  página. Assim o gesto nunca passa pelo alvo do sistema que o `arrasto_mac`/`arrasto_win` registram para o NLE, e a
  medição "arrasto interno × alvo do NLE" deixa de ser necessária (o risco some pelo desenho, não por medida).
- O arrasto do NLE chega à janela: `arrasto_mac::instalar_na_janela` e `arrasto_win::instalar_na_janela` (o destino é a
  webview da Carta, função `cartaArrasto`, sem o desconto do rodapé). Soltar sobre uma pasta da árvore manda para ELA;
  na lista, para a pasta aberta; com várias pastas na vista, pede uma pasta da árvore. A conta vai na faixa.
- ✅ (2026-11-13, PILOTADO no Mac) no projeto `9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-13 CARTA JANELA C2`: trocar de
  projeto pelo menu; "+ Nova pasta" (`Diarias`, `Diarias/D01`); clicar linha → detalhe; duplo clique no caminho → Finder
  com o `.mov` marcado; o `G01_CAM1` arrastado da bin do Premiere (`G01 ARRASTO MAC v02.prproj`) e solto sobre a `D01`
  da árvore → `D01/G01_CAM1_T01_MOV-PRORES.ref.json`, faixa "1 nova". Consertos achados no caminho: a posição do soltar
  vinha +28 (a barra de título; medida no NSWindow), a pasta inicial não aparecia marcada (e "+ Nova pasta" ficava
  desativado).
- ✅ **Pedidos do autor (13/11):** Ctrl/Cmd+A seleciona TUDO do painel clicado por último (árvore → todas as pastas, a
  pasta virtual; lista → todas as linhas). ⛔ No Mac o Cmd+A não chega como tecla (o menu Edit › Select All o pega):
  tratado pelo `selectstart`; a página não seleciona texto (só o detalhe). A linha selecionada é **verde-água fraco**
  (`#ddf0ed`), não cinza (se confundia com a linha par) — mais apagado que a pasta aberta da árvore.
- ⬜ Falta pilotado no Mac: soltar da bin do **MC** (o MC estava fechado).

### C2 parte 2 — decisões do autor (2026-11-13)

A régua é a **bin do Avid**: o que a lista mostra é a vitrine; por baixo, a pasta carrega OCULTO tudo o que os itens dela
precisam para serem recriados (o fecho oculto da `.avb`, `user_placed=False`).

- **Remover** (o nome é "remover", nunca "tirar"): só some da VISTA da Carta. Nenhum arquivo do disco é tocado, e o
  item continua sendo usado por quem o usa (timeline, subclipe, multicâmera) — com "Mostrar clipes referenciados"
  ligado, ele volta a aparecer. Removido e sem ninguém que o referencie = inacessível até ser mandado de novo (mandar a
  mesma mídia outra vez o traz de volta). ⇒ substitui o "tirar = Quarentena" da resposta 4 (12/11).
- **Mover:** organização interna (referências, itens e pastas entre pastas); a mídia no disco nunca. Uma linha revelada
  pelo interruptor pode ser movida: passa a ser visível na pasta nova e CONTINUA aparecendo na pasta do item que a
  referencia enquanto o interruptor estiver ligado (quem decide o que se lista ali é o item).
- **Renomear:** pastas sim; timelines sim (quando a Carta as levar, C3/C4); clipe, subclipe e multicâmera NÃO (confunde).
- **Mostrar clipes referenciados** (o "Show Reference Clips" do Set Bin Display): interruptor numa linha NOVA acima do
  cabeçalho da lista (onde depois entram busca e filtro). Ligado, todo subclipe/sincronizado/multicâmera/timeline da
  pasta revela o que o compõe, como linhas da lista.
- **Botão direito › Selecionar ›** Tudo · Nenhum · Inverter · Sem mídia nesta máquina · **Referenciados** (o "Select
  Relatives": marca, entre as linhas visíveis, o que compõe o item — só o PRIMEIRO nível: subclipe → vídeo e som;
  multicâmera → o que compõe cada ângulo; timeline → clipes, subclipes e multicâmeras dela) · **Quem usa** (o inverso).
- ⛔⛔ **Guardar TUDO, nada simplificado** (autor): uma multicâmera do Premiere feita de um nest que contém um merged
  clip é guardada assim, camada por camada; adaptar é tarefa da ENTREGA, conforme o destino (no Avid o nest vira
  collapse). ⇒ o registro de itens muda: cada camada vira um item próprio, a multicâmera aponta itens OU mídias, e a
  estrutura nativa do NLE de origem vai junto. Hoje `itens.py` troca o que compõe a multicâmera pelos masters — isso
  perde camadas e tem de mudar.
- **Respostas do autor (13/11):** renomear pasta pode; o que vem só por causa de um item entra OCULTO (como o Avid);
  as multicams já registradas ficam como estão (a camada vale daqui para a frente); "Referenciados" só o 1º nível;
  Selecionar com Tudo · Nenhum · Inverter · Sem mídia · Referenciados · Quem usa. ⭐ **Nomes unificados** (a Carta
  unifica; na entrega cada programa recebe o seu): `subclipe (A\V)` (o `.sync` do Avid / merged do Premiere),
  `subclipe (V)`, `subclipe (A)`, `multicam` (também o group clip do Avid), `nest`.

### C2 parte 2 — andamento (2026-11-13, Mac)

- ✅ **A área oculta** (`.carta/ocultas/`, `carta/vitrine.py`): remover leva para lá (nada do disco é tocado); mover traz
  de volta para uma pasta; mandar de novo traz de volta (`Conta.voltaram`); o que vem só por um item entra oculto
  (`anexar.mandar_*(visivel=False)`, as rotas do Avid e do Premiere). Pastas: renomear, mover, remover (o que ela mostra
  vai para o oculto; a pasta, para a Quarentena). Rotas `/carta/remover`, `/carta/mover`, `/carta/pasta/{renomear,mover,remover}`.
- ✅ **As camadas** (`itens.py`): a parte de um item pode ser `{"item": id}`; tipo novo `sequencia` (nest); o leitor do
  `.prproj` reconhece o clipe que aponta uma SEQUÊNCIA (antes era pulado calado) e cada camada vira um item (oculto);
  o que não se reconhece recusa o item DIZENDO. ⚠️ **Sem material real ainda:** nenhum `.prproj` de teste tem multicam
  feita de nest/merged — o caminho está testado só com item sintético. ⛔ **Avid:** group clip feito de subclipes/sync
  é RECUSADO com a frase (nunca medido; o G01 é agrupado dos masters). Precisa de um group clip assim, feito à mão.
- ✅ **A tela, PILOTADA no Mac** (cópia `9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-13 CARTA PARTE 2`): o interruptor
  "Mostrar clipes referenciados" na linha nova acima do cabeçalho; botão direito › Selecionar › Referenciados na multicam
  (marcou CAM1/2/3 + som), › Quem usa no CAM2 (marcou a multicam e o sync); Remover da vista (o CAM1 some, vai para
  `.carta/ocultas/`, volta revelado "oculta" com o interruptor); puxar a linha revelada para `Diarias` (passa a morar
  lá e continua revelada em `Cenas`, "mora em Diarias"); renomear a pasta pelo botão direito. Suíte **1984/38**.
- ✅ **A lista "A decidir"** (`carta/decidir.py`, rotas `/carta/decidir` e `/carta/decidir/responder`): o empate e o
  homônimo do "mandar" viram um fato `pendente` no diário (um por arquivo), e a resposta um fato `resolvido` — "é a
  mesma (que X)" liga o arquivo à referência X; "é outra" cria uma referência distinta. Só responde quem alcança o
  arquivo (a forma é desta máquina). Na tela: o botão "A decidir N" na barra do projeto, a gaveta com os casos (a
  medida, o arquivo que chegou, quem e quando), a bolinha âmbar e a pílula nas referências envolvidas. PILOTADO com um
  homônimo fabricado do `G01_CAM2` (barras, mesmo nome/TC/duração, imagem +0,047): "É outra" → duas referências.
  ⚠️ Os empates do ANEXAR (que saiu da tela) continuam só na conta.
- ✅ **A miniatura** (`carta/miniatura.py`, `GET /carta/miniatura?raiz&id`): vídeo = o quadro do meio pelo extrator do
  produto (`frames.extrair_varios`, que sabe do OP-Atom MPEG-2 e do RAW); som = a forma de onda preta sobre azul (o
  Production Manager), `scale=cbrt` (linear, o som baixo do lab saía uma linha reta); item = a mídia de baixo no ponto
  onde ele começa (o `G01_CAM3.sub.01` mostra o quadro 200, conferido pelo número escrito no quadro). Cache na pasta de
  DADOS desta máquina (nunca no projeto em rede), duas gerações por vez. Visto na janela, 7 de 7 com miniatura.
- ✅ **Pedidos do autor (13/11, tarde):** (1) a releitura de ~10 s fazia as miniaturas PISCAREM (a lista era redesenhada
  inteira): agora árvore, lista e "A decidir" só se redesenham quando o que veio do serviço MUDOU; (2) a coluna TC
  início mostra o TC do PRÓPRIO item (subclipe = TC do clipe + entrada; sync = o da imagem + o início dela; multicam =
  o da fonte que começa no quadro 0 dela; nest: vazio, o `.prproj` não foi lido para isso); (3) Duração em
  hh:mm:ss:ff; (4) coluna FPS depois da Duração (o som não tem taxa própria: "—", e a duração dele conta na taxa do
  PROJETO). `vista._relogio`, `tc_mais` (drop-frame com `;`), `duracao_tc`. Conferido: `G01_CAM3.sub.01` =
  `10:00:16:08`, o TC escrito no quadro 200 da miniatura.
- ✅ **Pedidos do autor (13/11, fim da tarde):** (1) sem o "atualizado há N s" (a releitura continua, calada); (2) FPS
  do SOM = a amostragem ("48 kHz", da mesma sondagem do codec); (3) detalhe: "Mandado por" → **Origem**; "Como" →
  **Itens referenciados** (subclipe, multicam, nest e OP-Atom): lista simples com ícone vídeo/áudio, vídeo antes, ordem
  alfabética; o clique leva ao item — na mesma pasta se ele está à vista (inclusive revelado), senão na pasta onde
  mora; removido da vista sem o interruptor = dito; (4) **Caminhos conhecidos por ABA**: subclipe/multicam = uma aba
  por mídia de baixo; ⛔ timeline/nest sem aba; OP-Atom = UMA linha ("+N arquivos da mesma mídia") e o duplo clique
  marca TODOS no Finder (`osascript` reveal+select, matriz); aba no OP-Atom só com arquivos em pastas diferentes.
  PILOTADO: a multicam com 4 abas, o clique no CAM1 levou a `Diarias D01`, o Finder com os 3 arquivos marcados.
- ⬜ Falta: material real das camadas (Premiere: multicam de nest com merged; Avid: group clip de sync subclipes);
  puxar uma PASTA para outra pilotado (testado só por teste de código); a lista "A decidir"; a miniatura. ⬜ **Windows:** o `arrasto_win` mudou e NÃO foi compilado (o Mac não tem o alvo); compilar e provar lá.
- ⬜ Parte 2: mover/renomear/tirar (tirar = Quarentena), a lista "A decidir" guardada no diário, a miniatura (cache de
  quadros). A coluna de miniatura ficou FORA até ter quadro de verdade (o protótipo desenhava de mentira).

## 6. Material de teste

- **OP-Atom:** `Avid MediaFiles` do SSD (protegido: só leitura), projeto `PRODUCAO-A_CURTA`.
- **Versão de trabalho:** `MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/MIDIAS/CONVERTIDOS/D01…D04`: 118 `.mp4`, 196
  `.wav`/`.WAV` e 15 `.mxf` (MP4 confirmado pelo autor).
- **Subclipes sincronizados:** as bins da PRODUCAO-A no MC (D02 subclipada pelo Órbita, `C07 FALAS`).
- **Original BRAW:** o NAS (desligado hoje) ou a cópia em HD. Não é preciso para C0 a C4, porque nenhum gesto da v1
  abre o original; só se registra o caminho.

## 7. Perguntas ao autor

1. ✅ Respondida (2026-11-12): o par de referência é o `GRUPO-MULTCAM` (MC, `PRODUCAO-A-ENSAIO/EDICAO.avb`, feito à mão
   em 28/06) e a multicâmera das MESMAS fontes feita no Premiere 26.0.2 (Mac) por ponto de entrada, em
   `MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/SAIDAS/CARTA ABERTA/GRUPO-MULTCAM PREMIERE v01.prproj`. Fontes: as do
   FLATFILE-MULTCAM (`CAM A.mxf`, `CAM B.mxf`, `SOM-DIRETO.wav`). C0(f) LEITURA feita (banco `avb/sincronizacao-e-subclipes.md`
   §5); ESCRITA feita em 2026-11-12 (`spikes/carta_aberta_group_clip.py`: forma igual à do grupo à mão, abre e carrega no MC
   2025.12) e PROVADA na imagem com mídia do laboratório (G01: 3 câmeras 23,976, OP-Atom pelo Resolve; os 3 ângulos no
   mesmo TC 10:00:21:14, banco §5) — e o sentido Avid → Premiere FEITO em 2026-11-12 (`spikes/carta_aberta_para_premiere.py`): grupo → multicâmera com
   as fontes inteiras, `.sync.01` → merged, subclipe → `createSubClip`; os três conferidos na imagem (banco `prproj/escrita.md`
   §11f). ✅ C0(g) respondida: importar um `.prproj` nosso DUPLICA a mídia; o ENXERTO numa cópia do projeto do editor
   (`spikes/carta_aberta_enxerto.py`, banco §11g) não duplica — o "Puxar" no Premiere salva o projeto dele antes. Falta: o sentido Premiere → Avid, o TC do merged e o som dos ângulos. ⛔ Achado para a tradução: por ponto de entrada o Premiere corta as cabeças; o Avid guarda as
   fontes inteiras com o deslocamento — traduzir sempre com as fontes inteiras (banco `premiere-cep/subclipe-e-merged-clip.md`).
2. ✅ C0(d) no Mac (2026-11-12): a mídia sai da bin para a janela do app pelo ARRASTO nos dois NLEs. MC: o MobID no XML do
   arrasto (provado em 07/11 na aba Preparar). Premiere: o `arrasto_mac.rs` registra `public.data` (os tipos `dyn.` dele a
   conformam, sem PID), avisa `premiere`/`premiere_item` e a página lê a SELEÇÃO pela ponte — 1 clipe, 2 clipes, a
   multicâmera e o WAV viraram etiquetas na Assistir; a sequência ainda traz o XML com o `ObjectUID` (banco
   `premiere-cep/arrastar-e-selecao.md` §6f). ⇒ a janela da Carta Aberta (C2) recebe pelo mesmo `arrasto_mac`/`arrasto_win`:
   basta ela expor a função de arrasto, como os módulos. ⬜ Windows já tinha os dois (21/10).
3. ✅ C0(b) (2026-11-12, MC 25.12 Mac): sim — bin NOVA escrita pelo pyavb com masters de outro projeto (+ o fecho oculto)
   abre ONLINE no projeto B, vídeo e som gerenciados (`spikes/carta_aberta_bin_entre_projetos.py`; banco
   `protocolos/avb/escrita.md`, regra do automatch). ⇒ o "Puxar" no Avid pode entregar os masters numa bin nossa sem relink;
   resta a (a), a MESMA pergunta com a `Avid MediaFiles` vista pela REDE.
4. ✅ Som dos ângulos no MC (2026-11-12): cada ângulo do grupo escrito por nós toca o som da PRÓPRIA câmera, sincronizado
   ao quadro (export medido por tom piloto + correlação, `spikes/carta_aberta_som_dos_angulos.py`); o som pode apontar o
   som direto com a imagem num ângulo — a tradução Premiere → Avid passou a fazer assim. ⛔ `ExportFile` de group clip não
   grava nada: exporta-se a sequência. ⬜ o som direto do grupo traduzido está 39 s fora (o WAV do lab, item já aberto).
5. ✅ O merged lido do `.prproj` (2026-11-12): arquivo, entrada e canal de cada trilha, nas duas formas de canal
   (`spikes/carta_aberta_merged_do_prproj.py`) — o `carta_aberta_para_avid.py` pode trocar o `--som` por ele.
6. ✅ O WAV do gravador real (2026-11-12): `time_reference` = TEMPO REAL (PRODUCAO-A C4 P1-T002 → 11:42:00:00 redondo a
   23,976, iXML `TIMECODE_RATE 24000/1001`); o Premiere e o MC leem assim. Os 36–39 s do G01 são do gerador do laboratório
   (`lab/multicam.py`), não da tradução — conserto proposto à sessão do laboratório (banco `subclipe-e-merged-clip.md`).

## O desafio da timeline real (autor, 2026-11-13): MC → Carta → Premiere, com a montagem da PRODUCAO-A

Pedido: abrir no MC a timeline real de montagem, trazê-la para a Carta e levá-la ao Premiere, apontando para as OP-Atom.
A timeline: `PRODA_CORTE.02.Exported.01` (`EMISSORA-APRS/PRODUCAO-A/PRODUCAO-A Bin.avb`), 26,5 min a 24 fps, V1–V3 e
A1–A16. Feita SÓ de masters (89 clipes de imagem, 552 de som, 73 masters distintos; nenhum subclipe nem grupo), com
143 transições, 180 `PanVolumeEffect`, 33 `Selector`, 9 `INT_EFF_SPATIAL_ADAPTER`, 7 correções de cor, 2 estabilizações,
4 `MotionEffect` (velocidade) e 1 AudioSuite.

O que o fluxo revelou (medido sem o MC, pelo mesmo código da rota `/carta/mandar`; projeto
`9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-13 PRODUCAO-A TIMELINE`):
- ⛔ **O MC 25.12 do Mac não abre** (3 de 3, 14:50–14:53): `abort()` na partida do Titler+ (`DekoLibrary`
  `PRESETS_DOC::GetLookInit` → `k_double` → `std::terminate`), antes de qualquer projeto. Igual com `-AppleLocale en_US`.
  Nada de Avid mudado em disco desde 12/11, quando abriu. Hipótese: a licença de avaliação (vencia em ~4 dias em 12/11).
- ✅ **Os masters:** 71 de 73 com a OP-Atom achada na `Avid MediaFiles` do SSD (0,4 s); entraram como 71 referências
  `ok` (36 vídeo, 35 som) em 2 s, codec/TC/duração certos. Faltam 2, que não são OP-Atom (um `.aif` de ambiente e
  `PRODUCAO-A - 05-04 C11 P1-T002.WAV`, AMA): sem forma OP-Atom, a Carta não os registra — e só DIZ a contagem.
- ⛔ **A sequência não entra:** `itens.do_avid` só lê subclipe e grupo; a espécie `sequencia` não vira item NEM vai para
  os recusados. Com o MC fechado a resposta diz "abra o projeto no Media Composer para mandar subclipes e grupos"
  (errado para uma sequência) e levou **33 s**.
- ⛔ **A entrega ao Premiere não existe** (é a C3): nem a Carta nem o Conformar escrevem uma timeline num `.prproj`
  (o Conformar só COPIA um `.prproj` relinkado; o seletor dele diz "em breve"). O Conformar já LÊ a timeline do Avid
  com os efeitos (`modulos/conformar/motor/carta_aberta`, o formato antigo).

### O desafio — construído (2026-11-13, tarde; o autor: "pode construir as duas")

- ✅ **A sequência do Avid vira item da Carta** (`carta/timeline.py`, ligado em `itens.do_avid`): `tipo: sequencia` com
  `timeline: true`, lida pelo leitor do Conformar (`avb_bin/segmentos.py`, nada de segundo leitor). Cada clipe aponta a
  referência do master e leva canal, `ganho_db`, velocidade, reformat, efeitos (como vieram) e `desligado`; as
  transições ficam na trilha. Na PRODA_CORTE: **1,8 s**, 19 trilhas, 877 clipes (= a conta do Conformar), 143
  transições; 88 masters com OP-Atom entraram ocultos, **30 OFFLINE** (som AMA cuja mídia não está nesta máquina —
  `ProdABckUp`, a pasta antiga `_DLPCDPL EXEMPLOS`), ditos um a um. O "anexar formato" apontando `MIDIAS/SFX` e
  `TRILHAS` da PRODUCAO-A religou 10 dos 30; 20 não casaram pela régua (nome/duração da bin ≠ do arquivo — a ver).
- ✅ A frase errada saiu ("abra o projeto no MC: subclipes, grupos e sequências são lidos da bin"); `_mandar_do_avid`
  ganhou `mandar_itens_da_bin` (o passo offline). ⚠️ Os 33 s com o MC fechado não foram investigados.
- ⚠️ O clipe que vem de SUBCLIPE é achatado no master com `via` (o leitor do Conformar resolve até o master). Na
  PRODA_CORTE são só os 33 clipes desligados (Selector). Guardar a camada do subclipe fica para quando houver caso vivo.
- ⛔⛔ **A `PRODA_CORTE.02.Exported.01` era a timeline ERRADA** (autor, 2026-11-14): exportada, perdeu os subclipes. A
  ORIGINAL é `PRODA_CORTE.00.2`, na bin `MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/PROJETO/PRODUCAO-A/01_SEQUENCIAS/
  01_EDIT/03_OC_EDIT VALENDO.avb` (toda online na Avid MediaFiles). Medido nela: **106/108 segmentos de imagem e
  598/725 de som apontam SUBCLIPE**; 44 subclipes (`04-02-01`…), **35 sincronizados** (imagem da câmera, som do
  gravador → merged no Premiere), 6 imagem+som do mesmo master, 3 só imagem. ⇒ O próximo bloco: o leitor da timeline
  guarda o ITEM (subclipe/sincronizado) e a entrega escreve o merged no `.prproj` com a timeline apontando para ele.
  ⬜ Depois: media manager do curta (uma cópia da Avid MediaFiles só com o que a montagem usa — pedido do autor).
- ✅ Na `Exported` (enquanto isso, 2026-11-14): som com canal e ganho (§11i), transições (§11j), velocidade,
  conformação de taxa e desligados (§11k) — v08: 798/798 clipes e 105/105 transições lidos pelo Premiere.
- ✅ **A ORIGINAL no Premiere (2026-11-14, tarde)** — a camada do subclipe guardada na Carta (36 `sincronizado` + 8
  `recorte`, ocultos; os canais do subclipe no item), e na entrega: subclipe sincronizado → MERGED aparado (o molde do
  autor, feito pela timeline), recorte → SUBCLIPE do Premiere com o nome do Avid, o vínculo imagem-som por TRECHO. v11:
  848/848, 157/157, 36 merged, 8 subclipes, 163 vínculos — conferida pelo autor, áudio inclusive (banco §11l).

### LEVAR para o NLE: o botão "Importar para X" (decisões do autor, 2026-11-14)

- **Um botão "Importar para X"** (e no botão direito) — X = o NLE aberto e conectado ("Importar para o Premiere",
  "… para o Media Composer", "… para o Resolve"), sem escolher o programa: o Ciclo Assist já sabe qual é. ⛔ Nunca
  "Importar" sozinho (autor: parece que se traz algo para DENTRO do app, não para o NLE de destino). Leva a SELEÇÃO da Carta (mídias, merged/subclipes/grupos, timelines) para o projeto aberto nele.
- **Destino: a bin SELECIONADA, ou a aberta por último** no NLE (no Premiere, candidata `app.project.getInsertionBin()` —
  ⬜ medir que ela devolve isso).
- **Importa direto**, sem resumo nem confirmação; **só aparece mensagem em caso de erro** (o que ficou de fora vai no
  registro, não num diálogo).
- O motor é o da entrega por enxerto (§11g–§11l): importar a mídia pelo próprio NLE, salvar o projeto do editor
  (decisão de 12/11), escrever numa CÓPIA dele, e trazer com `importSequences` — ⬜ medir que o `importSequences` de uma
  sequência que usa merged/subclipe traz os merged/subclipes junto, sem duplicar a mídia.
- **Depois: o arrasto.** Soltar em QUALQUER lugar de um NLE dispara o mesmo "Importar para X" (quem age é o nosso app, no
  soltar: a janela sob o cursor diz o programa; o arrasto NÃO leva arquivo, senão o NLE importaria sozinho e seriam
  duas importações). Soltar no nosso app: o chat anexa, o Sincronizar sincroniza, o Conformar conforma. ⬜ Medir nas duas
  plataformas: o "soltou" fora da janela chega à página? a janela sob o cursor (matriz de plataforma); o retorno visual
  com o cursor fora da nossa janela.
- ⭐ Aparte do banco (matriz, Windows): o Premiere executa "Mesclar clipes" pelo ID do menu (11591) — lá o merged pode
  ser feito pelo PRÓPRIO Premiere, com o nosso escrito como reserva. Mac não medido.
- ✅ **O motor do botão, de ponta a ponta** (2026-11-14, Mac; `carta/importar_premiere.py`, `carta/moldes_prproj.py`,
  rota `/carta/premiere/importar`; banco `prproj/escrita.md` §11n). Decisão do autor: caminho 1 + "o que o projeto do
  editor já tem serve de molde". ~20 s para a PRODA_CORTE.00.2: a mídia que falta pelo Premiere + salvar o do editor →
  cópia de trabalho em `.carta/premiere/` → o que falta de molde o Premiere monta na cópia aberta AO LADO → o editor de
  volta à frente, a cópia fechada → a timeline escrita numa 2ª cópia → `importSequences` → tudo o que entrou vai para a
  bin de destino (lida antes). Num projeto novo só com a mídia: 848/848 iguais à v11, 157 transições, 8 subclipes; num
  projeto com merged (o do autor): 36 merged. ⛔ Sem merged no projeto do editor, os sincronizados vão pela mídia
  nativa (dito) — o merged não tem via de API no Mac.
  ✅ **A calibragem** (opção A do autor, 2026-11-14): sem merged no projeto do editor, o projeto-modelo do app
  (`carta/moldes/modelo.prproj`, merged de 16 canais sobre mídia sintética) entra na CÓPIA, calado: 36 merged num
  projeto só com a mídia. Feito no 26.0.2 — ⬜ refazer no 25.6.5 e no Windows.
  ✅ **O botão na janela** (2026-11-14, pilotado): "Importar para X" na linha de ferramentas e no botão direito, X do
  `/conexao`; UMA timeline por vez; só o erro aparece; o relatório no diário (fato `importado`). O quadro da sequência
  vem do projeto do Avid (gravado na timeline ao mandar).
  ⬜ Falta: mídia/subclipe/multicam pelo mesmo botão; o quadro (1920×1080) vem hoje do pedido — tirar do formato do
  projeto do Avid; importar a mesma timeline de novo DUPLICA os merged (decidir com o autor: reaproveitar os que já
  estão lá?); o merged sem molde (Windows: menu nativo 11591; Mac: um molde levado pelo próprio Premiere?); Windows.
- ✅ Na janela (2026-11-14): o detalhe é recolhível (aba "Mostrar / Ocultar detalhes" no meio e no topo; estado lembrado).
- ✅/⛔ **A entrega ao Premiere** (`carta/entrega_premiere.py`, rota `/carta/entregar`, `cicloImportarTimeline` no
  `host.jsx`): XML de timeline (FCP7) apontando a OP-Atom (padrão; senão original/trabalho, contado), com o relatório
  do que fica de fora (cor, estabilização, reformat, título, offline). Pedaços ENTRAM no 26.0.2 Mac (1 clipe; as 16
  trilhas de som com fades e ganho; a V3 com dissolves; velocidade constante). **A V1 de vídeo (95 clipes) não entrou,
  e na 5ª tentativa travou e derrubou o Premiere** (modal "Importar arquivos" parado; banco `api-extendscript.md`,
  2026-11-13). Causa não achada. O projeto G01 do teste perdeu só os imports de teste (não foi salvo).
- **Próximo (decidir com o autor):** (a) bissectar a V1 com o Premiere À FRENTE, um clipe por vez, para achar o
  arquivo/clipe que trava; (b) ou trocar o XML pelo `.prproj` escrito (o enxerto, banco `prproj/escrita.md` §11g),
  que não passa pelo importador de XML; (c) entregar num `.prproj` NOVO e versionado (`cicloAbrirProjeto`), nunca no
  projeto aberto do editor.
