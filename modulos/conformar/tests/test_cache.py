"""Cache e logs (organograma aprovado pelo autor em 2026-10-05): uma regra, um teste.

Rodar:

    .venv/bin/python tests/test_cache.py        (Windows: .venv-win/Scripts/python)

- três lugares: dados, cache (padrão por SO, ou o escolhido) e logs — e, com os dados desviados
  (testes), o cache e os logs vão junto, nunca para a pasta real do usuário;
- o local escolhido: só caminho absoluto local (UNC e relativo voltam ao padrão); disco que não
  está aqui → o padrão; trocar não move nada (o novo começa vazio);
- limpar só mexe nas subpastas do app; a pasta escolhida pode ter coisas do editor;
- o teto é LRU POR UNIDADE (a conferência sai inteira; o DRT sai com o `.midias.json`), e pula as
  protegidas; `tocar` renova;
- o cache antigo (pasta de dados) é avisado, apagado ou dispensado — `partidas/` nunca;
- as rotas: nada se limpa no meio de um trabalho; pastas se abrem só pelo nome;
- o log: um arquivo, cabeçalho de ambiente, rotação que não derruba nada.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import plataforma  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def _arquivo(p: Path, n: int, idade_s: float = 0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)
    if idade_s:
        t = time.time() - idade_s
        os.utime(p, (t, t))
    return p


def _erro(f):
    try:
        f()
    except Exception as e:  # noqa: BLE001
        return type(e).__name__
    return None


def main() -> int:
    real = plataforma.pasta_dados()
    real_cache, real_logs = plataforma.pasta_cache_padrao(), plataforma.pasta_logs()
    print("três lugares")
    ok("⭐ o cache padrão mora na pasta do Ciclo Assist (2026-11-07): <CicloAssist>/conformar/cache",
       real_cache, plataforma.pasta_do_ciclo_assist() / "conformar" / "cache")
    ok("⭐ os logs moram na pasta do Ciclo Assist (2026-11-07): <CicloAssist>/logs/conformar",
       real_logs, plataforma.pasta_do_ciclo_assist() / "logs" / "conformar")

    print("os logs antigos vão para o arquivo")
    with tempfile.TemporaryDirectory() as tmp:
        antiga, nova = Path(tmp) / "antiga", Path(tmp) / "nova"
        antiga.mkdir()
        for n in ("delapraca.log", "pilhas.txt", "aro_servidor.log"):
            (antiga / n).write_text(n, encoding="utf-8")
        guardados = (plataforma._logs_antigos, plataforma.pasta_logs, plataforma._dados_desviados)
        plataforma._logs_antigos, plataforma.pasta_logs = (lambda: antiga), (lambda: nova)
        plataforma._dados_desviados = lambda: None
        try:
            movidos = plataforma.arquivar_logs_antigos()
            de_novo = plataforma.arquivar_logs_antigos()
        finally:
            plataforma._logs_antigos, plataforma.pasta_logs, plataforma._dados_desviados = guardados
        arquivo = nova / "antes-de-2026-11-07"
        ok("movidos (nada apagado), o da dylib do laboratório fica, e uma 2ª vez não faz nada",
           (movidos, sorted(p.name for p in arquivo.iterdir()), (antiga / "aro_servidor.log").is_file(), de_novo),
           (["delapraca.log", "pilhas.txt"], ["delapraca.log", "pilhas.txt"], True, []))

    with tempfile.TemporaryDirectory() as tmp:
        dados = Path(tmp) / "dados"
        plataforma.pasta_dados = lambda: dados              # nada na pasta real do usuário
        import cache
        import configuracoes
        import registro

        ok("⭐ dados desviados (testes): o cache e os logs vão junto, nunca para a pasta real",
           (plataforma.pasta_cache_padrao(), plataforma.pasta_logs()), (dados / "Cache", dados / "Logs"))
        ok("sem configuração: o cache é o padrão, teto 20 GB",
           (cache.raiz(), configuracoes.ler()["cache_max_gb"]), (dados / "Cache", 20))

        print("o local escolhido")
        escolhida = Path(tmp) / "MEU CACHE"
        configuracoes.gravar({"cache_dir": str(escolhida)})
        ok("a pasta escolhida vale", cache.raiz(), escolhida)
        ok("⛔ UNC é recusado (o DRT iria ao Resolve por SMB): volta o padrão",
           configuracoes.pasta_aceitavel(r"\\atacante\c$\cache"), None)
        ok("⛔ //host também", configuracoes.pasta_aceitavel("//atacante/cache"), None)
        ok("⛔ caminho relativo é recusado", configuracoes.pasta_aceitavel("cache"), None)
        if plataforma.E_WINDOWS:
            fora = "Q:\\" if not Path("Q:\\").exists() else "W:\\"
            configuracoes.gravar({"cache_dir": fora + "CACHE"})
            ok("⭐ disco que não está aqui: o cache cai no padrão e o painel avisa",
               (cache.raiz(), cache.indisponivel()), (dados / "Cache", True))
        configuracoes.gravar({"cache_max_gb": 0})
        ok("teto fora do razoável volta ao padrão", configuracoes.ler()["cache_max_gb"], 20)
        (dados / "configuracoes.json").write_text("{corrompido", encoding="utf-8")
        ok("arquivo corrompido: os padrões, sem levantar", configuracoes.ler()["cache_dir"], None)

        print("trocar o local não move nada")
        configuracoes.gravar({"cache_dir": None})
        _arquivo(cache.sub("recebidos") / "a.drt", 10)
        configuracoes.gravar({"cache_dir": str(escolhida)})
        ok("o novo começa vazio, o antigo fica onde estava",
           (cache.estatisticas()["arquivos"], (dados / "Cache" / "recebidos" / "a.drt").exists()), (0, True))

        print("limpar só mexe nas subpastas do app")
        do_editor = _arquivo(escolhida / "MINHAS COISAS" / "roteiro.pdf", 5)
        solto = _arquivo(escolhida / "anotacao.txt", 5)
        conf = escolhida / "Conferências" / "CENA · 2026-10-05 10h00"
        _arquivo(conf / "_interno" / "plano.json", 100)
        _arquivo(conf / "01_00_00_10 V1 A início.jpg", 900)
        _arquivo(cache.sub("recebidos") / "8a552457-1462-466e-a108-772942261d8b.drt", 50)
        _arquivo(cache.sub("recebidos") / "8a552457-1462-466e-a108-772942261d8b.midias.json", 7)
        _arquivo(cache.sub("trabalho") / "relink.aaf", 30)
        e = cache.estatisticas()
        ok("o uso conta só as subpastas do app", (e["bytes"], e["arquivos"]), (1087, 5))
        liberado = cache.limpar()
        ok("limpar apaga tudo o que é do app", (liberado["arquivos"], cache.estatisticas()["arquivos"]), (5, 0))
        ok("⭐ …e nada do editor (pasta e arquivo soltos na raiz escolhida)",
           (do_editor.exists(), solto.exists()), (True, True))

        print("o teto: LRU por unidade")
        velha = escolhida / "Conferências" / "VELHA · 2026-10-01 09h00"
        _arquivo(velha / "_interno" / "plano.json", 100, idade_s=5000)
        _arquivo(velha / "x.jpg", 900, idade_s=5000)
        nova = escolhida / "Conferências" / "NOVA · 2026-10-05 09h00"
        _arquivo(nova / "_interno" / "plano.json", 100, idade_s=4000)
        _arquivo(nova / "x.jpg", 900, idade_s=4000)
        rec = cache.sub("recebidos")
        drt_velho = _arquivo(rec / "11111111-1111-4111-8111-111111111111.drt", 400, idade_s=3000)
        midias_velho = _arquivo(rec / "11111111-1111-4111-8111-111111111111.midias.json", 10, idade_s=1)
        drt_novo = _arquivo(rec / "22222222-2222-4222-8222-222222222222.drt", 400, idade_s=10)
        for d, idade in ((velha, 5000), (nova, 4000)):
            t = time.time() - idade
            os.utime(d, (t, t))
        cache.tocar(nova / "x.jpg")                                # a nova foi aberta agora
        r = cache.aplicar_teto(max_bytes=1900)
        ok("⭐ sai a unidade usada há mais tempo, INTEIRA (a conferência velha)",
           (velha.exists(), nova.exists(), r["arquivos"]), (False, True, 2))
        ok("o DRT e o .midias.json são uma unidade: a data mais nova dela vale",
           (drt_velho.exists(), midias_velho.exists()), (True, True))
        r = cache.aplicar_teto(max_bytes=500, protegidos=[str(nova)])
        ok("⭐ a protegida (conferência em curso) fica, mesmo sendo a mais velha",
           (nova.exists(), drt_velho.exists(), midias_velho.exists(), drt_novo.exists()),
           (True, False, False, False))

        print("o cache antigo (decisão 5: não migrar; avisar e oferecer apagar)")
        _arquivo(dados / "conferencia" / ("a" * 32) / "100.jpg", 2000)
        _arquivo(dados / "recebidos" / "x.drt", 300)
        partida = _arquivo(dados / "partidas" / "p.carta", 10)
        token = _arquivo(dados / "token", 64)
        a = cache.antigo()
        ok("avisa o que sobrou das versões anteriores (sem as partidas)",
           (a["arquivos"], a["bytes"]), (2, 2300))
        cache.apagar_antigo()
        ok("⭐ apagar o antigo leva conferência e recebidos; partidas e token ficam",
           ((dados / "conferencia").exists(), (dados / "recebidos").exists(), partida.exists(),
            token.exists(), cache.antigo()), (False, False, True, True, None))
        _arquivo(dados / "recebidos" / "y.drt", 3)
        configuracoes.gravar({"cache_antigo_dispensado": True})
        ok("'Manter' para de avisar", cache.antigo(), None)
        configuracoes.gravar({"cache_dir": None})
        ok("o cache padrão (Cache/recebidos) não é confundido com o antigo",
           all("Cache" not in p for p in (cache.antigo() or {"pastas": []})["pastas"]), True)

        print("abrir pastas só pelo nome")
        ok("cache e logs se abrem pelo nome",
           (cache.pasta_conhecida("cache"), cache.pasta_conhecida("logs")),
           (cache.raiz(), plataforma.pasta_logs()))
        ok("⛔ qualquer outro nome é recusado", _erro(lambda: cache.pasta_conhecida("C:\\Windows")),
           "ValueError")

        print("as rotas")
        _rotas(escolhida)

        print("o log: um arquivo, cabeçalho, rotação")
        _log(Path(tmp) / "logs")

        print("apagar no exFAT do Mac (lista NFD, só apaga pelo NFC)")
        _exfat(Path(tmp) / "exfat")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


def _rotas(escolhida: Path) -> None:
    from api import rotas
    import cache
    import conferencia

    abertas = []
    plataforma.abrir_pasta = lambda p: abertas.append(Path(p))
    conferencia._UNICA = conferencia.Conferencias()

    class Ctx:
        def __init__(self, servico, corpo=None):
            self.servico, self._corpo, self.query = servico, corpo or {}, ""

        def json(self):
            return self._corpo

    livre = SimpleNamespace(sessao=SimpleNamespace(ocupada=False),
                            sessao_export=SimpleNamespace(ocupada=False),
                            receber=SimpleNamespace(progresso=lambda: {"ativo": False}))
    importando = SimpleNamespace(**{**vars(livre), "receber": SimpleNamespace(progresso=lambda: {"ativo": True})})

    st, r = rotas.cache_estado(Ctx(livre))
    ok("GET /cache: onde, quanto, teto, logs, antigo e ocupado",
       (st, sorted(r)), (200, sorted(["dir", "padrao", "escolhida", "indisponivel", "bytes", "arquivos",
                                      "max_gb", "logs", "antigo", "ocupado"])))
    st, r = rotas.cache_configurar(Ctx(livre, {"dir": r"\\atacante\x", "max_gb": 30}))
    ok("⛔ configurar com caminho de rede: 400", st, 400)
    st, r = rotas.cache_configurar(Ctx(livre, {"dir": str(escolhida), "max_gb": 30}))
    ok("configurar: pasta e teto guardados", (st, r["dir"], r["max_gb"]), (200, str(escolhida), 30))
    _arquivo(cache.sub("recebidos") / "33333333-3333-4333-8333-333333333333.drt", 5)
    st, r = rotas.cache_limpar(Ctx(importando))
    ok("⭐ nada se limpa no meio de um Importar (409)", (st, "Importar" in r["erro"]), (409, True))
    st, r = rotas.cache_limpar(Ctx(livre))
    ok("livre: limpa", (st, r["arquivos"]), (200, 0))
    st, _ = rotas.pasta_abrir(Ctx(livre, {"qual": "logs"}))
    st2, _ = rotas.pasta_abrir(Ctx(livre, {"qual": str(escolhida)}))
    st3, _ = rotas.pasta_abrir(Ctx(livre, {"qual": "conferencia", "id": "../../x"}))
    ok("⭐ /pasta/abrir: só pelo nome — um caminho no lugar do nome é recusado",
       (st, st2, st3, abertas), (200, 409, 409, [plataforma.pasta_logs()]))
    st, r = rotas.cache_configurar(Ctx(livre, {"dir": None}))
    ok("'Usar padrão': volta à pasta do sistema", (st, r["escolhida"], r["dir"]),
       (200, None, str(plataforma.pasta_cache_padrao())))


def _log(pasta: Path) -> None:
    import registro

    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    alvo = registro.configurar("teste", "9.9.9", pasta=pasta)
    try:
        ok("um arquivo de nome fixo, sem data", alvo, pasta / "delapraca.log")
        ok("idempotente: configurar de novo não duplica", registro.configurar("x", "1", pasta=pasta), alvo)
        texto = alvo.read_text(encoding="utf-8")
        ok("⭐ o cabeçalho diz versão, origem, SO, ffprobe, dados e cache",
           all(x in texto for x in ("De Lá Pra Cá 9.9.9", "(teste)", "SO:", "ffprobe=", "dados=", "cache=")),
           True)
        h = next(x for x in raiz.handlers if x not in antes)
        h.maxBytes = 2000
        for i in range(200):
            logging.getLogger("delapraca.teste").info("linha %03d %s", i, "x" * 40)
        ok("rotação: guarda até 4 anteriores, nunca mais", sorted(p.name for p in pasta.iterdir()),
           ["delapraca.log", "delapraca.log.1", "delapraca.log.2", "delapraca.log.3", "delapraca.log.4"])
        # ⚠️ no Windows, outro processo com o arquivo aberto faz o rename levantar
        orig = os.rename
        os.rename = lambda *a: (_ for _ in ()).throw(PermissionError("em uso"))
        try:
            for i in range(60):
                logging.getLogger("delapraca.teste").info("depois %03d %s", i, "y" * 40)
        finally:
            os.rename = orig
        ok("⭐ rotação que falha (arquivo em uso) não mata o log: segue escrevendo",
           "depois 059" in alvo.read_text(encoding="utf-8"), True)
    finally:
        for x in list(raiz.handlers):
            if x not in antes:
                raiz.removeHandler(x)
                x.close()
        registro._configurado = None


def _exfat(base: Path) -> None:
    """Simula o exFAT do macOS medido em 2026-10-05: o nome listado vem NFD e só o NFC apaga. Antes o
    `rmtree` recebia "não encontrado", o `_apagar` contava como apagado e o "Limpar" não tirava nada."""
    import unicodedata
    from unittest import mock

    import cache

    conf = base / cache.CONFERENCIAS / unicodedata.normalize("NFC", "Timeline Ação · 2026-10-05 10h00")
    (conf / "_interno").mkdir(parents=True)
    (conf / "_interno" / "plano.json").write_text("{}", encoding="utf-8")
    (conf / unicodedata.normalize("NFC", "NÃO CONFERE 01.jpg")).write_bytes(b"x")
    reais = {"remove": os.remove, "rmdir": os.rmdir, "listdir": os.listdir, "scandir": os.scandir}
    nfd = lambda c: unicodedata.normalize("NFD", str(c))  # noqa: E731

    def so_nfc(nome):
        def fn(c):
            if str(c) != unicodedata.normalize("NFC", str(c)):
                raise FileNotFoundError(2, "exFAT: só o NFC apaga", str(c))
            return reais[nome](c)
        return fn

    class Entrada:   # o `os.walk` lê pelo scandir: devolver os nomes em NFD, como o exFAT
        def __init__(self, e):
            self._e, self.name, self.path = e, nfd(e.name), nfd(e.path)

        def __getattr__(self, k):
            return getattr(self._e, k)

    class Varredura:
        def __init__(self, p):   # o exFAT ABRE pelo nome NFD que listou; o NTFS não — simular os dois iguais
            self._it = reais["scandir"](unicodedata.normalize("NFC", str(p)))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self._it.close()

        def __iter__(self):
            return (Entrada(e) for e in self._it)

        def __next__(self):
            return Entrada(next(self._it))

        def close(self):
            self._it.close()

    with mock.patch.object(plataforma, "E_MACOS", True), \
            mock.patch("os.remove", so_nfc("remove")), mock.patch("os.rmdir", so_nfc("rmdir")), \
            mock.patch("os.scandir", Varredura):
        plataforma.apagar_arvore(conf)
    ok("⭐ a conferência com acento sai inteira (o nome listado NFD falha, o NFC apaga)", conf.exists(), False)
    f = base / unicodedata.normalize("NFC", "Ação.drt")
    f.write_bytes(b"x")
    with mock.patch.object(plataforma, "E_MACOS", True), mock.patch("os.remove", so_nfc("remove")):
        plataforma.apagar_arquivo(nfd(f))
    ok("o DRT com acento também (pelo nome NFD que a listagem dá)", f.exists(), False)
    ok("⛔ o que não existe mesmo levanta (não conta como apagado em silêncio)",
       _erro(lambda: plataforma.apagar_arquivo(base / "sumiu.drt"))[:17], "FileNotFoundError")


if __name__ == "__main__":
    raise SystemExit(main())
