"""O piloto ADAPTATIVO do Ciclo Assist: olhar a tela, achar o elemento, agir, conferir.

Para o que a API do NLE não alcança (abrir o MC, criar projeto, salvar tudo). Peças:

| módulo | faz |
|---|---|
| `tela` | a foto da TELA (BitBlt, sem Pillow) e o JPEG pelo ffmpeg |
| `maos` | clique e tecla (`SendInput`), sempre conferindo QUEM está na frente antes do gesto |
| `localizador` | o `claude -p` olhando a foto: "onde está X?" — e a 2ª pergunta que CONFERE o ponto |

⛔ **Foto da TELA, nunca da janela.** `PrintWindow` não mostra menu nem lista suspensa (são
janelas de topo separadas — medido no MC 2024.6, 2026-11-01).
⛔ **A janela Qt do MC não tem acessibilidade** (UI Automation devolve 3 painéis): é pela foto.
⛔ **Na dúvida, não clica.** O localizador devolve `None` com o motivo; quem chama diz ao editor.

Só Windows por enquanto (⬜ macOS: `pendente` — o piloto da família já tem `maos_macos`).
Banco: `skills/piloto/SKILL.md`.
"""
