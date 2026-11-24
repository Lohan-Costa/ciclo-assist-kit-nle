# 0005 — Nome exato normalizado decide; correspondência frouxa é sempre sugestão

**Status:** ativa · Data: 2026-08-10

**Contexto:** medido num acervo real (AAF de produção × mídias no disco):
100/118 masters resolvidos (96,9% dos segmentos), e os 18 não resolvidos **não existem**
no acervo (conferido por busca direta) — ou seja, **100/118 é o teto real**, o matcher
achou tudo o que existia para achar. Dos 101 casamentos por nome, **100 foram exatos**;
o que produziu isso não foi busca frouxa (fuzzy), foi normalização: sufixos que o Avid
empilha (`.new.01`, `.sync`, `.cds`, `.copy`, `.sub`, `.grp`, `.exported`, contadores
`.NN`) caem, e separadores (`. _ - / \ ; :`) viram espaço — sem normalizar `;`, 29
trilhas ficavam offline (o Avid grava `17;25;16`, o AAF traz `17_25_16`).

**O achado que decidiu a política:** o único casamento frouxo do acervo era **falso
positivo** — `23_19_13 Cordas Trompa Oboé.wav` casando com `09;36;23 Cordas Trompa_02.wav`
(score 0,731; são músicas diferentes, os números do timecode divergem em silêncio). A
supressão de duplicatas pegou o erro **por sorte** — o arquivo já tinha dono mais forte.
Sem esse acaso, teria virado relink errado sem aviso. Saldo do frouxo neste acervo: zero
acertos, um erro.

**Decisão:** o casamento por nome exato normalizado decide sozinho. O casamento frouxo
nunca decide — vira `sugestao`, aparece no painel com o score, e espera um clique
humano.

**Consequência:** trava contra regressão em `tests/test_nomes.py` (28 casos: sufixos,
separadores, caixa, acento, os pares que não podem casar, o guard de tokens longos e a
normalização de UMID).
