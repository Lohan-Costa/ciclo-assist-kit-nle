"""A leitura da claquete na decupagem (2026-09-22).

⭐ Pedido do editor: *"ao identificar claquete, tentar ler o conteúdo e retornar rolo de
câmera (pode ter mais de um), cena, plano, take e se é gravação em série. Se não der pra
ler, um aviso de ilegível."*

O que estes testes travam é a VALIDAÇÃO — texto do modelo é entrada não confiável — e a
instrução. ⚠️ Quanto o modelo acerta é medida de campo (`CLAUDE.md`), não teste.
"""

from __future__ import annotations

from cicloassist.motor import decupador as D
from cicloassist.motor import percepcao as P


def test_a_claquete_do_acervo_e_lida_com_procedencia():
    """O formato MEDIDO: ROLO · CENA · PLANO · TOMADA (A002_C002 = A02 / 4 / 6 / 2)."""
    nota = D._uma_nota({"descricao": "Uma claquete e depois Personagem F.", "claquete": {
        "rolo": ["a02"], "cena": "4", "plano": "6", "tomada": "2", "texto": "A02 4 6 2"}})
    q = nota["claquete"]
    assert q["legivel"] and q["rolo"] == ["A02"] and q["take"] == "2"
    assert q["fonte"] == "claquete" and q["confianca"] == "inferido"
    # ⛔⛔ E a leitura NÃO chega sozinha aos campos de topo: quem os promove é a
    #    conferência, depois de aprovar. Ver `test_so_a_claquete_conferida_vira_fato`.
    assert not any(c in nota for c in ("cena", "plano", "take"))
    # ⭐ Conferida, aí sim: é o que a busca filtra e ordena.
    conferida = D.conferir_a_claquete(nota, ["A002_03170256_C002.mp4"])
    assert (conferida["cena"], conferida["plano"], conferida["take"]) == ("4", "6", "2")


def test_ilegivel_e_um_estado_dito_e_sem_numero_inventado():
    nota = D._uma_nota({"descricao": "x", "claquete": {"legivel": False}})
    assert nota["claquete"]["legivel"] is False and "cena" not in nota
    # Viu e não leu nada que preste = ilegível, mesmo sem o modelo dizer.
    vazia = D._uma_nota({"descricao": "x", "claquete": {"rolo": [], "cena": ""}})
    assert vazia["claquete"]["legivel"] is False


def test_sem_claquete_nao_ha_campo():
    assert "claquete" not in D._uma_nota({"descricao": "um plano de rua"})


def test_varios_rolos_marcas_e_serie():
    q = D.ler_claquete({"rolo": "A02/B01", "cena": "12", "plano": "A", "take": "3",
                        "serie": True, "marcas": ["pickup"]})
    assert q["rolo"] == ["A02", "B01"] and q["serie"] is True and q["marcas"] == ["PICKUP"]


def test_texto_do_modelo_tem_teto():
    """⛔ Entrada não confiável: um campo não carrega um parágrafo, e a lista tem teto."""
    q = D.ler_claquete({"rolo": [f"R{i}" for i in range(50)], "cena": "9" * 500,
                        "texto": "x" * 5000})
    assert len(q["rolo"]) == 4 and len(q["cena"]) <= 12 and len(q["texto"]) <= 200


def test_a_instrucao_chega_aos_dois_motores_e_pede_a_cabeca():
    assert "claquete" in D.PERSONA and "Nunca chute" in D.PERSONA
    assert "Nunca chute" in P.persona_plana()
    assert "{CLAQUETE}" not in D.PERSONA
    corpo = P.corpo_do_pedido([b"a"], [10], {"fps": "25"}, "c" * 64,
                              cabeca=[b"b", b"c"], segundos_da_cabeca=[1.0, 3.0])
    usuario = corpo["messages"][1]
    assert len(usuario["images"]) == 3 and "CABEÇA" in usuario["content"]


def test_o_pedido_do_claude_manda_ler_a_claquete():
    import inspect
    assert "claquete=true" in inspect.getsource(D.decupar)


