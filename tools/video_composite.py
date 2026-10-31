"""Composite ambience-video frames from the linear passes rendered by video_passes.py.

Per frame (all in scene-linear light, then through the scene's own view transform via Blender):
  frame = nodomecam + T * E_t + f(t) * lamp + mist * m(t) + smoke * s(t)
  * E_t: the sky dome's radiance with the cloud texture drifted, re-lit around the (fixed) moon exactly as
    refine_v6 lit the static map; T: per-pixel transmittance of the fog in front of the dome, measured as
    (nolamp - nodomecam) / E_0 on bright cloud pixels and smoothly filled in (in nodomecam the dome is
    black to camera rays, so nothing behind it shows);
  * f(t): a lamp flicker curve; mist/smoke: (nolamp - nolocalvol), modulated by slowly drifting noise;
  * a slow push-in toward the house.

Usage: python3 video_composite.py <scene.blend> <passes_dir> <frames_dir> <first> <last> <duration_s> [fps]
"""
import bpy, os, sys, math, time
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ground_maps as gm

BLEND, PASSES, FRAMES = sys.argv[1:4]
FIRST, LAST, DUR = int(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6])
FPS = float(sys.argv[7]) if len(sys.argv) > 7 else 24.0
CLOUD_DEG_PER_S = 0.09        # cloud drift (azimuth) - about 17 degrees over the 3-minute video
ZOOM_END = 1.04               # push-in by the last frame
os.makedirs(FRAMES, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=BLEND)
sc = bpy.context.scene


def load_exr(name):
    img = bpy.data.images.load(os.path.join(PASSES, name + ".exr"))
    w, h = img.size
    buf = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)                     # rows bottom -> top, as Blender stores them


nolamp, lamp, nodome, nolv, mask = (load_exr(n) for n in ("nolamp", "lamp", "nodomecam", "nolocalvol", "skymask"))
H, W = nolamp.shape[:2]
nolamp, lamp, nodome, nolv = (a[..., :3] for a in (nolamp, lamp, nodome, nolv))
sky_cov = np.clip(1.0 - mask[..., 3], 0.0, 1.0)

# ------------------------------------------------------------------ camera rays -> dome texture coordinates
camo = sc.camera
cam = camo.data
cpos = np.array(camo.matrix_world.translation, np.float32)
R = np.array(camo.matrix_world.to_3x3().normalized(), np.float32)
sw = cam.sensor_width
xs = ((np.arange(W) + 0.5) / W - 0.5) * sw
ys = ((np.arange(H) + 0.5) / H - 0.5) * sw * H / W
X, Y = np.meshgrid(xs, ys)
d = np.stack([X, Y, np.full_like(X, -cam.lens)], -1) @ R.T
d /= np.linalg.norm(d, axis=-1, keepdims=True)
dome = next(o for o in sc.objects if o.type == "MESH" and o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "sky")
moon = next(o for o in sc.objects if o.type == "MESH" and o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "moon")
Rd = dome.scale.x
sel = sky_cov > 0.002                               # only pixels that can see the dome
ds = d[sel]
b = ds @ cpos
t_hit = -b + np.sqrt(b * b - (cpos @ cpos - Rd * Rd))
p = (cpos + ds * t_hit[:, None]) / Rd
U = (0.5 + np.arctan2(p[:, 1], p[:, 0]) / (2 * np.pi)) % 1.0
V = 0.5 + np.arcsin(np.clip(p[:, 2], -1, 1)) / np.pi
mdir = np.array((moon.matrix_world.translation - camo.matrix_world.translation).normalized(), np.float32)
ang = np.degrees(np.arccos(np.clip(ds @ mdir, -1, 1)))
g1, g2 = np.exp(-(ang / 9.0) ** 2), np.exp(-(ang / 28.0) ** 2)
far = 0.8 + 0.2 * np.exp(-(ang / 60.0) ** 2)
GLOW = np.array([0.55, 0.62, 0.78], np.float32)
TEX = os.path.join(os.path.dirname(os.path.abspath(BLEND)), "textures_rman")
base = np.flipud(np.asarray(Image.open(os.path.join(TEX, "sky_emission.png")).convert("RGB")).astype(np.float32) / 255.0)
base = np.where(base <= 0.04045, base / 12.92, ((base + 0.055) / 1.055) ** 2.4).astype(np.float32)
TH, TW = base.shape[:2]
SKY_STRENGTH = 0.45                                  # v5 sky strength; v6 stores lit * 0.4 with strength 0.45 / 0.4
LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)


