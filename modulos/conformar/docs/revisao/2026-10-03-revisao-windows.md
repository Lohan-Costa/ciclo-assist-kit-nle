# Revisão de código — sessão no Windows (Resolve 19, o piso), 2026-10-03

Escopo: tudo o que mudou na validação no Windows (`d49b7ee..1c6930c`, 7 commits): o caminho do Mac lido
no Windows, o Fusion conferido no Resolve 19, o reverso e a mesa do Fairlight na forma do 19, o `..` nos
caminhos do `.prproj`, a velocidade e o volume com keyframes do áudio do Premiere.

**Método:** `/code-review high d49b7ee..HEAD` (10 achados). Cada achado foi conferido no código antes de
mexer. 8 corrigidos com teste (cada um falharia no código anterior), 1 documentado, 1 limpeza feita junto.
Suíte no Windows: 46/47 (o 47º é a mídia gerenciada do room tone da PRODA, que não está nesta máquina).

| # | Achado | Gravidade | Destino |
|---|---|---|---|
| 1 | `_no_volume_desta_maquina` sondava TODAS as letras — leitor de cartão vazio (diálogo modal escondido) e unidade de rede caída (timeout por sonda) — duas vezes por caminho, sem cache | alta | ✅ só discos LOCAIS e PRONTOS (`GetDriveTypeW` 2/3 + `GetVolumeInformationW`); a 2ª passada só nos outros discos; cache por (rótulo, caminho) |
| 2 | Fusion, caminho A: composição criada pelo import direto que não confere ficava no clipe, e o caminho B empilhava outra | média | ✅ apaga a do A; se o Resolve não apaga (o 19 não apaga a única), PARA e avisa "refazer à mão" (Python e casca) |
| 3 | Volume: keyframe sem vírgula derrubava a leitura inteira (IndexError); contagem crua × válida deixava o clipe sem volume, calado | média | ✅ uma regra só (`_kfs_do_level`); keyframe ilegível = valor fixo + aviso |
| 4 | A velocidade de áudio nova valia também para o áudio do AVID (speed_ratio com conform/reverso), sem medida | média | ✅ só no áudio do Premiere (`seg["prproj"]["audio"]`) |
| 5 | `..` acima da raiz era aceito (o `normpath` grampeia) e o separador mudava — a mesma mídia com duas grafias, casada e sondada duas vezes | média | ✅ pilha própria (`_resolver_pontos`): recusa acima da raiz, mantém o separador |
| 6 | Volume avaliado só no trecho nominal; o writer estende o áudio na sobra das transições | baixa | 📝 documentado: na sobra vale o valor da ponta; rampa só dentro da sobra (raro) não vem |
| 7 | `_montada` lia o `.comp` em UTF-8 estrito: acento noutra codificação derrubava a conferência | baixa | ✅ `errors="replace"` + `ValueError` (Python; o JS já não lança) |
| 8 | Sondas repetidas do mesmo caminho (estéreo, pedaços de lâmina) | limpeza | ✅ junto com o 1 |
| 9 | Conversão Level ↔ dB copiada em três lugares | limpeza | ✅ `_db_do_level` |
| 10 | Três cópias do molde QHash de dois keyframes | limpeza | ✅ `_timemap_dois_kf` (os três testes byte a byte seguem passando) |
