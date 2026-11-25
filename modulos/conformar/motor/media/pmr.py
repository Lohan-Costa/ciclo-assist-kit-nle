"""O índice do MSM (`msmFMID.pmr`) — do MobID do MASTER aos arquivos dele.

⚠️ PORTE de `Promo Entrega/motor/benditofield/pmr.py` (2026-09-24). A única mudança é o
índice POR ARQUIVO (`Leitura.por_arquivo`): o registro LONG traz o MobID da ESSÊNCIA daquele
arquivo — medido no mesmo dia, 290/290 trilhas do curta que estavam no disco casaram com a
essência que a bin aponta (imagem → `X.mxf`, som 1 → `X_A01.mxf`, som 2 → `X_A02.mxf`).
É o que dá o arquivo EXATO de cada canal, como o Resolve liga ao importar o AAF.

⭐⭐ **A alternativa medida a varrer o acervo.** Nesta máquina, `Avid MediaFiles` tem
**1404 `.mxf`** por volume e um `ffprobe` por arquivo custa 40 ms — **~56 s** para achar
quatro clipes. Os `.pmr` respondem a mesma pergunta em **0,52 s**, sem abrir um `.mxf`
sequer: medido em 07/09/2026 contra a bin `PROMO ENTREGA Bin.avb`, 24 índices lidos, 358
masters, e **4 de 4** MobIDs dos cortes resolvidos.

Isto é PORTE, não invenção. O formato está em `bancodedadosnles/protocolos/msm/pmr-fmid.md`
e o módulo veio de `_ASSIST ANTERIOR/assist_anterior/clipes/pmr.py`, que já rodou dentro de um
painel do Media Composer (02/09/2026: 12 `.pmr` → 358 masters em 0,56 s, 28/28 UMIDs de
uma bin real). O que importa do formato:

    cabeçalho: u32 magic(0x7a9) + u32 ? + u32 n_mídias
    depois, um PAR por mídia:
      LONG   cabeça de 32 bytes + u16 tam + nome do arquivo + u16 tam + nome do tape
      SHORT  cabeça de 32 bytes + 4 bytes, sem strings

⛔⛔ **O par é a chave da leitura, e é onde o parser publicado no banco PARA.** O LONG
carrega o mob **daquele arquivo**; o SHORT logo em seguida carrega o mob do **MASTER** —
o mesmo para todos os canais do clipe. O `tools/pmr_read.py` do banco devolve só os LONG,
então responde *"que arquivos existem"* e não *"de quem são"*. É o SHORT que interessa.
⚠️ A página do banco avisa disso desde 22/08; o código de lá não acompanhou. Quem chega
pelo código e não pela prosa reimplementa a metade errada — já quase aconteceu duas vezes.

⚠️ E a cabeça de 32 bytes não é hex corrido: o grupo 5 é um `u32` little-endian e o
grupo 6 são **dois `u16`** little-endian. Ler o grupo 6 como `u32` foi o que fez a
primeira tentativa do banco (2026-07-08) concluir, errado, que os bytes não batiam.

## Três guardas que vêm do banco, e nenhuma é opcional

1. ⛔ **Varrer só `Avid MediaFiles/MXF` e `/UME`.** Uma pasta `MXF-<projeto>` é mídia que
   o editor pôs **offline de propósito** — renomear a pasta é como se guarda material de
   outro projeto no mesmo disco. Os MobIDs são os MESMOS nas duas cópias, então varrê-la
   "resolve" e entrega mídia que o Media Composer trata como inexistente. Aconteceu no
   Órbita: 50/50 masters resolvidos e uma timeline montada que **parecia certa**.
2. ⚠️ **Comparar o nome da pasta sem depender da caixa.** Há disco em produção com
   `Avid Mediafiles` (`f` minúsculo) enquanto a Avid documenta `Avid MediaFiles`.
3. ⛔ **O `.pmr` NÃO é fundação.** Em storage gerenciado de rede ele não fica na pasta de
   mídia — medido em produção na Emissora. E cada `.pmr` indexa **só a sua pasta**: um
   ausente produz resultado parcial e **silencioso**. Por isso `Leitura` devolve quantas
   pastas não tinham índice: quem chama decide se cai para a varredura dirigida.

⭐ Desenho do banco, adotado aqui: **o índice é guia, nunca regra.** Quem consome confirma
a identidade pelo conteúdo, então um índice velho ou apontando para arquivo que sumiu
piora a fila — não corrompe o resultado.
"""

from __future__ import annotations

import logging
import os
import struct
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("delapraca.media.pmr")

