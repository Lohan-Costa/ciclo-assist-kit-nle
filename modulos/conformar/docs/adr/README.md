# Architecture Decision Records

Registros curtos das decisões não-óbvias do De Lá Pra Cá — o suficiente para quem for
ler ou modificar o código entender o "por quê", sem a narrativa completa de
tentativa-e-erro do desenvolvimento (essa fica nas notas privadas do mantenedor, em
`.dev/DECISIONS.md`).

Cada arquivo é curto de propósito: contexto, decisão, consequência. Se uma decisão
mudar, adicione um novo ADR referenciando o antigo — não edite o histórico.

- [0001 — O plugin roda DENTRO do Media Composer; o App é só o instalador](0001-plugin-autonomo-dentro-do-editor.md)
- [0002 — Relink por AAF via `LinkFile`, não reautoria por `.avb`](0002-relink-por-aaf-via-linkfile.md)
- [0003 — Matching por MASTER, não por segmento](0003-matching-por-master-nao-por-segmento.md)
- [0004 — Sem matcher visual no plugin; a confirmação é humana](0004-sem-matcher-visual-confirmacao-humana.md)
- [0005 — Nome exato normalizado decide; correspondência frouxa é sempre sugestão](0005-nome-normalizado-decide-frouxo-e-sugestao.md)
- [0006 — Achatar subclipes e group clips antes do `ImportFile`](0006-achatar-subclipes-antes-do-importfile.md)
- [0007 — O portão não usa token de arquivo; a defesa é `Origin`/`Sec-Fetch-Site`](0007-portao-sem-token-defesa-por-origem.md)
- [0008 — Uma sessão de trabalho por vez; progresso é lido, não empurrado](0008-uma-sessao-por-vez-progresso-lido-por-sse.md)
- [0009 — O preset de export AAF vem embarcado](0009-preset-de-export-embarcado.md)
- [0010 — Um canal gRPC por operação, nunca guardado](0010-um-canal-grpc-por-operacao.md)
- [0011 — Uma camada de plataforma, e degradação explícita por versão do MC](0011-uma-camada-de-plataforma-e-degradacao-por-versao.md)
- [0012 — A timeline entra por arrasto; o seletor de sequences vira o plano B](0012-a-timeline-entra-por-arrasto.md)
- [0013 — A rota `.avb` volta a existir: relink pela bin, sem AAF](0013-a-rota-avb-volta-a-existir.md)
- [0014 — Um banco de mídias por produção, chaveado por NOME](0014-banco-de-midias-compartilhado.md)
- [0015 — O export lê a bin; nunca chama `ExportFile`](0015-export-le-a-bin-nunca-chama-exportfile.md)
- [0016 — Magic Link: a timeline vai por uma pasta combinada, e o Resolve a puxa](0016-magic-link-pasta-combinada.md)
- [0017 — INSERT PARA COR/VFX: o botão Coletar lê a cópia do editor](0017-insert-pela-copia-do-editor.md)
- [0018 — Magic Link em canais: a edição no meio, um canal por setor](0018-magic-link-em-canais-por-setor.md)
- [0020 — No Resolve, o relink aos originais acontece ao importar](0020-relink-aos-originais-ao-importar.md)
