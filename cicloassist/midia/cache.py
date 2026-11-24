"""O cache do que já se sabe sobre uma mídia — endereçado pelo UMID do MASTER.

⭐⭐ **A regra que organiza tudo aqui, e ela é herdada de um módulo que já rodou em
produção** (`_ASSIST ANTERIOR/assist_anterior/transcricao/store.py`):

> A transcrição — e agora também os frames — é endereçada pelo **UMID do master**, não
> pelo hash de um arquivo. O hash exige ter o arquivo em mãos; o UMID vem de dentro do
> clipe. Processou uma vez, e **qualquer clipe que use aquele material acha pronto**:
> masterclipe, subclipe, groupclipe (multicam), e subclipe criado DEPOIS.

⭐ **E para frames há um segundo lado da mesma regra: o número do quadro é contado no
tempo do MASTER, nunca no do subclipe.** Dois subclipes que recortam pedaços vizinhos da
mesma diária compartilham os quadros da sobreposição. Numerar em tempo de subclipe faria
o mesmo frame ser extraído e guardado uma vez por recorte — o cache pareceria funcionar e
nunca acertaria.

## As três propriedades do armazenamento

Herdadas do sidecar do Decupador, cada uma paga por um defeito medido:

1. **Um diretório por mídia.** Mídias diferentes nunca colidem, e a mesma mídia é
   reconhecida em vez de reprocessada. Sem banco central: o compartilhamento é SMB, onde
   lock não é confiável.
2. **Escrita atômica.** Temporário + `os.replace()`. Ninguém vê arquivo pela metade, nem
   se a máquina cair no meio.
3. **Leitura defensiva.** O que está em disco é ENTRADA NÃO CONFIÁVEL: teto de tamanho,
   e o nome do diretório validado antes de virar caminho.

⛔ **E o cache NÃO mora ao lado da mídia.** Mídia gerenciada pelo Avid não tem "lado" —
ela vive em `Avid MediaFiles/MXF/<n>/` junto com centenas de outras.

## ⭐⭐ A pasta tem nome de gente; a identidade mora no manifesto (2026-09-13)

O editor abriu o cache e viu trinta pastas `060a2b3401010105…`. Ninguém administra o que
não consegue ler. Desde a spec `docs/spec/2026-09-13-cache-legivel-e-compartilhado.md`:

```
C001_23.976_video_04m12s_20260913-162206_a3f9c1\
    midia.json      ← o MANIFESTO: a chave, as identidades, o nome, os arquivos
```

- ⭐ O nome é o `material_package_name` — o nome **como está na bin** (banco,
  `protocolos/mxf/README.md`). O OP-Atom parte um clipe em vários arquivos com nome
  ilegível (`A01.E69CCF10_1A8ED1A8EDD3FA.mxf`), e eles vão para o manifesto.
- ⛔⛔ **O nome é RÓTULO, não CHAVE.** Câmeras A e B gravando `C001` no mesmo segundo
  teriam o mesmo nome; renomear na bin perderia a pasta. Quem acha a mídia é o ÍNDICE,
  pelo manifesto — e o sufixo de 6 hexadecimais separa as duas câmeras.
- O nome é fixado no NASCIMENTO, que é a primeira escrita. Só LER nunca cria pasta:
  diretório vazio por mídia consultada encheria o disco de nada.
- ⚠️ Pasta antiga, de 64 hexadecimais e sem manifesto, continua sendo achada até a
  migração (`tools/migrar_cache.py`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from fractions import Fraction
from pathlib import Path
from typing import Any, NamedTuple

log = logging.getLogger("cicloassist.midia.cache")

_HEX = set("0123456789abcdef")

#: Teto para JSON vindo do disco. Um índice honesto tem alguns KB; 16 MB é folga generosa
#: e ainda barra bomba de memória.
MAX_JSON_BYTES = 16 * 1024 * 1024


class ChaveInvalida(ValueError):
    """UMID que não vira chave. Exceção própria porque quem chamou precisa distinguir
    isto de um erro ao ler o arquivo."""


def de_umid(umid: str) -> str:
    """`urn:smpte:umid:060a2b34.0101…` → `060a2b340101…` (64 hex minúsculos).

    ⛔ **Esta chave vira NOME DE DIRETÓRIO, e é por isso que a validação é dura.** Um
    `.avb` de terceiro traz strings que não escolhemos; sem a checagem, um campo torto
    levaria a escrita para fora da pasta.

    ⚠️ **Minúsculas sempre.** Sem isso o mesmo material ganha dois diretórios, e o cache
    *pareceria* funcionar enquanto nunca acertasse — o pior modo de falha de um cache,
    porque não há erro, só lentidão que ninguém explica.

    ⚠️ Tirar o prefixo ANTES de filtrar hexadecimais: o `e` de `smpte` e o `d` de `umid`
    passam por um filtro de hex e o total vira 66 dígitos. É irmão do erro que a família
    `remap.py` já pagou, e está registrado no banco.
    """
    if not isinstance(umid, str):
        raise ChaveInvalida(f"UMID não é texto: {umid!r}")
    bruto = umid.rsplit(":", 1)[-1].replace(".", "").replace("-", "").strip().lower()
    # ⭐ O `ffprobe` escreve o MESMO identificador noutra grafia:
    #   `0x060A2B34…` em vez de `urn:smpte:umid:060a2b34.…`. É o `material_package_umid`
    #   do OP-Atom, e é o que permite a varredura do acervo encontrar o cache que a
    #   conversa já produziu. Sem tirar o `0x` aqui, a mesma mídia ganharia duas
    #   identidades — e a varredura diria "nada analisado" sobre material já pronto.
    if bruto.startswith("0x"):
        bruto = bruto[2:]
    if not e_chave(bruto):
        raise ChaveInvalida(
            f"UMID não vira chave de 64 hex: {umid!r} → {bruto!r} "
            f"({len(bruto)} caractere(s))"
        )
    return bruto


def e_chave(nome: str) -> bool:
    """Este texto é uma chave nossa — 64 hexadecimais minúsculos?

    ⭐ Existe para que LER o cache use exatamente o mesmo critério que ESCREVER nele. A
    aba Vetores lista o que há na pasta, e o nome de um diretório que veio do disco é
    entrada não confiável como qualquer outra: uma pasta estranha largada ali dentro não
    pode virar uma linha da tabela nem, pior, um caminho que a gente abra.
    """
    return len(nome) == 64 and all(c in _HEX for c in nome)


def raiz() -> Path:
    """Onde o cache vive. A variável de ambiente sobrepõe.

    ⛔⛔ **Uma conta só, e ela mora aqui.** No projeto anterior esta conta existia em
    TRÊS lugares, duas delas cópias declaradas — e as cópias divergiam da terceira no
    macOS, mandando log para uma pasta e transcrição para outra, sem nada acusar. No
    Windows as três coincidiam, e é por isso que ninguém viu.
    """
    do_ambiente = os.environ.get("CICLOASSIST_CACHE")
    if do_ambiente:
        return Path(do_ambiente)

    # ⭐ O editor pode mudar isto pelo painel (engrenagem → cache), e a escolha dele mora
    #   no `config.json`. O ambiente ainda ganha: é o que o desenvolvimento usa para não
    #   encostar no cache de quem está trabalhando na máquina.
    #
    # ⚠️ Import LOCAL, e não no topo: `servico/config.py` importa `escrever_atomico`
    #   daqui. No topo, os dois módulos se importariam em círculo já na partida.
    try:
        from ..servico.config import ler
        escolhido = ler().get("cache")
        if escolhido:
            return Path(str(escolhido))
    except Exception:
        # ⛔ Config quebrada não pode esconder o cache: cair no padrão custa reprocessar,
        #    estourar aqui derruba toda ferramenta que toca em mídia.
        pass

    from ..servico.config import pasta
    return pasta() / "midia"


def escrever_atomico(destino: Path, dados: bytes) -> None:
    """Escreve por temporário + `os.replace()`.

    O `os.replace` é atômico no mesmo volume — por isso o temporário nasce na pasta de
    destino e não em `/tmp`, que pode estar noutro disco e transformaria a troca atômica
    numa cópia comum.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(destino.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        os.replace(tmp, destino)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ── o nome da pasta ──────────────────────────────────────────────────────────

MANIFESTO = "midia.json"
ESQUEMA = 1

#: ⭐⭐ De que EDITOR esta entrada nasceu. Decisão do editor (2026-09-21), e é uma regra de
#: produto, não de armazenamento: **o banco do Premiere nunca pré-carrega o cache do Avid**.
#:
#: ⛔⛔ Até aqui uma mídia era UMA pasta com várias chaves (apelidos), e o `.mp4` que o
#: Premiere aponta resolvia para a pasta do Avid — com o NOME da bin do Avid e os caminhos
#: `D:/Avid MediaFiles/…` dentro. Medido no projeto dele: `B001_03150112_C001.mp4` caía em
#: `B001_03150112_C001`, cujos arquivos são três OP-Atom. Recorte nenhum conserta isso: a
#: entrada ERA a do Avid. ⇒ cada editor tem a sua entrada, e o cruzamento acontece uma vez
#: só, na hora de PROCESSAR (`identidade.aproveitar`).
#:
#: ⚠️ Entrada sem `origem` no manifesto é do Avid: as 332 desta máquina nasceram todas lá,
#: e inventar "desconhecido" faria a busca do Avid perder o próprio acervo.
ORIGENS = ("avid", "premiere")
ORIGEM_PADRAO = "avid"


def origem_valida(valor: object) -> str:
    texto = str(valor or "").strip().lower()
    return texto if texto in ORIGENS else ORIGEM_PADRAO

#: Pastas da raiz que não são mídia nem projeto: a cópia da migração e (fase C4) o banco.
RESERVADAS = {"_antes_da_migracao", "_banco"}

#: Quanto do nome da mídia entra no nome da pasta. ⚠️ MEDIDO no cache: um efeito sonoro
#: com mais de 150 caracteres — inteiro, estouraria o limite de caminho do Windows.
NOME_NA_PASTA = 40

TIPOS = ("video", "audio", "foto")

_PROIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_DISPOSITIVOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


def id_curto(chave: str) -> str:
    """6 hexadecimais que separam duas mídias de mesmo rótulo.

    ⚠️ Do HASH da chave, e não do fim dela: os UMIDs gerenciados terminam todos iguais
    (`…060e2b347f7f2a80`, visível no Explorer do editor) — o fim da chave colidiria.
    """
    return hashlib.sha1(chave.encode()).hexdigest()[:6]


def _limpar(nome: str) -> str:
    limpo = _PROIBIDOS.sub("_", str(nome or "")).strip().strip(".")
    limpo = re.sub(r"\s+", " ", limpo)[:NOME_NA_PASTA].strip().strip(".")
    if limpo.split(".")[0].upper() in _DISPOSITIVOS:
        limpo = f"_{limpo}"
    return limpo or "sem-nome"


def texto_do_fps(fps: Any) -> str:
    """`12000/1001`, `{"num": 24000, "den": 1001}`, `23.976` → `23.976`; `25` → `25`."""
    try:
        if isinstance(fps, dict):
            valor = Fraction(int(fps["num"]), int(fps["den"]))
        elif isinstance(fps, str) and "/" in fps:
            valor = Fraction(fps)
        else:
            valor = Fraction(str(fps))
        if valor <= 0:
            return ""
        return f"{float(valor):.3f}".rstrip("0").rstrip(".")
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        return ""


def texto_da_duracao(segundos: Any, fps: Any = None) -> str:
    try:
        exato = float(segundos)
    except (TypeError, ValueError):
        return ""
    if exato <= 0:
        return ""
    total = int(round(exato))
    if total == 0:
        # ⚠️ MEDIDO no acervo: `a003_03170838_C002` tem 8 frames. Arredondar para segundo
        #    sumiria com a duração — e "00m00s" leria como vazio.
        taxa = texto_do_fps(fps)
        return f"{round(exato * float(taxa))}f" if taxa else "1s"
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def nome_da_pasta(chave: str, rotulo: dict[str, Any], nasceu: float) -> str:
    """`<nome>_<fps>_<tipo>_<duração>_<AAAAMMDD-HHMMSS>_<id>` — o que falta, fica de fora."""
    tipo = rotulo.get("tipo") if rotulo.get("tipo") in TIPOS else ""
    taxa = texto_do_fps(rotulo.get("fps"))
    if not taxa and rotulo.get("amostragem"):
        # ⭐ Som não tem quadro: no lugar do fps vai a amostragem, que é o que o editor
        #   confere num arquivo de áudio.
        taxa = f"{int(rotulo['amostragem']) / 1000:g}kHz"
    partes = [
        _limpar(rotulo.get("nome") or ""),
        "" if tipo == "foto" else taxa,
        tipo,
        "" if tipo == "foto" else texto_da_duracao(rotulo.get("duracao_s"),
                                                    rotulo.get("fps")),
        time.strftime("%Y%m%d-%H%M%S", time.localtime(nasceu)),
        id_curto(chave),
    ]
    return "_".join(p for p in partes if p)


# ── o índice: chave → pasta ──────────────────────────────────────────────────


def _nfc(caminho: Path) -> str:
    """O caminho como texto COMPOSTO. Ver `_Indice.varrer`: o disco do Mac lista em NFD."""
    return unicodedata.normalize("NFC", str(caminho))


def identidades_do_manifesto(dados: dict[str, Any]) -> list[str]:
    """Toda chave pela qual uma mídia pode ser pedida: as `identidades` e os `apelidos`."""
    saida: list[str] = []
    ids = dados.get("identidades")
    if isinstance(ids, dict):
        saida += [v for v in ids.values() if isinstance(v, str)]
    for ap in dados.get("apelidos") or []:
        if isinstance(ap, dict) and isinstance(ap.get("chave"), str):
            saida.append(ap["chave"])
    return [c for c in saida if e_chave(c)]


class _Indice:
    """Onde mora cada mídia de UMA raiz. Derivado do disco, nunca a fonte da verdade.

    ⭐ Incremental: uma listagem da raiz, e só as pastas NOVAS têm o manifesto lido. Mídia
    nova (o caso comum de uma busca que erra) custa uma listagem, não reler tudo.

    ⚠️ Em memória, por processo. Na rede (fase C4) ele passa a ser guardado no disco LOCAL
    de cada máquina — nunca num banco dentro do NAS.
    """

    def __init__(self, raiz_: Path):
        self.raiz = raiz_
        self.mapa: dict[str, Path] = {}
        #: ⭐ De que editor nasceu cada chave primária. Lido do manifesto na MESMA passada
        #: que já monta o índice — perguntar depois seria reler 332 arquivos.
        self.origens: dict[str, str] = {}
        #: ⭐ Outra identidade da MESMA mídia → a chave dela (P1 do Premiere, 2026-09-17).
        #: O `.mov` AMA que o Avid linkou com um `mob_id` e o Premiere aponta pelo conteúdo
        #: é uma pasta só; cada caminho até ela é um apelido. Nunca uma pasta por apelido:
        #: `todas()` lista só as chaves.
        self.apelidos: dict[str, str] = {}
        self.estranhas: set[Path] = set()
        self.trava = threading.RLock()
        self.varrido_em = float("-inf")

    def _e_midia(self, pasta: Path) -> bool:
        """Registra `pasta` se for mídia. Devolve se era."""
        manifesto = pasta / MANIFESTO
        if manifesto.is_file():
            dados = _ler_json_em(manifesto)
            chave = dados.get("chave")
            if isinstance(chave, str) and e_chave(chave):
                anterior = self.mapa.get(chave)
                if anterior is not None and _nfc(anterior) != _nfc(pasta) and anterior.is_dir() \
                        and (anterior / MANIFESTO).is_file():
                    log.warning("a mídia %s tem duas pastas: %s e %s; fico com a primeira",
                                chave[:12], anterior.name, pasta.name)
                    return True
                self.mapa[chave] = pasta
                self.origens[chave] = origem_valida(dados.get("origem"))
                for outra in identidades_do_manifesto(dados):
                    # ⚠️ Chave de verdade ganha de apelido: uma pasta que NASCEU com esta
                    #    chave é mais certa que outra que a adotou.
                    if outra != chave and outra not in self.mapa:
                        self.apelidos.setdefault(outra, chave)
                return True
        if e_chave(pasta.name):
            # Pasta de antes do manifesto: vale até migrar, e perde para quem tem manifesto.
            anterior = self.mapa.get(pasta.name)
            if anterior is None or not (anterior / MANIFESTO).is_file():
                self.mapa[pasta.name] = pasta
            return True
        return False

    def varrer(self) -> None:
        """Uma listagem da raiz e das pastas que não são mídia (as de PROJETO, fase C2).

        ⛔ Sem memória de "já vi esta pasta". A primeira versão guardava as vistas e nunca
        relistava uma pasta de projeto que já tinha mídia: a mídia que OUTRO processo criasse
        ali dentro ficava invisível até reiniciar — o serviço reprocessaria em silêncio o
        que a fila acabou de fazer. Só a pasta JÁ MAPEADA é pulada, e é ela que custa ler.
        """
        with self.trava:
            self.mapa = {k: v for k, v in self.mapa.items() if v.is_dir()}
            self.origens = {k: v for k, v in self.origens.items() if k in self.mapa}
            self.apelidos = {k: v for k, v in self.apelidos.items() if v in self.mapa}
            # ⛔ Comparado em NFC: a pasta nasce com o nome COMPOSTO que o código escreve, e
            #    exFAT/HFS+ a LISTAM decomposta. MEDIDO no macOS (2026-09-14): `item in vivas`
            #    nunca batia para mídia nascida no processo, e cada relistagem logava "a mídia
            #    tem duas pastas: X e X" — uma duplicação que não existia.
            vivas = {_nfc(v) for v in self.mapa.values()}
            try:
                itens = sorted(self.raiz.iterdir())
            except OSError:
                self.estranhas = set()
                return
            estranhas = set()
            for item in itens:
                # ⚠️ `.fseventsd`, `.Trashes`, `.Spotlight-V100`: o macOS os põe na raiz de
                #    todo volume, e com o cache na raiz de um disco viravam "estranhas".
                if not item.is_dir() or item.name in RESERVADAS or item.name.startswith(".") \
                        or _nfc(item) in vivas:
                    continue
                if self._e_midia(item):
                    continue
                # Não é mídia: pode ser pasta de projeto. As filhas são olhadas SEMPRE.
                achou = False
                try:
                    for filha in item.iterdir():
                        if filha.is_dir() and (_nfc(filha) in vivas or self._e_midia(filha)):
                            achou = True
                except OSError:
                    pass
                if not achou:
                    estranhas.add(item)
            self.estranhas = estranhas

    def dona(self, chave: str, banco: str = "") -> str:
        """A chave da pasta a que `chave` leva, sem sair de `banco`.

        ⛔⛔ **Apelido não atravessa banco.** Pedindo uma entrada do Premiere, uma chave
        que hoje é apelido de uma entrada do Avid tem de continuar sendo a chave CRUA —
        senão a entrada "nova" cairia na pasta do Avid e `copiar_de` copiaria a pasta
        sobre si mesma. MEDIDO em 2026-09-21: foi exatamente isso, `WinError 32` em cada
        quadro, com a entrada respondendo `origem=avid`.
        """
        with self.trava:
            if chave in self.mapa:
                return chave
            dona = self.apelidos.get(chave, chave)
            if banco and dona != chave and self.origens.get(dona, ORIGEM_PADRAO) != banco:
                return chave
            return dona

    def achar(self, chave: str, forcar: bool = False, banco: str = "") -> Path | None:
        """⚠️ Mídia que não existe relistaria a raiz a CADA pergunta — extrair 6 quadros de
        uma mídia nova são dezenas de `tem_quadro`, e num NAS com milhares de pastas cada
        listagem custa. Na leitura, uma varredura a cada `RELISTAR_S`; quem vai CRIAR pasta
        pede `forcar`, porque errar ali é pasta duplicada."""
        with self.trava:
            pasta = self.mapa.get(self.dona(chave, banco))
            if pasta is not None and pasta.is_dir():
                return pasta
            agora = time.monotonic()
            if not forcar and agora - self.varrido_em < RELISTAR_S:
                return None
            self.varrer()
            self.varrido_em = agora
            return self.mapa.get(self.dona(chave, banco))

    def origem_de(self, chave: str) -> str:
        """De que editor é a mídia que responde por esta chave (primária ou apelido)."""
        with self.trava:
            return self.origens.get(self.dona(chave), ORIGEM_PADRAO)

    def primaria(self, chave: str, banco: str = "") -> str:
        """A chave da pasta a que `chave` leva — ela mesma, se não for apelido. Sem disco."""
        return self.dona(chave, banco)

    def registrar(self, chave: str, pasta: Path, origem: str = ORIGEM_PADRAO) -> None:
        """⚠️ A ORIGEM vem junto, e não é detalhe: a mídia recém-nascida entra no índice
        por aqui, sem passar pelo `_e_midia` que lê o manifesto. Sem ela, uma entrada do
        Premiere criada agora respondia `avid` até a próxima varredura — e a busca do
        editor não a via no banco dele."""
        with self.trava:
            self.mapa[chave] = pasta
            self.origens[chave] = origem_valida(origem)
            self.apelidos.pop(chave, None)
            self.estranhas.discard(pasta)

    def registrar_apelido(self, apelido: str, chave: str) -> None:
        with self.trava:
            if apelido != chave and apelido not in self.mapa:
                self.apelidos[apelido] = chave


#: De quanto em quanto tempo uma pergunta sem resposta relista a raiz. Mídia que OUTRO
#: processo criou aparece em até isto; a deste processo aparece na hora (`registrar`).
RELISTAR_S = 2.0

_indices: dict[str, _Indice] = {}
_trava_dos_indices = threading.Lock()


def indice(raiz_: Path | None = None) -> _Indice:
    onde = Path(raiz_ or raiz())
    with _trava_dos_indices:
        # ⚠️ Sem `resolve()`: ele só expande o caminho quando a pasta EXISTE, e o
        #    `USUARI~1` do TEMP vira o nome longo — a mesma raiz ganharia dois índices
        #    antes e depois de nascer a primeira mídia, e o segundo não saberia dela.
        # ⚠️ E em NFC: a mesma raiz vinda do seletor do Mac (NFD) e do config (NFC) seriam
        #    dois índices da mesma pasta.
        chave = unicodedata.normalize("NFC", os.path.normcase(os.path.abspath(str(onde))))
        if chave not in _indices:
            _indices[chave] = _Indice(onde)
        return _indices[chave]


def todas(raiz_: Path | None = None) -> list["Midia"]:
    """⭐ A ÚNICA forma de listar o cache. Antes eram seis `iterdir` espalhados, cada um
    com o seu critério de "isto é uma mídia" — e o nome legível quebraria os seis."""
    onde = Path(raiz_ or raiz())
    ind = indice(onde)
    ind.varrer()
    with ind.trava:
        pares = sorted(ind.mapa.items(), key=lambda kv: kv[1].name.lower())
    saida = []
    for chave, pasta in pares:
        m = Midia(chave, raiz_do_cache=onde)
        m._pasta = pasta
        saida.append(m)
    return saida


def chaves_da_origem(origem: str, raiz_: Path | None = None) -> frozenset[str]:
    """Toda chave — primária E apelido — das entradas de UM editor.

    ⭐⭐ É o filtro que separa os bancos na RESPOSTA. Decisão do editor (2026-09-21): a
    busca no Premiere nunca mostra material do Media Composer, nem o nome dele, nem um
    caminho de `Avid MediaFiles`.

    ⛔ Inclui os apelidos porque o recorte de um projeto chega em chaves de arquivo, e uma
    entrada do Premiere pode ter mais de uma (o `mob_id` que o Avid gera, a impressão do
    conteúdo). Fora isso, a conta é a mesma de `com_apelidos`.
    """
    alvo = origem_valida(origem)
    ind = indice(raiz_)
    ind.varrer()
    with ind.trava:
        primarias = {c for c in ind.mapa if ind.origens.get(c, ORIGEM_PADRAO) == alvo}
        apelidos = {a for a, dona in ind.apelidos.items() if dona in primarias}
    return frozenset(primarias | apelidos)


def com_apelidos(ids: "set[str] | frozenset[str]", raiz_: Path | None = None) -> frozenset[str]:
    """`ids` mais a chave de cada mídia a que algum deles é apelido.

    ⭐ É o que o recorte por projeto precisa: as bins dão `mob_id`s, e a mídia AMA pode
    estar guardada sob a impressão do conteúdo, com o `mob_id` como apelido. Sem isto, o
    material do projeto aberto sairia "fora do projeto".
    """
    ind = indice(raiz_)
    ind.varrer()
    with ind.trava:
        extras = {ind.apelidos[i] for i in ids if i in ind.apelidos}
    return frozenset(ids) | frozenset(extras)


def estranhas(raiz_: Path | None = None) -> int:
    """Pastas da raiz que não são mídia nossa — o "isto é mesmo o meu cache?" do reconectar."""
    ind = indice(raiz_)
    ind.varrer()
    return len(ind.estranhas)


def _ler_json_em(caminho: Path) -> dict[str, Any]:
    try:
        if not caminho.is_file() or caminho.stat().st_size > MAX_JSON_BYTES:
            return {}
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning("cache ilegível em %s (%s); tratando como vazio", caminho, e)
        return {}


#: ⛔ Duas threads nascendo a MESMA mídia (a fila e um turno) criariam duas pastas com o
#: segundo diferente no nome. Nascer é raro e rápido: uma trava só basta.
_trava_de_nascer = threading.Lock()

#: ⛔ Toda escrita no MANIFESTO passa por aqui. Ele é lido-e-regravado inteiro por três
#: caminhos (`anotar_fonte`, `apelidar`, o nascimento), e dois deles rodam em threads
#: diferentes ao mesmo tempo no uso normal — resolver um take (que apelida) enquanto a fila
#: transcreve (que anota a fonte). Sem a trava, o último a gravar apaga o que o outro
#: acabou de escrever, e o único sintoma é uma identidade que some.
_trava_do_manifesto = threading.RLock()


class Ficha(NamedTuple):
    """O que o `midia.json` de uma mídia diz, lido de uma vez só. Ver `Midia.ficha`."""

    manifesto: dict[str, Any]
    fonte: dict[str, Any]
    nome: str
    origem: str


class Midia:
    """O cache de UM master: endereçado pelo UMID, guardado numa pasta de nome legível."""

    def __init__(self, umid: str, raiz_do_cache: Path | None = None,
                 rotulo: dict[str, Any] | None = None, tipo: str = "umid",
                 apelidos: dict[str, str] | None = None, origem: str = ""):
        """`tipo` diz de onde a chave veio (`umid` ou `conteudo`, ver `midia/identidade`);
        `apelidos` são outras chaves da mesma mídia (`{chave: tipo}`), gravadas ao nascer.

        ⭐ `origem` é o editor de quem esta entrada é (`ORIGENS`), e só vale ao NASCER —
        ler uma mídia não muda de que banco ela é."""
        self.raiz = Path(raiz_do_cache or raiz())
        # Apelido já conhecido deste processo vira a chave na hora, sem disco; o resto
        # se resolve em `achada()`.
        # ⛔⛔ **Mas apelido não atravessa BANCO.** Pedindo uma entrada do Premiere, uma
        #    chave que hoje é apelido de uma entrada do Avid tem de continuar sendo a
        #    chave CRUA — senão `aproveitar()` receberia de volta a pasta do Avid e a
        #    separação nunca aconteceria. (É o que os apelidos cruzados de antes de
        #    2026-09-21 faziam; `tools/separar_bancos.py` os remove, e isto aqui é o
        #    cinto de segurança para quem ainda não rodou.)
        #: O banco que quem pediu exige. Vazio = "tanto faz", que é o caso de toda
        #: leitura de dentro de um NLE só.
        self._banco = origem_valida(origem) if origem else ""
        self.chave = indice(self.raiz).primaria(de_umid(umid), self._banco)
        self._rotulo = {k: v for k, v in (rotulo or {}).items() if v}
        self._pasta: Path | None = None
        self._tipo = tipo
        self._apelidos_ao_nascer = {de_umid(k): v for k, v in (apelidos or {}).items()
                                    if e_chave(de_umid(k)) and de_umid(k) != self.chave}
        self._origem_ao_nascer = origem_valida(origem) if origem else ORIGEM_PADRAO

    def __repr__(self) -> str:
        return f"Midia({self.chave[:16]}…)"

    # ── onde ─────────────────────────────────────────────────────────────────

    def achada(self) -> Path | None:
        """A pasta, se a mídia já nasceu. Nunca cria."""
        if self._pasta is not None and self._pasta.is_dir():
            return self._pasta
        ind = indice(self.raiz)
        self._pasta = ind.achar(self.chave, banco=self._banco)
        if self._pasta is not None:
            # ⭐ Pedida por um apelido, a mídia passa a responder pela SUA chave: é ela que
            #    o recorte do projeto e as buscas comparam.
            self.chave = ind.primaria(self.chave, self._banco)
        return self._pasta

    @property
    def existe(self) -> bool:
        return self.achada() is not None

    @property
    def pasta(self) -> Path:
        """A pasta para ESCREVER — nasce aqui, com o nome legível, se ainda não existe."""
        return self.achada() or self._nascer()

    def arquivo(self, nome: str) -> Path:
        """Um arquivo da mídia para LER. Sem pasta ainda, um caminho que não existe."""
        return (self.achada() or self.raiz / self.chave) / nome

    def batizar(self, **rotulo: Any) -> "Midia":
        """O que se sabe da mídia para o nome da pasta: `nome`, `fps`, `tipo`, `duracao_s`,
        `arquivos`. Só vale ANTES do nascimento — depois, vai para o manifesto."""
        self._rotulo.update({k: v for k, v in rotulo.items() if v})
        return self

    def _rotulo_completo(self) -> dict[str, Any]:
        """O rótulo dado, completado pelo que a varredura do acervo sabe desta chave."""
        rotulo: dict[str, Any] = {}
        try:
            from . import acervo as _acervo
            clipe = (_acervo.ler(self.raiz).get("clipes") or {}).get(self.chave) or {}
        except Exception:  # noqa: BLE001 — acervo quebrado não impede nascer
            clipe = {}
        if clipe:
            rotulo = {
                "nome": clipe.get("nome"),
                "fps": clipe.get("fps"),
                "duracao_s": clipe.get("duracao_s"),
                "amostragem": clipe.get("amostragem"),
                "tipo": "video" if clipe.get("tem_imagem") else (
                    "audio" if clipe.get("tem_som") else ""),
                "arquivos": list(clipe.get("arquivos") or []),
            }
        rotulo.update(self._rotulo)
        return {k: v for k, v in rotulo.items() if v}

    def _nascer(self) -> Path:
        with _trava_de_nascer:
            achada = indice(self.raiz).achar(self.chave, forcar=True, banco=self._banco)
            if achada is not None:
                self._pasta = achada
                return achada
            rotulo = self._rotulo_completo()
            agora = time.time()
            destino = self.raiz / nome_da_pasta(self.chave, rotulo, agora)
            destino.mkdir(parents=True, exist_ok=True)
            manifesto = {
                "esquema": ESQUEMA,
                "chave": self.chave,
                "identidades": {self._tipo: self.chave},
                "origem": self._origem_ao_nascer,
                "nome": rotulo.get("nome") or "",
                "fps": texto_do_fps(rotulo.get("fps")),
                "tipo": rotulo.get("tipo") or "",
                "duracao_s": rotulo.get("duracao_s") or 0,
                "amostragem": rotulo.get("amostragem") or 0,
                "arquivos": [str(a) for a in rotulo.get("arquivos") or []],
                "nasceu": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(agora)),
                "pasta": destino.name,
            }
            if self._apelidos_ao_nascer:
                manifesto["apelidos"] = [{"chave": k, "tipo": v}
                                         for k, v in self._apelidos_ao_nascer.items()]
            escrever_atomico(destino / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1)
                             .encode("utf-8"))
            indice(self.raiz).registrar(self.chave, destino, self._origem_ao_nascer)
            for apelido in self._apelidos_ao_nascer:
                indice(self.raiz).registrar_apelido(apelido, self.chave)
            self._pasta = destino
            log.info("mídia nova no cache: %s", destino.name)
            return destino

    # ── o manifesto ──────────────────────────────────────────────────────────

    def manifesto(self) -> dict[str, Any]:
        return self._ler_json(self.arquivo(MANIFESTO))

    def ficha(self) -> "Ficha":
        """Manifesto, fonte e nome com **uma** leitura do `midia.json`.

        ⛔⛔ Pedindo os três pelo caminho normal, o mesmo arquivo é aberto de 3 a 5 vezes:
        `ler_fonte()` o lê, `nome` chama `ler_fonte()` DE NOVO e ainda `manifesto()`, e
        quem filtra por banco chama `origem`, que o lê outra vez. Numa listagem do cache
        inteiro (537 mídias) isso são ~1.800 leituras do mesmo arquivo pequeno — e é a aba
        Vetores que paga, a cada vez que o editor entra nela.
        """
        manifesto = self.manifesto()
        fonte = dict(self._ler_json(self.arquivo("fonte.json")))
        nova = manifesto.get("fonte")
        if isinstance(nova, dict):
            fonte.update(nova)
        nome = str(manifesto.get("nome") or fonte.get("master")
                   or fonte.get("master_de_som") or "")
        return Ficha(manifesto=manifesto, fonte=fonte, nome=nome,
                     origem=origem_valida(manifesto.get("origem")))

    @property
    def origem(self) -> str:
        """De que editor esta entrada é. ⚠️ Sem `origem` no manifesto é do Avid — ver `ORIGENS`."""
        return origem_valida(self.manifesto().get("origem"))

    @property
    def nome(self) -> str:
        """O nome que o editor reconhece: o do manifesto, e senão o que a fonte anotou."""
        fonte = self.ler_fonte()
        return str(self.manifesto().get("nome") or fonte.get("master")
                   or fonte.get("master_de_som") or "")

    # ── metadados da fonte ───────────────────────────────────────────────────

    def anotar_fonte(self, dados: dict[str, Any]) -> None:
        """Registra o que se sabe da mídia: nome do master, arquivo, taxa, duração.

        ⭐ Mora no MANIFESTO (`fonte`), junto da identidade. O `fonte.json` das pastas de
        antes da migração continua sendo lido.
        """
        if not self.existe:
            # O que a fonte sabe ajuda a batizar a pasta que vai nascer agora.
            nome = dados.get("master") or dados.get("master_de_som")
            self.batizar(nome=nome, arquivos=[dados["arquivo"]] if dados.get("arquivo")
                         else None)
        pasta = self.pasta
        with _trava_do_manifesto:
            manifesto = self._ler_json(pasta / MANIFESTO) or {"esquema": ESQUEMA,
                                                              "chave": self.chave}
            fonte = dict(manifesto.get("fonte") or {})
            fonte.update(dados)
            manifesto["fonte"] = fonte
            if not manifesto.get("nome") and (fonte.get("master") or fonte.get("master_de_som")):
                manifesto["nome"] = fonte.get("master") or fonte.get("master_de_som")
            escrever_atomico(pasta / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1).encode("utf-8"))

    def marcar_no_manifesto(self, campo: str, valor: Any) -> None:
        """Grava um campo solto no manifesto de uma mídia que JÁ existe (nunca faz nascer)."""
        pasta = self.achada()
        if pasta is None:
            return
        with _trava_do_manifesto:
            manifesto = self._ler_json(pasta / MANIFESTO)
            if not manifesto:
                return
            manifesto[campo] = valor
            escrever_atomico(pasta / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1).encode("utf-8"))

    def apelidos(self) -> list[dict[str, Any]]:
        return [a for a in self.manifesto().get("apelidos") or [] if isinstance(a, dict)]

    def apelidar(self, outra: str, tipo: str, **procedencia: Any) -> bool:
        """Registra `outra` como mais uma chave DESTA mídia. Só com a mídia já nascida.

        Devolve se acrescentou. ⛔ Uma chave que já é de OUTRA pasta nunca vira apelido
        daqui: juntaria duas mídias, e a busca apontaria uma pela outra para sempre.
        """
        pasta = self.achada()
        if pasta is None:
            raise FileNotFoundError(f"{self!r} ainda não nasceu; não há onde apelidar")
        outra = de_umid(outra)
        ind = indice(self.raiz)
        with _trava_do_manifesto, ind.trava:
            dona = ind.primaria(outra)
            if outra == self.chave or dona == self.chave:
                return False
            if dona in ind.mapa:
                log.warning("%s já é de outra mídia (%s); não apelido em %s",
                            outra[:12], dona[:12], pasta.name)
                return False
            manifesto = self._ler_json(pasta / MANIFESTO) or {"esquema": ESQUEMA,
                                                              "chave": self.chave}
            lista = [a for a in manifesto.get("apelidos") or [] if isinstance(a, dict)]
            lista.append({"chave": outra, "tipo": tipo,
                          **{k: v for k, v in procedencia.items() if v is not None},
                          "quando": time.strftime("%Y-%m-%dT%H:%M:%S")})
            manifesto["apelidos"] = lista
            escrever_atomico(pasta / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1)
                             .encode("utf-8"))
            ind.registrar_apelido(outra, self.chave)
        return True

    def desapelidar(self, outra: str) -> bool:
        """Tira `outra` da lista de chaves desta mídia. Devolve se tirou.

        ⭐⭐ Existe por causa da separação dos bancos (2026-09-21): um apelido criado pelo
        casamento por CONTEÚDO fazia o arquivo do Premiere responder pela entrada do Avid,
        e era por ali que o nome da bin e os caminhos de `Avid MediaFiles` vazavam para a
        lista. ⚠️ Tirar um apelido não apaga quadro, vetor nem transcrição de ninguém — o
        pior que acontece é o casamento ser medido de novo, e isso custa segundos.
        """
        pasta = self.achada()
        if pasta is None:
            return False
        outra = de_umid(outra)
        ind = indice(self.raiz)
        with _trava_do_manifesto, ind.trava:
            manifesto = self._ler_json(pasta / MANIFESTO)
            lista = [a for a in manifesto.get("apelidos") or [] if isinstance(a, dict)]
            ficam = [a for a in lista if a.get("chave") != outra]
            if len(ficam) == len(lista):
                return False
            if ficam:
                manifesto["apelidos"] = ficam
            else:
                manifesto.pop("apelidos", None)
            escrever_atomico(pasta / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1)
                             .encode("utf-8"))
            if ind.apelidos.get(outra) == self.chave:
                ind.apelidos.pop(outra, None)
        return True

    def ler_fonte(self) -> dict[str, Any]:
        antiga = self._ler_json(self.arquivo("fonte.json"))
        nova = self._ler_json(self.arquivo(MANIFESTO)).get("fonte")
        if isinstance(nova, dict):
            antiga.update(nova)
        return antiga

    def _ler_json(self, caminho: Path) -> dict[str, Any]:
        """Lê JSON do disco tolerando ausência e corrupção.

        ⚠️ Cache corrompido **não pode derrubar o produto**: um JSON pela metade (queda
        no meio da escrita de uma versão anterior, disco de rede que piscou) vira "não
        tenho isso em cache", que é sempre uma resposta segura. Reprocessar custa
        segundos; estourar custa a conversa do editor.
        """
        try:
            if not caminho.is_file():
                return {}
            if caminho.stat().st_size > MAX_JSON_BYTES:
                log.warning("%s maior que o teto; ignorando", caminho)
                return {}
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning("cache ilegível em %s (%s); tratando como vazio", caminho, e)
            return {}

    # ── quadros ──────────────────────────────────────────────────────────────

    @property
    def quadros(self) -> Path:
        return self.arquivo("quadros")

    def caminho_do_quadro(self, frame_no_master: int) -> Path:
        """O arquivo de um quadro, nomeado pela posição **no tempo do master**.

        ⭐ É esta escolha que faz dois subclipes vizinhos compartilharem a sobreposição.
        Zero à esquerda para o diretório ordenar sozinho na tela de quem for olhar.

        ⚠️ Para LER. Quem grava usa `guardar_quadro`, que faz a pasta nascer.
        """
        return self.quadros / f"{frame_no_master:08d}.jpg"

    def tem_quadro(self, frame_no_master: int) -> bool:
        caminho = self.caminho_do_quadro(frame_no_master)
        try:
            # Arquivo de tamanho zero é resto de uma extração que morreu no meio, e
            # tratá-lo como presente entregaria uma imagem vazia ao modelo.
            return caminho.is_file() and caminho.stat().st_size > 0
        except OSError:
            return False

    def guardar_quadro(self, frame_no_master: int, jpeg: bytes) -> Path:
        destino = self.pasta / "quadros" / f"{frame_no_master:08d}.jpg"
        escrever_atomico(destino, jpeg)
        return destino

    def quadros_guardados(self) -> list[int]:
        if not self.quadros.is_dir():
            return []
        numeros = []
        for arquivo in self.quadros.glob("*.jpg"):
            try:
                numeros.append(int(arquivo.stem))
            except ValueError:
                continue
        return sorted(numeros)

    # ── o que já se sabe sobre o material ────────────────────────────────────

    @property
    def _notas(self) -> Path:
        return self.arquivo("notas.json")

    def ler_notas(self) -> list[dict[str, Any]]:
        """O que já foi observado neste material.

        ⭐ Mora junto dos quadros, e pela mesma razão: **é conhecimento sobre o MASTER**.
        Descrever um take é descrever um pedaço daquela mídia, e o pedaço não deixa de
        existir quando o subclipe é refeito. Um groupclipe de multicam montado depois
        encontra a descrição pronta.

        ⛔⛔ **MEDIDO em 2026-09-19 (Assist anterior) e reproduzido aqui em 2026-09-20:** 4 de
        332 `notas.json` eram a **lista crua**, não `{"notas": [...]}` — gravados assim pelo
        nosso `tools/consertar_quadros.py` em 17/09 (o defeito do gravador está consertado).
        Um arquivo desses derrubava a aba Vetores INTEIRA com
        `'list' object has no attribute 'get'`: a tela dizia "0 mídias" com o disco cheio.
        ⇒ Os dois formatos valem na LEITURA, e os arquivos do cache não são tocados.
        """
        dados = self._ler_json(self._notas)
        if isinstance(dados, list):
            return [n for n in dados if isinstance(n, dict)]
        notas = dados.get("notas") if isinstance(dados, dict) else None
        return notas if isinstance(notas, list) else []

    def anotar(self, nota: dict[str, Any]) -> None:
        """Acrescenta uma observação, substituindo a anterior do mesmo trecho.

        ⚠️ Substituir em vez de acumular: reanotar o mesmo take significa que a leitura
        anterior estava incompleta ou errada, e guardar as duas faria o Claude ler
        descrições contraditórias do mesmo material sem saber qual vale.
        """
        chave = (nota.get("trecho") or "").strip()
        notas = [n for n in self.ler_notas() if (n.get("trecho") or "").strip() != chave]
        notas.append(nota)
        notas.sort(key=lambda n: n.get("inicio_frames") or 0)
        escrever_atomico(
            self.pasta / "notas.json",
            json.dumps({"notas": notas}, ensure_ascii=False, indent=1).encode("utf-8"),
        )

    # ── transcrição ──────────────────────────────────────────────────────────

    @property
    def _transcricao(self) -> Path:
        return self.arquivo("transcricao.json")

    def ler_transcricao(self) -> list[dict[str, Any]]:
        """As falas do master INTEIRO, em segundos do master.

        ⭐ Mesma regra dos quadros: transcreveu uma vez, e qualquer recorte daquele áudio
        acha pronto — inclusive um groupclipe de multicam montado depois. Recortar a
        janela do subclipe é conta de lista; passar o áudio pelo ASR de novo não é.
        """
        dados = self._ler_json(self._transcricao)
        falas = dados.get("falas")
        return falas if isinstance(falas, list) else []

    def tem_transcricao(self) -> bool:
        return self._transcricao.is_file()

    def guardar_transcricao(self, falas: list[dict[str, Any]]) -> None:
        escrever_atomico(
            self.pasta / "transcricao.json",
            json.dumps({"falas": falas}, ensure_ascii=False, indent=1).encode("utf-8"),
        )

    @property
    def audio(self) -> Path:
        """O WAV de trabalho. Fica no cache porque montá-lo custa segundos e ele serve
        para refazer a transcrição com outro modelo sem tocar nos `.mxf` de novo."""
        return self.pasta / "audio.wav"

    # ── assinatura do gerador ────────────────────────────────────────────────

    def precisa_refazer(self, estagio: str, assinatura: dict[str, Any]) -> bool:
        """O que está em cache foi feito com ESTES parâmetros?

        ⭐ É o que permite melhorar o produto sem invalidar tudo à mão: mudou a largura
        do frame ou a qualidade do JPEG, os quadros antigos deixam de servir sozinhos.
        Sem isto, um cache velho entrega silenciosamente resultado de uma versão que já
        não existe — e a diferença aparece como comportamento inexplicável, não como erro.
        """
        gravada = self._ler_json(self.arquivo(f"gerador.{estagio}.json"))
        return gravada != assinatura

    def ler_gerador(self, estagio: str) -> dict[str, Any]:
        """Com que receita este estágio foi feito. `{}` quando nunca foi feito.

        ⭐ É a coluna "modelo" da aba Vetores: o que está gravado aqui é a assinatura de
        quem produziu o que está em disco — não a receita de hoje. As duas juntas são o
        que responde "atualizado?".
        """
        return self._ler_json(self.arquivo(f"gerador.{estagio}.json"))

    def registrar_gerador(self, estagio: str, assinatura: dict[str, Any]) -> None:
        escrever_atomico(
            self.pasta / f"gerador.{estagio}.json",
            json.dumps(assinatura, ensure_ascii=False, indent=1).encode("utf-8"),
        )

    #: ⛔⛔ O que uma entrada COPIA de outra quando os bancos se cruzam, e o que NÃO copia.
    #:
    #: Fora da lista, de propósito: **`audio.wav`**. Medido neste cache em 2026-09-21 —
    #: 1.994 MB de 2.079, ou seja **96% do cache** —, e ele é arquivo de TRABALHO,
    #: regenerável do próprio arquivo deste banco se um dia alguém refizer a transcrição.
    #: Copiar o resto custa 85 MB para as 332 mídias, ~256 KB por entrada.
    #:
    #: Fora da lista também: o `midia.json`. A identidade é DESTA entrada — o nome, os
    #: arquivos e a origem são dela, e é justamente isso que separa os bancos.
    #:
    #: ⭐⭐ `cortes.json` entra aqui (2026-09-22): ele é a coisa mais CARA do cache em tempo
    #: de gente — as horas de Mac da decupagem micro saem dele, e as posições são quadros do
    #: MASTER, que é o que a porteira do casamento garante ser o mesmo dos dois lados.
    COPIAVEIS = ("quadros", "vetores.npy", "vetores.json", "transcricao.json",
                 "cortes.json", "notas.json", "falantes.json")

    def copiar_de(self, outra: "Midia", medida: float = 0.0,
                  fonte: str = "") -> list[str]:
        """Aproveita o que `outra` já produziu, sem reprocessar. Devolve o que foi copiado.

        ⭐⭐ **É o cruzamento entre os bancos** (decisão do editor, 2026-09-21): quando uma
        mídia importada no Premiere casa, por CONTEÚDO, com algo que o Media Composer já
        analisou, a entrada nova nasce aqui e copia o trabalho em vez de refazê-lo.

        ⭐ Os quadros podem ser copiados porque a porteira do casamento (`identidade
        .e_candidato`) exige **mesma taxa, mesmo TC de início e mesmo número de quadros**:
        o quadro N de lá é o quadro N daqui. Sem essa exigência a cópia deslocaria tudo.

        ⚠️ **No SOM a porteira é mais frouxa** — nome e duração com folga de 0,1 s —, e o
        OP-Atom do Avid começa 398 amostras (8 ms) depois do WAV, medido em 2026-09-17.
        A transcrição copiada pode estar deslocada disso. É abaixo de um quadro, e a
        procedência registra de quem veio para que dê para auditar.
        """
        de = outra.achada()
        if de is None:
            return []
        destino = self.pasta
        copiados: list[str] = []
        for nome in self.COPIAVEIS:
            origem_ = de / nome
            if not origem_.exists():
                continue
            if nome == "notas.json":
                if self._copiar_notas_do_master(outra):
                    copiados.append(nome)
                continue
            alvo = destino / nome
            try:
                if origem_.is_dir():
                    shutil.copytree(origem_, alvo, dirs_exist_ok=True)
                else:
                    shutil.copy2(origem_, alvo)
            except OSError as e:
                log.warning("não consegui copiar %s de %s: %s", nome, de.name, e)
                continue
            copiados.append(nome)
        # ⭐ A RECEITA vai junto, e sem ela a cópia não serve para nada: `precisa_refazer`
        #   compararia contra `{}` e a fila refaria tudo na primeira passada.
        for estagio in ("quadros", "transcricao", "vetores", "cortes"):
            receita = outra.ler_gerador(estagio)
            if receita:
                self.registrar_gerador(estagio, receita)
        # ⚠️ A procedência é gravada MESMO sem nada a copiar: o casamento é um fato, e
        #   `copiados: []` diz exatamente o que aconteceu — "é a mesma mídia, e não havia
        #   trabalho pronto lá". Gravar só quando copia esconderia por que esta entrada
        #   nasceu, que é a pergunta de quem for auditar.
        self.anotar_procedencia_da_copia(outra, medida, fonte, copiados)
        return copiados

    #: Os escopos de nota que descrevem o MASTER, e por isso atravessam de um banco para o
    #: outro. Fora daqui fica `take` — a nota escrita numa conversa sobre um SUBCLIPE.
    ESCOPOS_DO_MASTER = ("midia", "trecho")

    def _copiar_notas_do_master(self, outra: "Midia") -> bool:
        """Só a nota do MASTER atravessa — e com o nome DESTE banco.

        ⛔⛔ **Subclipe e multicam não atravessam** (decisão do editor, 2026-09-22): *"o
        cruzamento dos bancos deve ser só dos masters, e não dos subclipes/multicam — são
        elementos que cada software fará diferente e não coexistirão em outra plataforma"*.
        MEDIDO no cache dele: a busca do Premiere mostrava `C07_P03-T001` — o nome de um
        subclipe do AVID, vindo de uma nota de take escrita numa conversa do Media Composer
        — e o duplo clique abria a diária de câmera inteira.

        ⭐⭐ **A nota de TRECHO atravessa** (2026-09-22), e é a que mais importa: ela é a
        decupagem MICRO, e cada uma custou ~50 s a ~87 s de Mac. Ela descreve um pedaço do
        MASTER, em quadros do master — o mesmo motivo que deixa os quadros e os vetores
        atravessarem. Sem isto, a entrada do Premiere refazia horas de trabalho já feito,
        em silêncio, e o mesmo material ganhava duas leituras diferentes.

        ⛔ E o `trecho` da nota é o nome do master NA BIN DO AVID (`a002_03170703_C003`):
        vira o título do cartão. Por isso ele é reescrito com o nome desta entrada — na de
        trecho, no mesmo formato de `motor.micro.chave_do_trecho`, senão uma micro refeita
        deste lado gravaria uma SEGUNDA nota para o mesmo trecho em vez de substituí-la.
        """
        mestras = [n for n in outra.ler_notas()
                   if n.get("escopo") in self.ESCOPOS_DO_MASTER]
        if not mestras:
            return False
        minhas = [n for n in self.ler_notas()
                  if n.get("escopo") not in self.ESCOPOS_DO_MASTER]
        nome = self.nome or self.chave[:12]
        for n in mestras:
            chave = (f"{nome} · trecho {n['inicio_frames']}"
                     if n.get("escopo") == "trecho" and n.get("inicio_frames") is not None
                     else nome)
            minhas.append({**n, "trecho": chave, "copiada_de": outra.origem})
        escrever_atomico(
            self.pasta / "notas.json",
            json.dumps({"notas": minhas}, ensure_ascii=False, indent=1).encode("utf-8"))
        return True

    def anotar_procedencia_da_copia(self, outra: "Midia", medida: float,
                                    fonte: str, copiados: list[str]) -> None:
        """De quem esta entrada aproveitou, e com que medida. ⚠️ Procedência em todo item
        é regra da casa: sem ela ninguém saberia que a transcrição daqui foi feita sobre
        OUTRO arquivo."""
        pasta = self.achada()
        if pasta is None:
            return
        with _trava_do_manifesto:
            manifesto = self._ler_json(pasta / MANIFESTO)
            manifesto["aproveitado_de"] = {
                "chave": outra.chave,
                "nome": outra.nome,
                "origem": outra.origem,
                "copiados": list(copiados),
                "confianca": "confirmado" if medida else "inferido",
                "fonte": fonte or "conteudo",
                "medida": round(float(medida), 4) if medida else "",
                "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            escrever_atomico(pasta / MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=1)
                             .encode("utf-8"))

    def limpar_estagio(self, estagio: str) -> None:
        """Joga fora o que um estágio produziu. Usado quando a assinatura mudou."""
        if estagio == "quadros" and self.existe and self.quadros.is_dir():
            for arquivo in self.quadros.glob("*.jpg"):
                arquivo.unlink(missing_ok=True)
