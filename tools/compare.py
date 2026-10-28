"""Side-by-side comparison with labels: compare.py out.png "label A" a.png "label B" b.png [...]"""
import sys
from PIL import Image, ImageDraw
out, pairs = sys.argv[1], list(zip(sys.argv[2::2], sys.argv[3::2]))
ims = [Image.open(p).convert("RGB") for _, p in pairs]
h = min(i.height for i in ims)
ims = [i.resize((int(i.width * h / i.height), h), Image.LANCZOS) for i in ims]
gap = 8
canvas = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), h + 34), (12, 12, 12))
x = 0
d = ImageDraw.Draw(canvas)
for (label, _), im in zip(pairs, ims):
    canvas.paste(im, (x, 34)); d.text((x + 8, 10), label, fill=(235, 235, 235)); x += im.width + gap
canvas.save(out)
