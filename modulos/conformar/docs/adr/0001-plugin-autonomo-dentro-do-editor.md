# 0001 — O plugin roda DENTRO do Media Composer; o App é só o instalador

**Status:** ativa

**Contexto:** o predecessor (RELINKER) era um app externo que recebia uma timeline de um
lado e entregava do outro — imitando programaticamente, por engenharia reversa, o que o
Media Composer faz sozinho quando está aberto e dirigível.

**Decisão:** o produto passa a ser um **plugin do Panel SDK** que roda dentro do processo
do Media Composer, com o motor de relink embutido. Cada NLE (por enquanto só o MC) recebe
**painel + serviço próprios, autônomos** — o plugin funciona com o App fechado. O App
existe só para instalar (modelo Órbita) e para atender quem não tem o MC aberto.

**Por quê:** com o editor aberto e dirigível, não é preciso mais imitar comportamentos
decifrados por engenharia reversa — pede-se a ele que os execute. O ganho concreto é
**fidelidade de efeitos**: quem monta a timeline continua sendo o próprio Media Composer,
então Titler+, FrameFlex, timewarp e estabilizador sobrevivem por construção, sem que o
plugin escreva uma linha a respeito deles.

**Alternativas consideradas:** manter o App externo e melhorar a imitação — descartada,
porque a fidelidade de efeitos é estrutural (quem monta é o MC), não uma questão de
cobrir mais casos na reimplementação.

**Custo aceito:** ~50 MB de motor duplicado por NLE (o motor é um pacote só no
repositório; a duplicação é só de empacotamento). **Ganho:** um plugin nunca quebra por
causa de outro.

**Consequência:** a rota antiga do RELINKER (`avb_export`/`build_avb`, que reautora a
timeline e derruba alguns efeitos) não desaparece — vira o backend do App agnóstico, para
quem não tem o Media Composer (ver [ADR 0002](0002-relink-por-aaf-via-linkfile.md)).
