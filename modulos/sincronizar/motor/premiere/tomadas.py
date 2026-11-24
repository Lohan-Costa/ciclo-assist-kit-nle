"""A sequência sincronizada do Premiere → os merged clips a criar.

O par do `avid/takes.takes_da_sequencia`, com o gesto trocado: no Avid o editor ARRASTA
a timeline para o painel; no Premiere não há arrasto da bin (medido no CEP, nos dois
sistemas), então o painel lê a SEQUÊNCIA ATIVA —
decisão do autor, 2026-09-16.

## A unidade é o CLIPE DE CÂMERA, não a janela de som

No Avid um subclipe pode carregar várias trilhas de imagem (revezamento de câmeras).
Um merged clip do Premiere é **um** vídeo mais o som, então aqui a unidade é cada
clipe de câmera da sequência, pareado com o som direto que mais o cobre. É a mesma
unidade de `ExportOptions.merged_clips` no builder (um merged por câmera de tomada).

## Aparado, como no Avid

Decisão do autor, 2026-09-16: o merged sai **aparado onde imagem e som coexistem** —
sem preto nem som sobrando nas pontas. Este módulo calcula o recorte (`corte_in` /
`corte_out`, em segundos DO ARQUIVO DE CÂMERA); quem o aplica é a escrita.

## Câmera × som direto, sem metadado

A sequência que o Órbita monta põe o som direto nas primeiras trilhas de áudio e,
opcionalmente, o áudio da câmera depois. Aqui não se depende dessa ordem: **um item de
áudio cujo arquivo também aparece como vídeo é som de câmera**; o resto é som direto.

## O formato de entrada

O de `sincGetTimelineSelection()` no `host.jsx`, uma linha por clipe:
`V|A \\t track \\t índice \\t início \\t inPoint \\t duração \\t selecionado \\t caminho`,
tempos em SEGUNDOS.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PureWindowsPath

import registro

from avid.takes import Tomada, Trecho, _batizar_orfaos, presumir_pela_forma
from media import identidade as _identidade

log = registro.log(__name__)

#: Tolerância para dizer que dois itens do mesmo som estão na mesma posição de sync:
#: meio frame a 60 fps. Arredondamento de segundos do ExtendScript, não edição.
_TOLERANCIA_S = 1 / 120


@dataclass(frozen=True)
class Item:
    """Um clipe da sequência, como o host o descreve."""
    kind: str          # "V" | "A"
    track: int
    index: int
    start: float       # na timeline, segundos
    in_point: float    # dentro do arquivo, segundos
    duration: float
    selected: bool
    path: str

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def origem(self) -> float:
        """Onde o SEGUNDO ZERO do arquivo cai na timeline."""
        return self.start - self.in_point


@dataclass(frozen=True)
class Par:
    """Um merged a criar: um clipe de câmera e o som direto que o cobre.

    ⭐ `som` vazio = clipe solto (autor, 2026-11-08): sem som direto, sai como subclipe, igual ao órfão do Avid."""
    camera: str
    som: str
    #: Onde o segundo zero do SOM cai, medido no relógio do arquivo de CÂMERA. É o
    #: deslocamento de sync que o builder pede (câmera começa `-offset` depois do som).
    som_no_relogio_da_camera: float
    #: O recorte, em segundos DO ARQUIVO DE CÂMERA.
    corte_in: float
    corte_out: float
    tomada: Tomada


def ler_registros(texto: str) -> list[Item]:
    """O texto do host → itens. Linha malformada é descartada, não derruba a leitura."""
    itens: list[Item] = []
    for linha in (texto or "").splitlines():
        campos = linha.split("\t")
        if len(campos) < 8 or campos[0] not in ("V", "A"):
            continue
        try:
            itens.append(Item(
                kind=campos[0], track=int(campos[1]), index=int(campos[2]),
                start=float(campos[3]), in_point=float(campos[4]),
                duration=float(campos[5]), selected=campos[6] == "1",
                # O caminho é o ÚLTIMO campo e o único que poderia conter TAB.
                path="\t".join(campos[7:])))
        except ValueError:
            continue
    return itens


def _nome_de_arquivo(caminho: str) -> str:
    """O nome do arquivo, com a extensão — é o que a bin do Premiere mostra.

    ⚠️ `PureWindowsPath` aceita as duas barras; um caminho do macOS lido no Windows (ou o
    contrário) não pode virar o caminho inteiro por falta de separador reconhecido.
    """
    return PureWindowsPath(caminho).name


@dataclass
class _Som:
    """Um som direto numa posição de sync — os N canais somados."""
    path: str
    origem: float
    intervalos: list[tuple[float, float]]
    usado: bool = False

    def cobertura(self, a: float, b: float) -> tuple[float, float, float]:
        """(total coberto, primeiro instante, último instante) dentro de [a, b)."""
        total, ini, fim = 0.0, None, None
        for s, e in self.intervalos:
            x, y = max(a, s), min(b, e)
            if y > x:
                total += y - x
                ini = x if ini is None else min(ini, x)
                fim = y if fim is None else max(fim, y)
        return total, (ini if ini is not None else a), (fim if fim is not None else a)


def _sons_diretos(itens: list[Item]) -> list[_Som]:
    de_video = {i.path for i in itens if i.kind == "V"}
    sons: list[_Som] = []
    for it in sorted((i for i in itens if i.kind == "A" and i.path not in de_video),
                     key=lambda i: (i.start, i.track)):
        alvo = next((s for s in sons if s.path == it.path
                     and abs(s.origem - it.origem) <= _TOLERANCIA_S), None)
        if alvo is None:
            alvo = _Som(it.path, it.origem, [])
            sons.append(alvo)
        alvo.intervalos.append((it.start, it.end))
    return sons


def completar_colunas(itens: list[Item], colunas: dict, sondar=None) -> dict:
    """Para o som cujo NOME não diz a cena, as tags do próprio arquivo fazem o papel da coluna `Scene`/`Take` da bin do Avid.

    ⭐ Sem isto, `18-1T01.WAV` saía sem cena no Premiere, com a cena escrita no arquivo. Só quem o nome não resolve paga a leitura
    (cacheada em disco). Arquivo ilegível fica como estava."""
    from media import claquete as _claquete
    if sondar is None:
        from media.inspector import probe as sondar
    saida = dict(colunas or {})
    de_video = {i.path for i in itens if i.kind == "V"}
    for caminho in {i.path for i in itens if i.kind == "A" and i.path not in de_video}:
        nome = _nome_de_arquivo(caminho)
        if nome in saida or _claquete.ler(nome) is not None:
            continue
        try:
            meta = sondar(caminho) or {}
        except Exception as e:  # noqa: BLE001 — sem a tag, o clipe só fica sem cena
            log.debug("sem tags de %r: %s", caminho, e)
            continue
        if meta.get("scene") and meta.get("take"):
            saida[nome] = {"Scene": str(meta["scene"]), "Take": str(meta["take"])}
    return saida


def pares(itens: list[Item], fps: float, colunas: dict | None = None,
          so_selecionados: bool = False) -> tuple[list[Par], dict]:
    """Os merged a criar, em ordem de timeline, e um resumo do que ficou de fora.

    Args:
        itens: a sequência inteira (`ler_registros`).
        fps: da SEQUÊNCIA — as durações da `Tomada` são em frames dela.
        colunas: `{nome do arquivo de som → {coluna: valor}}`, da bin do Premiere.
        so_selecionados: considerar só as câmeras selecionadas na timeline.

    Returns:
        `(pares, resumo)`, com `resumo = {"orfaos_de_camera", "orfaos_de_som",
        "disputados"}` — `disputados` conta câmeras cobertas por mais de um som
        (ficam com o que mais cobre).
    """
    if fps <= 0:
        raise ValueError("fps da sequência inválido")
    colunas = colunas or {}
    sons = _sons_diretos(itens)
    cameras = sorted((i for i in itens if i.kind == "V" and i.path
                      and (i.selected or not so_selecionados)),
                     key=lambda i: (i.start, i.track))

    def frames(segundos: float) -> int:
        return int(round(segundos * fps))

    saida: list[Par] = []
    posicoes: list[int] = []
    orfaos_cam = disputados = 0
    for cam in cameras:
        candidatos = []
        for s in sons:
            total, ini, fim = s.cobertura(cam.start, cam.end)
            if total > _TOLERANCIA_S:
                candidatos.append((total, s, ini, fim))
        if not candidatos:
            orfaos_cam += 1
            posicoes.append(frames(cam.start))
            nome_cam = _nome_de_arquivo(cam.path)
            duracao = frames(cam.duration)
            saida.append(Par(camera=cam.path, som="", som_no_relogio_da_camera=0.0,
                             corte_in=cam.in_point, corte_out=cam.in_point + cam.duration, tomada=Tomada(
                nome=nome_cam, cena=None, plano=None, take=None, convencao=None, edit_rate=float(fps),
                duracao=duracao, duracao_bruta=duracao,
                trechos=(Trecho(mob_id=cam.path, track_id=1, media_kind="picture", start=frames(cam.in_point),
                                length=duracao, trilha_de_origem=cam.track + 1),),
                origem="sequencia", nome_do_som="", nome_do_video=nome_cam, orfao=True)))
            continue
        if len(candidatos) > 1:
            disputados += 1
        # O que mais cobre; empate → o que começa antes na timeline (ordem estável).
        candidatos.sort(key=lambda c: (-c[0], c[1].origem))
        _total, som, a, b = candidatos[0]
        som.usado = True
        posicoes.append(frames(cam.start))

        corte_in = cam.in_point + (a - cam.start)
        corte_out = cam.in_point + (b - cam.start)
        nome_cam = _nome_de_arquivo(cam.path)
        nome_som = _nome_de_arquivo(som.path)
        ident = _identidade.de_clipe(nome_som, nome_som, colunas.get(nome_som) or {})
        duracao = frames(b - a)
        tomada = Tomada(
            nome=nome_cam,
            cena=ident.cena, plano=ident.plano, take=ident.take,
            convencao=ident.convencao,
            episodio=ident.episodio,
            edit_rate=float(fps),
            duracao=duracao,
            # ⭐ O "bruto" aqui é o clipe de câmera como está na sequência: o que o
            # aparo tirou dele é o que o editor precisa ver antes de gerar.
            duracao_bruta=frames(cam.duration),
            trechos=(
                Trecho(mob_id=som.path, track_id=1, media_kind="sound",
                       start=frames(a - som.origem), length=duracao),
                Trecho(mob_id=cam.path, track_id=1, media_kind="picture",
                       start=frames(corte_in), length=duracao,
                       trilha_de_origem=cam.track + 1),
            ),
            origem="sequencia",
            nome_do_som=nome_som,
            nome_do_video=nome_cam,
        )
        saida.append(Par(
            camera=cam.path, som=som.path,
            som_no_relogio_da_camera=som.origem - cam.origem,
            corte_in=corte_in, corte_out=corte_out, tomada=tomada))

    # ⭐ A cena do solto é presumida pelos vizinhos: a MESMA regra do Avid, com a mesma marca (`convencao="posicao"`).
    if saida:
        presumidas = presumir_pela_forma([p.tomada for p in saida])
        batizados = _batizar_orfaos(list(zip(posicoes, presumidas)))
        saida = [replace(p, tomada=t) for p, (_, t) in zip(saida, batizados)]

    resumo = {"orfaos_de_camera": orfaos_cam,
              "orfaos_de_som": sum(1 for s in sons if not s.usado),
              "disputados": disputados}
    log.info("%d merged a criar da sequência (%s)", len(saida), resumo)
    return saida, resumo


def nomes_por_caminho(lista: list[Par]) -> dict[str, str]:
    """`{caminho → nome}`, o `nomes_por_mob` que `avid.nomear.ficha` espera."""
    out: dict[str, str] = {}
    for p in lista:
        out[p.camera] = _nome_de_arquivo(p.camera)
        if p.som:
            out[p.som] = _nome_de_arquivo(p.som)
    return out