#: O nome do índice dentro de cada pasta numerada.
INDICE = "msmFMID.pmr"
#: ⛔ As ÚNICAS pastas a varrer. Ver a guarda 1 no cabeçalho.
PASTAS_DE_MIDIA = ("MXF", "UME")
#: A pasta que o Avid cria na raiz do volume. ⚠️ Comparada sem caixa (guarda 2).
RAIZ_DO_AVID = "avid mediafiles"

_MAGIC = 0x7A9
#: Um nome de arquivo maior que isto não é nome de arquivo — é desalinhamento.
_MAX_NOME = 260


@dataclass(frozen=True)
class Leitura:
    """O que a varredura do índice achou, e o que ela NÃO achou."""

    #: `{urn do master: [caminhos dos arquivos]}` — a URN na forma que o pyavb devolve.
    por_master: dict
    #: Quantos `.pmr` foram lidos, e quantas pastas de mídia não tinham um.
    indices_lidos: int = 0
    pastas_sem_indice: int = 0
    #: Pastas que existem e foram puladas de propósito (`MXF-<projeto>`).
    ignoradas: tuple = ()
    #: `{urn da ESSÊNCIA (o mob daquele arquivo): caminho}` — o arquivo exato de cada trilha.
    por_arquivo: dict | None = None
    #: Os `.mxf` que estavam no disco SEM constar do `.pmr` da pasta e entraram pela leitura do próprio arquivo.
    completados: int = 0

    @property
    def masters(self) -> int:
        return len(self.por_master)


def _urn(cabeca: bytes) -> str:
    """Os 32 bytes de cabeça de um registro → a URN SMPTE do mob.

    ⚠️ A ordem dos bytes é a de `pmr-fmid.md` §2: grupo 5 é `u32` LE, grupo 6 são
    **dois `u16`** LE, o resto é cru.
    """
    g = [bytearray(cabeca[i:i + 4]) for i in range(0, 32, 4)]
    g[4] = g[4][::-1]
    g[5] = g[5][1::-1] + g[5][3:1:-1]
    h = b"".join(bytes(x) for x in g).hex()
    return "urn:smpte:umid:" + ".".join(h[i:i + 8] for i in range(0, 64, 8))


def ler(caminho) -> list:
    """Um `.pmr` → `[(nome do arquivo, urn do master)]`."""
    return [(nome, master) for nome, _arquivo, master in ler_registros(caminho)]


def ler_registros(caminho) -> list:
    """Um `.pmr` → `[(nome do arquivo, urn da essência do arquivo, urn do master)]`.

    ⚠️ Nunca levanta por conteúdo: um índice truncado ou de outra versão devolve o que
    deu para ler. Ele é um cache — falhar aqui derrubaria a conferência inteira por causa
    de uma pasta que nem era a certa.
    """
    caminho = Path(caminho)
    try:
        dados = caminho.read_bytes()
    except OSError as e:
        log.info("não deu para ler %s: %s", caminho.name, e)
        return []
    if len(dados) < 12:
        return []
    magic, _a, n = struct.unpack_from("<III", dados, 0)
    if magic != _MAGIC:
        log.info("%s: magic 0x%x (esperado 0x%x) — ignorado", caminho.name, magic, _MAGIC)
        return []

    saida: list = []
    off, vistos, pendente = 12, 0, None
    while vistos < n and off + 32 <= len(dados):
        cabeca = dados[off:off + 32]
        off += 32
        if off + 2 > len(dados):
            break
        (tam,) = struct.unpack_from("<H", dados, off)
        espia = dados[off + 2:off + 2 + tam] if tam else b""
        # LONG ou SHORT? O LONG tem um comprimento plausível seguido de ASCII.
        e_longo = 0 < tam < _MAX_NOME and len(espia) == tam and all(
            32 <= c < 127 for c in espia)
        if e_longo:
            off += 2
            nome = dados[off:off + tam].decode("ascii", "replace")
            off += tam
            if off + 2 > len(dados):
                break
            (tape,) = struct.unpack_from("<H", dados, off)
            off += 2 + tape
            pendente = (nome, _urn(cabeca))
            continue
        # ⭐ O SHORT: é ele que traz o master, e só vale se houver um LONG esperando.
        off += 4
        if pendente is not None:
            saida.append((pendente[0], pendente[1], _urn(cabeca)))
            pendente = None
            vistos += 1
    return saida


# ── onde procurar ──────────────────────────────────────────────────────────────


