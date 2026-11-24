# Bancadas pilotadas (2026-10-18)

Scripts da sessão que validou o "molde por assinatura" no Media Composer e a API externa do Resolve. Rodam com o
Python do sistema (`py`) a partir DESTA pasta; `boot.py` acha o piloto e o app.

- `vigiar.py <exe> <script> [args]` — roda o script com VIGIA: foto da tela a cada 60 s (trazendo o programa à frente)
  e parada com foto no primeiro diálogo, sem clicar. **Toda execução pilotada passa por ele** (autor, 2026-10-18).
- Resolve: `bancada_resolve.py`, `bancada_resolve2.py` (as chamadas da casca, por fora), `e2e_resolve.py <arquivo>
  [pastas…]` (o Importar pela janela do app, pela API do serviço).
- Media Composer: `lab_golden.py`, `lab_clonar.py`, `lab_comparar.py` (molde × golden, comparação profunda) e
  `e2e_relink.py` (o relink da bin de fora pela API do serviço). `assinaturas.json` é gerado por eles.
