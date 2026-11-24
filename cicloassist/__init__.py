"""O Ciclo Assist."""

# ⛔⛔ Antes de QUALQUER `import grpc` (revisão de 2026-11-07, medido): com os "fork handlers" do gRPC ligados (o padrão
#    do grpcio 1.83), um subprocesso aberto (ffmpeg, ffprobe, `claude -p`, o app) enquanto canais de gRPC abrem e
#    fecham para o MC prende o fork por ~62 s SEGURANDO O GIL: o processo inteiro para, a porta não atende, e o
#    supervisor do app o mata ("parou de responder… processo vivo"). Reproduzido 3 de 3 (e no código real do Assist
#    contra o MC); com `0`, 0 de 3 em 40 mil forks. Nenhum filho nosso usa gRPC, então não há o que perder.
import os as _os

_os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")