def volumes_montados() -> list:
    """As raízes dos volumes montados. `[]` fora do Windows.

    ⚠️⚠️ **`SetErrorMode(SEM_FAILCRITICALERRORS)` não é opcional.** Sem ele, consultar um
    **leitor de cartão vazio** abre o diálogo modal *"Insira um disco na unidade"* — e o
    motor roda em segundo plano, atrás da janela do Media Composer: ele **congela
    esperando um clique numa janela que ninguém vê**. Não é hipótese: em 07/09/2026 um
    `Reveal File` esquecido atrás do MC travou a API inteira e o painel ficou parado em
    "lendo os campos de cada corte…". Um modal nosso seria pior — invisível E sem culpado.
    """
    if os.name != "nt":
        raiz = Path("/Volumes")
        if raiz.is_dir():
            try:
                return [str(p) for p in raiz.iterdir() if p.is_dir()]
            except OSError:
                return []
        return []

    import ctypes

    k32 = ctypes.windll.kernel32
    anterior = k32.SetErrorMode(0x0001)          # SEM_FAILCRITICALERRORS
    try:
        montadas = k32.GetLogicalDrives()
        return [f"{chr(ord('A') + i)}:\\" for i in range(26) if montadas & (1 << i)]
    finally:
        k32.SetErrorMode(anterior)


def pastas_de_midia(raiz) -> tuple:
    """As pastas numeradas a varrer sob uma raiz — e só elas.

    Devolve `(pastas, ignoradas)`. Aceita tanto o volume (`D:\\`) quanto a própria
    `Avid MediaFiles`, porque quem chama tem uma ou outra na mão dependendo de onde o
    caminho veio.
    """
    base = Path(raiz)
    if base.name.lower() != RAIZ_DO_AVID:
        achada = None
        try:
            for filho in base.iterdir():
                if filho.is_dir() and filho.name.lower() == RAIZ_DO_AVID:
                    achada = filho
                    break
        except OSError:
            return [], []
        if achada is None:
            return [], []
        base = achada

    boas, ignoradas = [], []
    try:
        for filho in sorted(base.iterdir()):
            if not filho.is_dir():
                continue
            if filho.name.upper() in PASTAS_DE_MIDIA:
                # As pastas NUMERADAS de dentro — é onde a mídia e o índice moram.
                try:
                    boas.extend(sorted(d for d in filho.iterdir() if d.is_dir()))
                except OSError:
                    continue
            else:
                # ⛔ `MXF-<projeto>` e afins: mídia que o editor escondeu do Avid.
                ignoradas.append(str(filho))
    except OSError:
        return [], []
    return boas, ignoradas


def tipo_da_pasta(caminho: str) -> str:
    """O que uma pasta INDICADA pelo editor é (autor, 2026-10-25, organograma Premiere → Avid):

    - `"avid"` — a `Avid MediaFiles` (ou a `MXF`/`UME` dentro dela, ou abaixo delas): mídia GERENCIADA, que se procura
      pelo índice do Avid e NUNCA se linka por AMA;
    - `"fora"` — outra pasta dentro da `Avid MediaFiles` (`MXF-desconectar`, `MXF-<projeto>`): mídia que o editor tirou
      do Avid de propósito (guarda 1) — é descartada;
    - `"link"` — qualquer outra: pasta de link.

    Pela FORMA do caminho, sem tocar no disco e sem depender da caixa (guarda 2) nem da barra."""
    partes = [x for x in str(caminho or "").replace("\\", "/").split("/") if x]
    baixas = [x.lower() for x in partes]
    if RAIZ_DO_AVID not in baixas:
        return "link"
    i = baixas.index(RAIZ_DO_AVID)
    sub = partes[i + 1] if i + 1 < len(partes) else ""
    return "avid" if not sub or sub.upper() in PASTAS_DE_MIDIA else "fora"


def raizes_de_midia() -> list:
    """As pastas `Avid MediaFiles` dos volumes montados nesta máquina.

    ⭐⭐ **Sem perguntar nada ao Media Composer, e de propósito.** O caminho "oficial"
    seria a coluna `Drive` da bin — que nem é uma letra de unidade (`'SSD (D:)'`)
    e custa uma chamada gRPC. Enumerar os volumes é local, barato e não depende de a bin
    trazer a coluna: a mídia de um clipe pode estar num volume que a bin não menciona.
    """
    fora: list = []
    for volume in volumes_montados():
        try:
            for filho in Path(volume).iterdir():
                if filho.is_dir() and filho.name.lower() == RAIZ_DO_AVID:
                    fora.append(str(filho))
                    break
        except OSError:
            # ⚠️ Volume sem mídia, sem permissão ou desconectado não é erro: é um volume
            # que não interessa. Um `raise` aqui derrubaria a conferência inteira.
            continue
    return fora


def _hex_para_urn(valor: str | None) -> str | None:
    """`0x060A2B34…` (o UMID como o `ffprobe` escreve, 32 bytes) → a URN do pyavb e do `.pmr`."""
    h = (valor or "").lower().removeprefix("0x")
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        return None
    return "urn:smpte:umid:" + ".".join(h[i:i + 8] for i in range(0, 64, 8))