def test_o_rolo_lido_e_conferido_contra_o_nome_do_arquivo():
    """⛔⛔ MEDIDO (qwen3-vl 8B, 2026-09-22): na claquete pequena demais, o modelo copiou o
    EXEMPLO da instrução (A02 · 4 · 6 · 2) em vez de dizer ilegível. O arquivo era
    `A009_…`. A conferência não depende do modelo: rolo que não bate derruba a leitura."""
    errada = D._uma_nota({"descricao": "x", "claquete": {
        "rolo": ["A02"], "cena": "4", "plano": "6", "take": "2"}})
    q = D.conferir_a_claquete(errada, ["A009_03190918_C010.mp4"])["claquete"]
    assert q["confianca"] == "hipotese" and "A009" in q["aviso"]

    certa = D._uma_nota({"descricao": "x", "claquete": {"rolo": ["A09"], "cena": "16"}})
    q = D.conferir_a_claquete(certa, ["A009_03190918_C010"])["claquete"]
    assert q["confianca"] == "inferido" and "conferido" in q


def test_sem_rolo_no_nome_nao_ha_o_que_conferir():
    nota = D._uma_nota({"descricao": "x", "claquete": {"rolo": ["A02"], "cena": "1"}})
    q = D.conferir_a_claquete(nota, ["C04_P01-T002"])["claquete"]
    assert q["confianca"] == "inferido" and "aviso" not in q


def test_a_instrucao_diz_o_genero_e_nao_traz_marca_de_exemplo():
    """Medido: com "PICKUP" no exemplo, o modelo marcou PICKUP nos 4 takes; e escreveu
    "um claquete"."""
    assert '"marcas": []' in D.PERSONA and "a claquete (não clapperboard" in D.PERSONA


def test_so_a_claquete_conferida_vira_fato():
    """⛔⛔ MEDIDO no cache em 2026-09-23: as 44 notas com a claquete em `hipotese` tinham
    cena/plano/take no TOPO — onde a busca filtra e ordena — sem marca de dúvida nenhuma.
    A conferência marcava a dúvida só dentro do objeto `claquete`, que nenhum filtro lê."""
    nota = D._uma_nota({"descricao": "x", "claquete": {
        "rolo": ["A02"], "cena": "4", "plano": "6", "take": "2"}})
    # O rolo não bate com o nome do arquivo: a leitura fica, o FATO não.
    reprovada = D.conferir_a_claquete(nota, ["A009_03190918_C010.mp4"])
    assert reprovada["claquete"]["confianca"] == "hipotese"
    assert reprovada["claquete"]["cena"] == "4"          # o número continua à vista
    assert not any(c in reprovada for c in ("cena", "plano", "take"))


def test_a_promocao_de_uma_passada_anterior_e_desfeita():
    """A limpeza do cache antigo usa a MESMA função do produto — por isso ela tira o que
    uma passada velha promoveu, em vez de ter um critério à parte que envelhece."""
    velha = {"descricao": "x", "cena": "4", "plano": "6", "take": "2",
             "claquete": {"legivel": True, "rolo": ["A02"], "cena": "4", "plano": "6",
                          "take": "2", "confianca": "inferido", "fonte": "claquete"}}
    limpa = D.conferir_a_claquete(velha, ["A009_03190918_C010.mp4"])
    assert not any(c in limpa for c in ("cena", "plano", "take"))
    assert limpa["claquete"]["confianca"] == "hipotese"


def test_o_que_ja_foi_reprovado_continua_reprovado():
    """⛔⛔ A INSTRUÇÃO muda, e com ela o critério: o exemplo `31 · 8 · 5` saiu dela em
    2026-09-23. Sem esta trava, passar de novo por uma nota velha a aprovaria — o eco de
    ontem não é eco hoje — e devolveria aos filtros o chute que a limpeza tirou. É a mesma
    armadilha do `consertar_quadros`: critério que muda com o código."""
    velha = {"descricao": "x", "cena": "31", "plano": "8", "take": "5",
             "claquete": {"legivel": True, "rolo": ["A02"], "cena": "31", "plano": "8",
                          "take": "5", "confianca": "hipotese", "fonte": "claquete",
                          "aviso": "cena/plano/take iguais ao EXEMPLO da instrução"}}
    de_novo = D.conferir_a_claquete(velha, ["A002_03170823_C005.mp4"])
    assert de_novo["claquete"]["confianca"] == "hipotese"
    assert not any(c in de_novo for c in ("cena", "plano", "take"))


