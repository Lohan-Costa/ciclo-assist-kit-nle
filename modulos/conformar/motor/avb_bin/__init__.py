"""Leitura e edição da timeline dentro de uma bin `.avb` do Media Composer.

⚠️⚠️ **O pacote NÃO pode se chamar `avb`** — esse é o nome do **pyavb**, e um pacote local
com esse nome o sombreia: `from avb.core import AVBObject` dentro de
`motor/avb_export/translate.py` passa a resolver para cá e o `avb_export` inteiro deixa de
importar. Descoberto ao criar este módulo (2026-08-16); daí `avb_bin`.

A rota `.avb` do relink: em vez de pedir um AAF ao editor (`ExportFile` + preset) e
devolvê-lo por `ImportFile`, lê-se e edita-se a **própria bin que o Media Composer
escreveu**. A composição continua sendo a dele — só as referências de MobID mudam —, e por
isso os efeitos sobrevivem pelo mesmo motivo que na rota AAF: não passamos perto deles.

Ver [ADR 0013](../../docs/adr/0013-a-rota-avb-volta-a-existir.md).

    percurso.py   o percurso da timeline (UM lugar só — ver ADR 0006)
    masters.py    os masters em uso, nos MESMOS objetos `Master` da rota AAF
    denest.py     achatar subclipes (requisito do relink, não só do reimport)
    remap.py      repontar para os masters novos

⚠️ Três regras que valem para qualquer escrita de `.avb`, cada uma um fracasso antes de
virar regra (todas medidas em 2026-08-16, ver o ADR):

1. **`Bin.uid` novo em toda gravação** — senão o MC recusa com `FILE_OPEN_FAILURE`
   enquanto houver uma bin de mesmo UID aberta.
2. **Masters e timeline na MESMA bin** — num master AMA o caminho do arquivo mora na bin.
3. **Nome de arquivo novo a cada entrega** — `OpenBin` numa bin já aberta devolve
   `Completed` e **não relê o disco**.
"""

import avb_fiel  # noqa: E402,F401 — antes de qualquer leitura: a string nula (0xFFFF) sobrevive à regravação (B005)
