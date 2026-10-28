"""Overhead map of the terrain: hillshade, standing water, traveled way, obstacle footprints, camera view."""
import sys, os, math, numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ground_maps as gm

tex, out = sys.argv[1], sys.argv[2]
crop = [float(v) for v in sys.argv[3:7]] if len(sys.argv) > 6 else [-20, 14, -10, 34]   # xmin xmax ymin ymax
h = np.load(os.path.join(tex, "_height.npy")); fp = np.load(os.path.join(tex, "_fp.npy"))
n = h.shape[0]; px = gm.S / n
gy, gx = np.gradient(h, px)
light = np.array([-0.6, 0.5, 0.62]); light /= np.linalg.norm(light)
nrm = np.stack([-gx * 6, -gy * 6, np.ones_like(h)], -1); nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
shade = np.clip(nrm @ light, 0, 1)
hn = (h - h.min()) / (h.max() - h.min())
rgb = np.stack([0.35 + 0.4 * hn, 0.3 + 0.35 * hn, 0.22 + 0.25 * hn], -1) * (0.35 + 0.75 * shade[..., None])
ys = gm.Y0 + (np.arange(n) + 0.5) * px; xs = gm.X0 + (np.arange(n) + 0.5) * px
X, Y = np.meshgrid(xs, ys)
xc = gm.road_x(ys); t = np.abs(X - xc[:, None])
water = h < gm.WATER_LEVEL
rgb[water] = rgb[water] * 0.3 + np.array([0.15, 0.45, 0.85]) * 0.7
edge = (np.abs(t - gm.TRAVELED_HALF_WIDTH) < px * 1.5)
rgb[edge] = [1.0, 0.95, 0.2]
rgb[fp > 0] = rgb[fp > 0] * 0.3 + np.array([0.9, 0.15, 0.1]) * 0.7
img = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
i0, i1 = int((crop[0] - gm.X0) / px), int((crop[1] - gm.X0) / px)
j0, j1 = int((crop[2] - gm.Y0) / px), int((crop[3] - gm.Y0) / px)
im = Image.fromarray(np.flipud(img[j0:j1, i0:i1]))
sc = 900 / im.width
im = im.resize((900, int(im.height * sc)), Image.LANCZOS)
dr = ImageDraw.Draw(im)
def to_px(x, y): return ((x - crop[0]) / px * sc, (crop[3] - y) / px * sc)
cam = (-3.0, -9.0); yaw = math.atan2(18.0, 5.5); half = math.radians(34.7)
for a in (yaw - half, yaw + half):
    dr.line([to_px(*cam), to_px(cam[0] + 60 * math.cos(a), cam[1] + 60 * math.sin(a))], fill=(255, 255, 255), width=2)
dr.ellipse([to_px(*cam)[0] - 6, to_px(*cam)[1] - 6, to_px(*cam)[0] + 6, to_px(*cam)[1] + 6], fill=(255, 255, 255))
dr.rectangle([8, 8, 470, 96], fill=(0, 0, 0))
for k, (c, txt) in enumerate([((255, 242, 51), "traveled way edge (1.75 m from centreline)"), ((40, 120, 220), "standing water (terrain below water level)"),
                              ((230, 40, 25), "obstacle footprints (buildings, wall, posts, props)"), ((255, 255, 255), "camera and horizontal field of view")]):
    dr.rectangle([16, 16 + k * 20, 30, 30 + k * 20], fill=c); dr.text((38, 17 + k * 20), txt, fill=(255, 255, 255))
im.save(out)
print("water m2:", round(float(water.sum() * px * px), 2))