def test_o_eco_do_exemplo_e_pego_mesmo_com_o_rolo_certo():
    """⛔⛔ MEDIDO: 8 notas de 4 mídias ficaram com o `31 · 8 · 5` do exemplo marcadas como
    FATO, porque o modelo leu o rolo certo (`A002_…` → `A002`) e copiou só o resto. A
    conferência do rolo não tem como pegar isso — o rolo estava certo."""
    exemplo = D._valores_do_exemplo()
    assert exemplo and len(exemplo) == 3, "o exemplo da instrução mudou de forma"
    nota = D._uma_nota({"descricao": "x", "claquete": {
        "rolo": ["A002"], "cena": exemplo[0], "plano": exemplo[1], "take": exemplo[2]}})
    conferida = D.conferir_a_claquete(nota, ["A002_03170823_C005.mp4"])
    assert conferida["claquete"]["confianca"] == "hipotese"
    assert "EXEMPLO" in conferida["claquete"]["aviso"]
    assert not any(c in conferida for c in ("cena", "plano", "take"))


def test_o_exemplo_conferido_sai_do_proprio_texto_da_instrucao():
    """⛔ Dois literais iguais em dois lugares divergem calados: trocar o exemplo sem
    trocar a conferência a deixaria procurando o valor de ontem."""
    for valor in D._valores_do_exemplo():
        assert f'"{valor}"' in D.CLAQUETE


def test_qualquer_literal_da_instrucao_devolvido_como_leitura_e_recusado():
    """⛔⛔ MEDIDO em 2026-09-23: trocar os valores do exemplo por `‹cena›` acabou com o eco
    de `31 · 8 · 5`, e o modelo passou a devolver `rolo ["01-2"]` — a FRASE SEGUINTE da
    instrução, escrita ali como explicação de notação. Todo literal do prompt é material de
    cópia, e o `X07` do exemplo apareceu 20 vezes no cache."""
    # ⚠️ Só os que CABEM num campo: `ler_claquete` corta o rolo em 8 caracteres e a cena em
    #    12, então uma frase inteira da instrução nunca chega a um deles — ela cabe no
    #    `texto`, que fica fora da conferência de propósito (ver o teste do falso positivo).
    literais = [v for v in D._literais_da_instrucao() if len(v) <= 8]
    assert literais, "a instrução não tem literal curto — reveja este teste"
    for valor in literais:
        nota = D._uma_nota({"descricao": "x", "claquete": {
            "rolo": [valor], "cena": "9", "plano": "2", "take": "1"}})
        conferida = D.conferir_a_claquete(nota, ["C04_P01-T002"])
        assert conferida["claquete"]["confianca"] == "hipotese", valor
        assert "ESCRITO na instrução" in conferida["claquete"]["aviso"]
        assert not any(c in conferida for c in ("cena", "plano", "take"))


def test_a_leitura_boa_do_acervo_nao_cai_no_detector_de_eco():
    """⚠️ O risco desta conferência é o falso positivo, e ele tem duas travas MEDIDAS:

    - número de um ou dois dígitos não denuncia nada (`plano 8` é plano de verdade em
      qualquer material; só a TRIPLA igual ao exemplo reprova);
    - `texto` fica fora, porque o `"como está"` do exemplo voltou em toda leitura —
      inclusive nas 4 conferidas certas.
    """
    for cena, plano, take in (("4", "2", "2"), ("4", "4", "1"), ("11", "3", "03")):
        nota = D._uma_nota({"descricao": "x", "claquete": {
            "rolo": ["A01"], "cena": cena, "plano": plano, "take": take,
            "texto": "como está"}})
        conferida = D.conferir_a_claquete(nota, ["A001_03170345_C005.mp4"])
        assert conferida["claquete"]["confianca"] == "inferido", (cena, plano, take)
        assert (conferida["cena"], conferida["plano"]) == (cena, plano)


def test_a_claquete_reprovada_nao_sobe_para_a_nota_macro(tmp_path, monkeypatch):
    """⛔⛔ 22 das 44 notas em `hipotese` eram a MACRO: `micro._subir_claquete` checava só
    `legivel`, que uma leitura reprovada continua sendo."""
    from cicloassist.midia import cache as _cache
    from cicloassist.motor import micro as M

    monkeypatch.setattr(_cache, "raiz", lambda: tmp_path)
    midia = _cache.Midia("f" * 64)
    midia.anotar({"escopo": "midia", "descricao": "a diária inteira"})

    M._subir_claquete(midia, {"legivel": True, "cena": "31", "plano": "8", "take": "5",
                              "confianca": "hipotese", "aviso": "copiou o exemplo"})
    macro = midia.ler_notas()[0]
    assert "claquete" not in macro and "cena" not in macro

    M._subir_claquete(midia, {"legivel": True, "cena": "4", "plano": "6", "take": "2",
                              "confianca": "inferido"})
    macro = midia.ler_notas()[0]
    assert macro["claquete"]["cena"] == "4" and macro["cena"] == "4"