def sample_sky(du):
    """Dome radiance for the sky pixels with the cloud texture shifted by du (texture u units)."""
    fx = ((U - du) % 1.0) * TW - 0.5
    fy = np.clip(V * TH - 0.5, 0, TH - 1.001)
    x0 = np.floor(fx).astype(np.int64); y0 = np.floor(fy).astype(np.int64)
    tx = (fx - x0)[:, None]; ty = (fy - y0)[:, None]
    x0 %= TW; x1 = (x0 + 1) % TW; y1 = np.minimum(y0 + 1, TH - 1)
    c = (base[y0, x0] * (1 - tx) + base[y0, x1] * tx) * (1 - ty) + (base[y1, x0] * (1 - tx) + base[y1, x1] * tx) * ty
    cloud = gm.smoothstep(0.02, 0.14, c @ LUM)
    lit = c * (1 + cloud * (2.0 * g1 + 0.35 * g2))[:, None] + GLOW * (0.03 * g1 + 0.012 * g2)[:, None]
    return lit * far[:, None] * SKY_STRENGTH


# transmittance of the fog in front of the dome, from the two renders
E0 = sample_sky(0.0)
Dsky = (nolamp - nodome)[sel]
lumE = E0 @ LUM
valid = (sky_cov[sel] > 0.98) & (lumE > 0.012)
Traw = np.zeros((H, W), np.float32); Wv = np.zeros((H, W), np.float32)
tmp = np.zeros(sel.sum(), np.float32); tmp[valid] = np.clip((Dsky[valid] @ LUM) / lumE[valid], 0, 1.5)
Traw[sel] = tmp; Wv[sel] = valid.astype(np.float32)


def blur(img, sigma):
    fy_ = np.fft.fftfreq(img.shape[0])[:, None]; fx_ = np.fft.fftfreq(img.shape[1])[None, :]
    g = np.exp(-2 * (np.pi ** 2) * sigma ** 2 * (fx_ ** 2 + fy_ ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(img) * g)).astype(np.float32)


sig = 15.0 * W / 1920
Tmap = blur(Traw * Wv, sig) / np.maximum(blur(Wv, sig), 1e-4)
Tsky = (np.clip(Tmap, 0, 1.2) * sky_cov)[sel]
print("fog transmittance over the open sky: median %.2f" % float(np.median(Tsky[valid])), flush=True)

# ------------------------------------------------------------------ mist / smoke layers and their motion
V_all = nolamp - nolv


def project(pw):
    v = np.array(camo.matrix_world.inverted() @ pw, np.float32)
    return ((v[0] / -v[2]) * cam.lens / sw + 0.5) * W, ((v[1] / -v[2]) * cam.lens / (sw * H / W) + 0.5) * H


smoke_ob = bpy.data.objects["Cone"]
sx_, sy_ = project(smoke_ob.matrix_world.translation)
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
smoke_w = np.exp(-(((xx - sx_) / (0.09 * W)) ** 2 + ((yy - sy_) / (0.14 * H)) ** 2))[..., None]
mist_l, smoke_l = V_all * (1 - smoke_w), V_all * smoke_w
N1 = gm.spectral_noise(512, 2.6, 31); N1 = (N1 - N1.min()) / (N1.max() - N1.min())
N2 = gm.spectral_noise(512, 2.3, 32); N2 = (N2 - N2.min()) / (N2.max() - N2.min())


