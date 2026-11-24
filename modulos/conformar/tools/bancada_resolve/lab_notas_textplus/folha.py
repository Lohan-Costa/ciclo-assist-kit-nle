import sys, os, glob
from PIL import Image, ImageDraw
pasta, saida = sys.argv[1], sys.argv[2]
vars_ = ["ATUAL", "A_FATIADO", "B_UNIAO"]
qs = sorted({int(f[-8:-4]) for f in glob.glob(os.path.join(pasta, "*.png"))})
W, H = 640, 360
folha = Image.new("RGB", (W * 3, H * len(qs)), (40, 40, 40))
d = ImageDraw.Draw(folha)
for i, q in enumerate(qs):
    for j, v in enumerate(vars_):
        f = os.path.join(pasta, f"NOTAS_{v}_{q:04d}.png")
        if os.path.exists(f):
            im = Image.open(f).convert("RGB").resize((W, H))
            folha.paste(im, (j * W, i * H))
        d.rectangle([j * W, i * H, j * W + W - 1, i * H + H - 1], outline=(90, 90, 90))
        d.text((j * W + 8, i * H + H - 18), f"{v}  q{q}", fill=(255, 255, 0))
folha.save(saida)
print(saida, folha.size)
