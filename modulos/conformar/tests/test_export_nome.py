"""O nome do arquivo exportado e as regras da sessão de export — sem MC, sem disco.

Rodar:

    .venv-win/Scripts/python tests/test_export_nome.py
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

from nomes import export as N  # noqa: E402
from sessao_export import com_extensao, formato_valido, mob_id_da_api  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<58} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    campos = N.valores("PRODA_CORTE", "PRODUCAO-A", agora=datetime(2026, 9, 24, 14, 5))

    print("── os campos ─────────────────────────────────────────────────")
    ok("⭐ %data é AAMMDD", campos["data"], "260924")
    ok("%hora é HHMM", campos["hora"], "1405")
    ok("tag fechada", N.analisar("%{sequencia}_%{data}", campos)["nome"], "PRODA_CORTE_260924")
    ok("tag solta com literal colado por _", N.analisar("%sequencia_V2", campos)["nome"],
       "PRODA_CORTE_V2")
    ok("⭐ campo inexistente TRAVA (não rende vazio)",
       (N.analisar("%{cena}_x", campos)["nome"], bool(N.analisar("%{cena}_x", campos)["erro"])),
       ("", True))
    ok("vazio é erro", N.analisar("", campos)["erro"], "o nome ficou vazio")

    print("\n── pré-preenchimento ─────────────────────────────────────────")
    ok("⭐ '%' do nome da sequência vira literal", N.analisar(N.literal("CORTE 50%"), campos)["nome"],
       "CORTE 50%")

    print("\n── o nome vira NOME, nunca caminho ───────────────────────────")
    ok("barra não atravessa pasta", N.nome_de_arquivo("../../Windows/x"), ".._.._Windows_x")
    ok("proibidos do Windows", N.nome_de_arquivo('a<b>c:d"e|f?g*h'), "a_b_c_d_e_f_g_h")
    ok("⭐ ponto/espaço no fim saem", N.nome_de_arquivo("CORTE. "), "CORTE")
    ok("nome reservado do Windows", N.nome_de_arquivo("CON"), "_CON")

    print("\n── a sessão ──────────────────────────────────────────────────")
    ok("extensão completada", com_extensao(str(Path("D:/x/NOME")), "drt"), str(Path("D:/x/NOME.drt")))
    ok("extensão não duplicada", com_extensao(str(Path("D:/x/NOME.DRT")), "drt"), str(Path("D:/x/NOME.DRT")))
    ok("Carta Aberta é .json", com_extensao(str(Path("D:/x/N.1")), "carta_aberta"),
       str(Path("D:/x/N.1.json")))
    for f in ("prproj", "aaf", "xml", "otio"):
        try:
            formato_valido(f)
            ok(f"{f} recusado no backend", "aceitou", "em breve")
        except ValueError as e:
            ok(f"{f} recusado no backend", "em breve" in str(e), True)
    try:
        formato_valido("exe")
        ok("formato desconhecido recusado", "aceitou", "recusou")
    except ValueError:
        ok("formato desconhecido recusado", "recusou", "recusou")

    urn = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cec8e8.0a910000.060e2b34.7f7f2a80"
    api = mob_id_da_api(urn)
    ok("⭐ MobID da bin → agrupamento do arrasto (26-6-16-12-4)",
       [len(p) for p in api.split("-")], [26, 6, 16, 12, 4])
    ok("mesmos 64 dígitos, mesma ordem", api.replace("-", ""),
       urn.split(":")[-1].replace(".", ""))

    print("\n── nunca sobrescreve ─────────────────────────────────────────")
    from api.rotas import _arquivo_livre
    with tempfile.TemporaryDirectory() as d:
        alvo = Path(d) / "N.drt"
        ok("livre fica igual", _arquivo_livre(str(alvo)), str(alvo))
        alvo.write_text("x")
        ok("existente numera", Path(_arquivo_livre(str(alvo))).name, "N_2.drt")
        (Path(d) / "N_2.drt").write_text("x")
        ok("e segue numerando", Path(_arquivo_livre(str(alvo))).name, "N_3.drt")

    print("\n── o nome do envio é do EDITOR (autor, 2026-09-25) ────────────")
    from types import SimpleNamespace

    from api.rotas import _nome_do_envio

    ins = N.valores("PRODA_CORTE", tipo="vfx")
    ok("%tipo vale COR/VFX, em maiúsculas", ins["tipo"], "VFX")
    ok("prefixo sugerido no painel renderiza",
       N.analisar("INSERT PARA %{tipo} — %{sequencia}", ins)["nome"], "INSERT PARA VFX — PRODA_CORTE")
    ok("%tipo só aparece no insert", N.SO_INSERT, frozenset({"tipo"}))
    ctx = SimpleNamespace(servico=SimpleNamespace(
        sessao_export=SimpleNamespace(nome_da_sequencia=lambda: "PRODA_CORTE", projeto="PRODA"),
        coleta=SimpleNamespace(sequencia={"nome": "PRODA_CORTE.02"})))
    ok("⭐ timeline: o padrão do editor vira o nome",
       _nome_do_envio(ctx, {"padrao": "%{sequencia}_para_cor"}, "timeline"), "PRODA_CORTE_para_cor")
    ok("⭐ insert: %sequencia é a da COLETA e %tipo o do botão",
       _nome_do_envio(ctx, {"padrao": "%{tipo}_%{sequencia}", "tipo": "cor"}, "insert"),
       "COR_PRODA_CORTE.02")
    ok("sem padrão (painel antigo), o nome da sequência",
       _nome_do_envio(ctx, {}, "timeline"), "PRODA_CORTE")
    try:
        _nome_do_envio(ctx, {"padrao": "%{inexistente}"}, "timeline")
        ok("padrão inválido é recusado no envio (não sai com nome errado)", "aceitou", "recusou")
    except ValueError:
        ok("padrão inválido é recusado no envio (não sai com nome errado)", "recusou", "recusou")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
