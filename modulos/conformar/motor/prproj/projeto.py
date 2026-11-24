"""O `.prproj` carregado: texto cru + índice dos objetos de topo. Só leitura.

O XML do Premiere é um grafo plano: cada objeto é filho direto de `<PremiereData>`, indentado
com UM tab, identificado por `ObjectID` (numérico) e/ou `ObjectUID` (uuid); as referências são
`ObjectRef` → `ObjectID` e `ObjectURef` → `ObjectUID`. Indexar os spans no texto (em vez de um
parser de XML) cabe em memória mesmo num projeto de 850 MB descompactado, e é a técnica que o
RELINK_PRODUCAO-G validou (banco: `protocolos/prproj/relink-e-geometria.md`).
"""
from __future__ import annotations

import gzip
import re

#: Ticks por segundo do Premiere (exato). Banco: `protocolos/prproj/dados/ticks.json`.
TPS = 254016000000

_INICIO = re.compile(r"\n\t<([A-Za-z0-9_.]+)([^>]*)>")


class Obj:
    __slots__ = ("tag", "oid", "uid", "ini", "fim")

    def __init__(self, tag, oid, uid, ini, fim):
        self.tag, self.oid, self.uid, self.ini, self.fim = tag, oid, uid, ini, fim

    def __repr__(self):
        return f"<{self.tag} {self.oid or self.uid}>"


class Projeto:
    def __init__(self, caminho: str):
        self.caminho = caminho
        with gzip.open(caminho, "rb") as fh:
            self.texto = fh.read().decode("utf-8", "replace")
        self.objetos: list[Obj] = []
        self._por_id: dict[str, Obj] = {}
        self._binarios: dict[str, str] | None = None     # BinaryHash → base64 (`valor_inicial`)
        t = self.texto
        for m in _INICIO.finditer(t):
            tag, attrs = m.group(1), m.group(2)
            if attrs.endswith("/"):
                continue
            fim = t.find("\n\t</%s>" % tag, m.end())
            if fim < 0:
                continue
            oid = re.search(r'ObjectID="(\d+)"', attrs)
            uid = re.search(r'ObjectUID="([^"]+)"', attrs)
            o = Obj(tag, oid.group(1) if oid else None, uid.group(1) if uid else None,
                    m.end(), fim)
            self.objetos.append(o)
            # ObjectID repetido existe (espaços de nome separados, escrita.md §8): vale o 1º.
            for k in (o.oid, o.uid):
                if k and k not in self._por_id:
                    self._por_id[k] = o

    # ---- leitura -------------------------------------------------------
    def corpo(self, o: Obj) -> str:
        return self.texto[o.ini:o.fim]

    def valor_inicial(self, prm: Obj) -> str | None:
        """O `StartKeyframeValue` binário (base64) de um parâmetro — inclusive quando o Premiere o
        guardou em OUTRO lugar do arquivo.

        ⛔ MEDIDO 2026-10-04 (Premiere 26.0.2, `FINALIZACAOPRODB_FINALIZACAO_PARA RESOLVE.prproj`): um
        blob igual é gravado UMA vez; as outras ocorrências vêm vazias, só com o `BinaryHash`
        (`<StartKeyframeValue Encoding="base64" BinaryHash="1660e736…"/>`). Lendo só o conteúdo do
        próprio parâmetro, as 13 cartelas do filme (o crédito final duplicado de outra sequência) saíam
        "gráfico sem tradução" — e uma máscara duplicada sumiria igual. No projeto: 326 vazios, todos
        com o conteúdo em outro lugar (o antigo: 401)."""
        m = re.search(r"<StartKeyframeValue([^>]*?)(?:/>|>([^<]*)<)", self.corpo(prm))
        if not m:
            return None
        if (m.group(2) or "").strip():
            return m.group(2).strip()
        h = re.search(r'BinaryHash="([^"]+)"', m.group(1))
        if not h:
            return None
        if self._binarios is None:
            self._binarios = {}
            for b in re.finditer(r'BinaryHash="([^"]+)">([^<]+)<', self.texto):
                self._binarios.setdefault(b.group(1), b.group(2).strip())
        return self._binarios.get(h.group(1))

    def obj(self, ref: str | None) -> Obj | None:
        return self._por_id.get(ref) if ref else None

    def refs(self, o: Obj, tag: str) -> list[Obj]:
        """Objetos apontados por `<tag … ObjectRef|ObjectURef="…"/>` dentro de `o`, em ordem."""
        achados = re.findall(r'<%s\b[^>]*Object(?:U)?Ref="([^"]+)"' % re.escape(tag), self.corpo(o))
        return [x for x in (self.obj(r) for r in achados) if x is not None]

    def ref(self, o: Obj, tag: str) -> Obj | None:
        r = self.refs(o, tag)
        return r[0] if r else None

    def campos_numerados(self, o: Obj, prefixo: str) -> list[tuple[int, str]]:
        """`<Prefixo0>…</Prefixo0>`, `<Prefixo1>…` (o `MediaFileHistoryN` do `Media`), em ordem."""
        achados = re.findall(r"<%s(\d+)>([^<]*)</%s\1>" % (re.escape(prefixo), re.escape(prefixo)), self.corpo(o))
        return sorted((int(n), _desescapar(v)) for n, v in achados)

    def campo(self, o: Obj, tag: str) -> str | None:
        m = re.search(r"<%s>([^<]*)</%s>" % (re.escape(tag), re.escape(tag)), self.corpo(o))
        # o texto do XML vem escapado: um arquivo "doors &amp; closing.wav" não existe no disco
        # (medido 2026-10-04: 4 efeitos sonoros do PRODB davam "inexistente" por isso)
        return _desescapar(m.group(1)) if m else None

    def de_tipo(self, tag: str) -> list[Obj]:
        return [o for o in self.objetos if o.tag == tag]

    def versao(self) -> str | None:
        """`MZ.BuildVersion.Modified`: quem GRAVOU o arquivo (o `Created` quase sempre é outro)."""
        m = re.search(r"<MZ\.BuildVersion\.Modified>([^<]*)<", self.texto)
        return m.group(1) if m else None

    def nome_da_sequencia(self, s: Obj) -> str:
        m = re.search(r"\n\t\t<Name>([^<]*)</Name>", self.corpo(s))
        return _desescapar(m.group(1)) if m else (self.campo(s, "Name") or "")


def _desescapar(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))
