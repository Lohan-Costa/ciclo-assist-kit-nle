"""Migrar o cache de pastas `060a2b34…` para pastas de nome legível — sem reprocessar nada.

Spec: `docs/spec/2026-09-13-cache-legivel-e-compartilhado.md` §7.

Para cada pasta antiga (64 hexadecimais, sem `midia.json`):

1. o rótulo sai do que já se sabe — a varredura do acervo (`material_package_name`, taxa,
   duração, se tem imagem) e o `fonte.json` da própria pasta;
2. a data do nome é a de CRIAÇÃO da pasta antiga: é quando o cache daquela mídia nasceu de
   verdade, e a migração não pode fingir que tudo nasceu hoje;
3. a pasta é COPIADA para o nome novo, com o manifesto, e a antiga vai para
   `_antes_da_migracao/` — que o índice ignora e o editor apaga quando tiver conferido.

⛔ Copiar e só então mover, e não renomear: se a cópia falhar no meio, a antiga continua
onde estava e o cache continua funcionando pelo caminho de antes.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from . import cache as _cache

log = logging.getLogger("cicloassist.midia.migracao")

COPIA = "_antes_da_migracao"


def _rotulo(antiga: Path, raiz: Path) -> dict[str, Any]:
    m = _cache.Midia(antiga.name, raiz_do_cache=raiz)
    rotulo = m._rotulo_completo()
    fonte = _cache._ler_json_em(antiga / "fonte.json")
    if not rotulo.get("nome"):
        rotulo["nome"] = fonte.get("master") or fonte.get("master_de_som") or ""
    if not rotulo.get("tipo"):
        if fonte.get("master") or (antiga / "quadros").is_dir():
            rotulo["tipo"] = "video"
        elif fonte.get("master_de_som") or (antiga / "transcricao.json").is_file():
            rotulo["tipo"] = "audio"
    if not rotulo.get("arquivos") and fonte.get("arquivo"):
        rotulo["arquivos"] = [fonte["arquivo"]]
    if rotulo.get("arquivos") and not (rotulo.get("duracao_s") and
                                       (rotulo.get("fps") or rotulo.get("amostragem"))):
        # ⚠️ O acervo guardado antes da sonda v3 tem duração ZERO em todo áudio. Uma sonda
        #    de um arquivo por mídia (~60 ms) completa o nome sem esperar outra varredura.
        from . import acervo as _acervo
        for arquivo in rotulo["arquivos"][:1]:
            try:
                sonda = _acervo._sondar(Path(arquivo)) or {}
            except Exception:  # noqa: BLE001 — sem ffprobe, o nome sai mais curto
                sonda = {}
            for campo in ("duracao_s", "fps", "amostragem"):
                if sonda.get(campo) and not rotulo.get(campo):
                    rotulo[campo] = sonda[campo]
    return rotulo


def planejar(raiz: Path | None = None) -> list[dict[str, Any]]:
    """O que a migração faria. Não toca em nada."""
    onde = Path(raiz or _cache.raiz())
    plano = []
    try:
        itens = sorted(onde.iterdir())
    except OSError:
        return []
    for antiga in itens:
        if not antiga.is_dir() or not _cache.e_chave(antiga.name) \
                or (antiga / _cache.MANIFESTO).is_file():
            continue
        rotulo = _rotulo(antiga, onde)
        st = antiga.stat()
        # ⚠️ `st_ctime` só é CRIAÇÃO no Windows; no macOS é a última mudança de inode, e a
        #    pasta seria batizada com a data da última escrita (medido 2026-09-14).
        nasceu = getattr(st, "st_birthtime", st.st_ctime)
        plano.append({
            "chave": antiga.name,
            "antiga": antiga,
            "nova": onde / _cache.nome_da_pasta(antiga.name, rotulo, nasceu),
            "rotulo": rotulo,
            "nasceu": nasceu,
        })
    return plano


def migrar(raiz: Path | None = None) -> dict[str, Any]:
    """Faz. ⚠️ Com o serviço PARADO: um turno gravando no meio seria gravado na antiga."""
    onde = Path(raiz or _cache.raiz())
    feitas, falhas = [], []
    for item in planejar(onde):
        antiga, nova, rotulo = item["antiga"], item["nova"], item["rotulo"]
        criada = False
        try:
            if nova.exists():
                raise FileExistsError(f"{nova.name} já existe")
            criada = True
            shutil.copytree(antiga, nova)
            fonte = _cache._ler_json_em(nova / "fonte.json")
            manifesto = {
                "esquema": _cache.ESQUEMA,
                "chave": item["chave"],
                "identidades": {"umid": item["chave"]},
                "nome": rotulo.get("nome") or "",
                "fps": _cache.texto_do_fps(rotulo.get("fps")),
                "tipo": rotulo.get("tipo") or "",
                "duracao_s": rotulo.get("duracao_s") or 0,
                "amostragem": rotulo.get("amostragem") or 0,
                "arquivos": [str(a) for a in rotulo.get("arquivos") or []],
                "nasceu": time.strftime("%Y-%m-%dT%H:%M:%S",
                                        time.localtime(item["nasceu"])),
                "pasta": nova.name,
                "migrada_de": antiga.name,
            }
            if fonte:
                manifesto["fonte"] = fonte
            _cache.escrever_atomico(nova / _cache.MANIFESTO,
                                    json.dumps(manifesto, ensure_ascii=False, indent=1)
                                    .encode("utf-8"))
            (nova / "fonte.json").unlink(missing_ok=True)
            destino = onde / COPIA / antiga.name
            destino.parent.mkdir(exist_ok=True)
            shutil.move(str(antiga), str(destino))
            _cache.indice(onde).registrar(item["chave"], nova)
            feitas.append(nova.name)
        except OSError as e:
            # A antiga continua no lugar: o cache segue funcionando por ela.
            # ⛔ Só apaga a nova se foi ESTA rodada que a criou. `FileExistsError` é um
            #    `OSError`: sem a marca, a pasta que já existia seria apagada aqui.
            if criada and nova.exists() and antiga.exists():
                shutil.rmtree(nova, ignore_errors=True)
            falhas.append(f"{antiga.name[:16]}…: {e}")
            log.warning("migração de %s falhou: %s", antiga.name, e)
    return {"feitas": feitas, "falhas": falhas}