def test_o_rotulo_impresso_na_prancheta_nao_vira_valor():
    """⛔⛔ MEDIDO em 2026-09-23, numa claquete real e bem legível: o modelo devolveu
    `"cena": "CENA 1", "plano": "PLANO 1", "take": "TOMADA 1"`. Passou a conferência (o
    rolo batia) e foi para os filtros, onde procurar cena `1` não casa `CENA 1`. O rótulo
    está IMPRESSO embaixo de cada campo da prancheta: ele lê o que vê."""
    q = D.ler_claquete({"rolo": ["A01"], "cena": "CENA 4", "plano": "PLANO 3",
                        "take": "TOMADA 1"})
    assert (q["cena"], q["plano"], q["take"]) == ("4", "3", "1")
    # E o que já foi GRAVADO assim se conserta pela limpeza, que passa por aqui.
    velha = {"descricao": "x", "cena": "CENA 1", "claquete": {
        "legivel": True, "rolo": ["A01"], "cena": "CENA 1", "plano": "PLANO 1",
        "take": "TOMADA 1", "confianca": "inferido", "fonte": "claquete"}}
    limpa = D.conferir_a_claquete(velha, ["A001_03170256_C002.mp4"])
    assert limpa["claquete"]["cena"] == "1" and limpa["cena"] == "1"


def test_rolo_so_com_rotulo_nao_vira_vazio():
    """⚠️ `_sem_rotulo` só tira o rótulo quando sobra alguma coisa: um campo que veio só
    com a palavra continua como está, em vez de virar string vazia — que `ler_claquete`
    leria como 'não leu nada' e derrubaria a claquete inteira para ilegível."""
    q = D.ler_claquete({"rolo": ["A01"], "cena": "CENA", "plano": "2"})
    assert q["legivel"] and q["cena"] == "CENA" and q["plano"] == "2"


def test_a_confusao_de_ocr_no_rolo_nao_reprova_leitura_certa():
    """⛔ MEDIDO em 2026-09-23: a claquete escrita à mão diz `A01` (o zero parece um O), o
    modelo devolveu `AO1`, o rolo "não bateu" com `A001_…` e a leitura inteira caiu para
    `hipotese` — com cena, plano e tomada CERTOS (4 · 3 · 1, conferidos no quadro). A
    conferência existe para pegar chute, não caligrafia."""
    nota = D._uma_nota({"descricao": "x", "claquete": {
        "rolo": ["AO1"], "cena": "4", "plano": "3", "take": "1"}})
    conferida = D.conferir_a_claquete(nota, ["A001_03170355_C006.mp4"])
    assert conferida["claquete"]["confianca"] == "inferido"
    assert (conferida["cena"], conferida["plano"], conferida["take"]) == ("4", "3", "1")
    # ⛔ E o rolo LIDO continua como o modelo escreveu: quem perdoa é a comparação.
    assert conferida["claquete"]["rolo"] == ["AO1"]

    # A câmera errada continua sendo câmera errada.
    outra = D._uma_nota({"descricao": "x", "claquete": {"rolo": ["BO2"], "cena": "4"}})
    assert D.conferir_a_claquete(
        outra, ["A001_03170355_C006.mp4"])["claquete"]["confianca"] == "hipotese"


def test_a_claquete_do_outro_curta_com_campos_em_ingles():
    """⭐⭐ MEDIDA em 2026-09-23, no material da *PRODUCAO-F* (`D:/Avid MediaFiles/MXF/
    010020260629`): claquete DIGITAL, com timecode em LED e os campos impressos em inglês —
    `ROLL # A02 · SCENE 25 · SHOT 6 · TAKE 5`, mais PROD/DIR/DOP/DATE. Outro acervo, outro
    padrão, e o mesmo código tem de atravessar os dois."""
    q = D.ler_claquete({"rolo": ["ROLL # A02"], "cena": "SCENE 25", "plano": "SHOT 6",
                        "take": "TAKE 5"})
    assert q["rolo"] == ["A02"] and (q["cena"], q["plano"], q["take"]) == ("25", "6", "5")
    # ⛔ E o nome do arquivo DESTE material (`A_0002C016_…`) tem de dar a referência do
    #   rolo: sem ela a conferência fica sem com que comparar e aprova o que vier.
    nota = D.conferir_a_claquete({"descricao": "x", "claquete": q},
                                 ["A_0002C016_260629_125302_h1DF4"])
    assert nota["claquete"]["confianca"] == "inferido"
    assert (nota["cena"], nota["plano"], nota["take"]) == ("25", "6", "5")