def noise(Nf, ox, oy, scale):
    fx = (xx / scale + ox) % 512; fy = (yy / scale + oy) % 512
    x0 = fx.astype(np.int64); y0 = fy.astype(np.int64); tx = fx - x0; ty = fy - y0
    x1 = (x0 + 1) % 512; y1 = (y0 + 1) % 512
    return (Nf[y0, x0] * (1 - tx) + Nf[y0, x1] * tx) * (1 - ty) + (Nf[y1, x0] * (1 - tx) + Nf[y1, x1] * tx) * ty


# ------------------------------------------------------------------ lamp flicker
rng = np.random.default_rng(5)
KEYS = {r: rng.standard_normal(int(DUR * r) + 8) for r in (0.35, 2.7, 7.5)}


def smooth_noise(t, rate):
    k = KEYS[rate]; x = t * rate; i = int(x); f = x - i
    p0, p1, p2, p3 = k[i], k[i + 1], k[i + 2], k[i + 3]
    return 0.5 * ((2 * p1) + (-p0 + p2) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f * f + (-p0 + 3 * p1 - 3 * p2 + p3) * f ** 3)


def flicker(t):
    return float(np.clip(1.0 + 0.05 * smooth_noise(t, 0.35) + 0.045 * smooth_noise(t, 2.7) + 0.02 * smooth_noise(t, 7.5), 0.8, 1.15))


# ------------------------------------------------------------------ push-in
CX, CY = 0.56 * W, 0.5 * H
gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))


def zoom(img, s):
    if s <= 1.0001:
        return img
    fx = CX + (gx - CX) / s; fy = CY + (gy - CY) / s
    x0 = np.floor(fx).astype(np.int64); y0 = np.floor(fy).astype(np.int64)
    tx = (fx - x0)[..., None]; ty = (fy - y0)[..., None]
    x1 = np.minimum(x0 + 1, W - 1); y1 = np.minimum(y0 + 1, H - 1)
    return (img[y0, x0] * (1 - tx) + img[y0, x1] * tx) * (1 - ty) + (img[y1, x0] * (1 - tx) + img[y1, x1] * tx) * ty


# ------------------------------------------------------------------ frames
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.render.image_settings.color_depth = "8"
sc.render.image_settings.compression = 15
out_img = bpy.data.images.new("video_frame", W, H, float_buffer=True, alpha=False)
rgba = np.ones((H, W, 4), np.float32)
t0 = time.time()
for k in range(FIRST, LAST + 1):
    t = k / FPS
    frame = nodome.copy()
    sky = np.zeros((H, W, 3), np.float32)
    sky[sel] = Tsky[:, None] * sample_sky(CLOUD_DEG_PER_S * t / 360.0)
    frame += sky + flicker(t) * lamp
    frame += mist_l * (0.9 * (noise(N1, -0.022 * t, 0.004 * t, 2.6 * W / 1920) - 0.5))[..., None]
    frame += smoke_l * (1.4 * (noise(N2, -0.05 * t, -0.11 * t, 1.2 * W / 1920) - 0.5))[..., None]
    e = min(max(t / DUR, 0.0), 1.0)
    frame = zoom(np.maximum(frame, 0.0), 1.0 + (ZOOM_END - 1.0) * e * e * (3 - 2 * e))
    rgba[..., :3] = frame
    out_img.pixels.foreach_set(rgba.ravel())
    out_img.save_render(os.path.join(FRAMES, "%05d.png" % k), scene=sc)
    if (k - FIRST) % 100 == 0:
        print("frame %d (%.2fs/frame)" % (k, (time.time() - t0) / (k - FIRST + 1)), flush=True)
print("done frames %d-%d in %.0fs" % (FIRST, LAST, time.time() - t0), flush=True)