def _ler_do_arquivo(caminho: Path) -> tuple[str | None, str | None]:
    """`(urn do master, urn da essência)` lidos do PRÓPRIO `.mxf` (OP-Atom, pelo `ffprobe`); `(None, None)` se não der."""
    from media import opatom
    doc = opatom.probe_file(str(caminho))
    if not doc:
        return None, None
    lido = opatom.parse_probe(doc, str(caminho))
    if isinstance(lido, str):
        return None, None
    return _hex_para_urn(lido.clip_umid), _hex_para_urn(lido.file_umid)


def _completar(sub: Path, listados: set[str]) -> list[tuple[str, str | None, str | None]]:
    """Os `.mxf` da pasta que o `.pmr` NÃO lista → `[(nome, urn da essência, urn do master)]`, lidos do arquivo.

    ⛔ O `.pmr` não é fundação (`protocolos/msm/pmr-fmid.md` §5): ele fica para trás quando a pasta ganha arquivos — o
    da `98_SFX…` da PRODUCAO-A listava 30 dos 84 (MC 25.12, 2026-11-24). O Media Composer lê os MXF e mostra tudo
    online; quem confiava só no índice deixava 21 de 866 trechos offline. Só os NÃO listados são lidos (o índice
    continua sendo o caminho rápido), em paralelo — um `ffprobe` por arquivo."""
    try:
        faltam = sorted(e for e in os.listdir(sub)
                        if e.lower().endswith(".mxf") and not e.startswith("._") and e not in listados)
    except OSError:
        return []
    if not faltam:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        lidos = list(ex.map(lambda n: _ler_do_arquivo(sub / n), faltam))
    return [(nome, essencia, master) for nome, (master, essencia) in zip(faltam, lidos) if master or essencia]


def indice_de(raizes, completar: bool = True) -> Leitura:
    """As raízes de mídia → `{urn do master: [arquivos]}`: o `.pmr` de cada pasta e, com `completar`, os `.mxf` que ele
    não lista lidos do próprio arquivo (`_completar` — desde 2026-11-24; antes, nenhum `.mxf` era aberto).

    ⚠️ Um master pode ter arquivos em pastas numeradas diferentes (e em volumes
    diferentes — nesta máquina `D:` e `E:` carregam o mesmo acervo). A lista soma todas e
    sai **ordenada**, para que a escolha de quem consome seja determinística: duas
    conferências da mesma timeline têm de medir o mesmo arquivo, senão os números não se
    reproduzem e a calibração dos limiares perde o chão.
    """
    por_master: dict = {}
    por_arquivo: dict = {}
    lidos = sem_indice = completados = 0
    ignoradas: list = []

    for raiz in raizes or []:
        if not raiz:
            continue
        pastas, fora = pastas_de_midia(raiz)
        ignoradas.extend(fora)
        for sub in pastas:
            alvo = sub / INDICE
            registros: list = []
            if alvo.is_file():
                lidos += 1
                registros = ler_registros(alvo)
            else:
                sem_indice += 1
            if completar:
                extras = _completar(sub, {nome for nome, _a, _u in registros})
                completados += len(extras)
                registros = list(registros) + extras
            for nome, arquivo, urn in registros:
                if urn:
                    por_master.setdefault(urn, []).append(str(sub / nome))
                if not arquivo:
                    continue
                # A 1ª ocorrência fica (volumes e pastas são percorridos em ordem estável) —
                # ⛔ salvo se o arquivo dela SUMIU e o desta existe: o índice de uma pasta não muda
                # quando o editor move os `.mxf` para outra, e a velha vinha antes na ordem
                # (`MXF\1-…` < `MXF\3572`: o DRT apontava o arquivo que já não estava lá —
                # laboratório A01, 2026-10-11). Só olha o disco nas colisões, que são raras.
                novo = str(sub / nome)
                atual = por_arquivo.setdefault(arquivo, novo)
                if atual != novo and not Path(atual).is_file() and Path(novo).is_file():
                    por_arquivo[arquivo] = novo

    for urn in por_master:
        por_master[urn] = sorted(dict.fromkeys(por_master[urn]))

    log.info("pmr: %d índice(s), %d master(s), %d sem índice, %d pasta(s) ignorada(s), %d .mxf fora do índice lidos do arquivo",
             lidos, len(por_master), sem_indice, len(ignoradas), completados)
    return Leitura(por_master=por_master, indices_lidos=lidos,
                   pastas_sem_indice=sem_indice, ignoradas=tuple(ignoradas),
                   por_arquivo=por_arquivo, completados=completados)