def test_o_rotulo_sai_antes_do_corte_do_campo():
    """⚠️ A ordem importa: cortando primeiro, `"ROLL # A02"` vira `"ROLL # A"` nos 8
    caracteres do rolo e depois `"A"` — o cartão perderia o número da câmera."""
    assert D.ler_claquete({"rolo": ["ROLL # A02"], "cena": "1"})["rolo"] == ["A02"]


def test_o_rolo_no_nome_cobre_os_padroes_de_camera_conhecidos():
    esperado = {
        "A009_03190918_C010": ("A", 9),      # Blackmagic
        "A001C003": ("A", 1),                # ARRI
        "A001_C003": ("A", 1),               # RED
        "A_0002C016_260629_125302": ("A", 2),  # o material da PRODUCAO-F
    }
    for nome, alvo in esperado.items():
        m = D._ROLO_NO_NOME.match(nome)
        assert m and (m.group(1).upper(), int(m.group(2))) == alvo, nome
    # ⚠️ E um nome que NÃO é de câmera continua sem dar referência nenhuma.
    assert D._ROLO_NO_NOME.match("C04_P01-T002") is None


def test_o_nome_do_arquivo_devolvido_como_claquete_e_recusado():
    """⛔⛔ MEDIDO em 2026-09-23, numa claquete filmada NO ESCURO (só o timecode em LED
    aceso): o `texto` trouxe o TC certo (`08:30:08:12`) e os campos vieram `cena 260629 ·
    plano 083016 · take h1DF4` — a data, a hora e o sufixo do NOME DO ARQUIVO, repartidos
    nos três. E o nome é nosso: vai no cabeçalho do pedido."""
    q = D.ler_claquete({"rolo": ["A_0001C0"], "cena": "260629", "plano": "083016",
                        "take": "h1DF4", "texto": "08:30:08:12"})
    nota = D.conferir_a_claquete({"descricao": "x", "claquete": q},
                                 ["A_0001C001_260629_083016_h1DF4"])
    assert nota["claquete"]["confianca"] == "hipotese"
    assert "NOME DO ARQUIVO" in nota["claquete"]["aviso"]
    assert not any(c in nota for c in ("cena", "plano", "take"))


def test_a_cena_que_existe_DENTRO_do_nome_nao_e_eco():
    """⚠️ A comparação é por TOKEN inteiro: a cena `4` de um take real está "dentro" de
    `03170345` como substring, e reprovar por isso derrubaria leitura boa. Medido: esta é
    a claquete conferida de `A001_03170345_C005` (`A01 · 4 · 2 · 2`)."""
    q = D.ler_claquete({"rolo": ["A01"], "cena": "4", "plano": "2", "take": "2"})
    nota = D.conferir_a_claquete({"descricao": "x", "claquete": q},
                                 ["A001_03170345_C005"])
    assert nota["claquete"]["confianca"] == "inferido"
    assert (nota["cena"], nota["plano"], nota["take"]) == ("4", "2", "2")


def test_o_rolo_certo_nao_e_eco_do_nome():
    """⛔⛔ O `rolo` fica FORA do detector de eco do nome, e é o oposto do que parece: ele
    coincide com o nome do arquivo **por definição** — é isso que a conferência do rolo
    exige para aprovar. Medido no cache: a primeira versão reprovou `rolo A001` em
    `A001_0317…` (o rolo certo) e `rolo A02` em `A_0002C016…_A02.mxf`, onde o `_A02` é o
    sufixo de TRILHA do OP-Atom."""
    q = D.ler_claquete({"rolo": ["A001"], "cena": "4", "plano": "2", "take": "1"})
    nota = D.conferir_a_claquete({"descricao": "x", "claquete": q},
                                 ["A001_03170334_C004.mp4", "A001_03170334_C004"])
    assert nota["claquete"]["confianca"] == "inferido"

    mo = D.ler_claquete({"rolo": ["A02"], "cena": "25", "plano": "6", "take": "5"})
    nota = D.conferir_a_claquete({"descricao": "x", "claquete": mo}, [
        "A_0002C016_260629_125302_h1DF4", "A_0002C016_260629_125302_h1DF4_A02"])
    assert nota["claquete"]["confianca"] == "inferido"
    assert (nota["cena"], nota["plano"], nota["take"]) == ("25", "6", "5")
