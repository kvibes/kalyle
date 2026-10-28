"""Height and mask maps for the haunted village ground (numpy only, no bpy).

World-space map: x in [X0, X0+S], y in [Y0, Y0+S]. Arrays are indexed [row, col] with
row 0 at Y0 (Blender's bottom image row), so they are flipped when written to PNG.
"""
import math
import numpy as np

X0, Y0, S = -30.0, -12.0, 64.0
H_MIN, H_MAX = -0.15, 0.15          # 16-bit height encoding range in metres
WATER_LEVEL = -0.05                 # puddle surface height
TRAVELED_HALF_WIDTH = 1.75          # compacted wheel-and-hoof track, kept clear of obstacles

# Road centreline as x(y). The far end bends left so the street clears the house at (-1, 30).
ROAD_CTRL = [(-5.0, -16), (-5.0, -14), (-4.8, -4), (-5.2, 4), (-6.4, 12), (-7.0, 20),
             (-7.3, 30), (-7.0, 40), (-6.5, 52), (-6.0, 60), (-6.0, 62)]

# Puddle depressions: centre x, y, lateral radius, along-road radius, depth (m)
PUDDLES = [(-5.4, 0.8, 1.9, 1.25, 0.06), (-4.4, -1.6, 0.8, 0.4, 0.03), (-6.6, 4.4, 1.3, 0.6, 0.04),
           (-5.3, 7.3, 0.9, 0.45, 0.03), (-6.9, 11.6, 1.4, 0.55, 0.04), (-7.2, 17.2, 1.1, 0.5, 0.035),
           (-7.3, 23.5, 1.3, 0.5, 0.035)]


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def smooth_max(a, b, k=0.006):
    return 0.5 * (a + b + np.sqrt((a - b) ** 2 + k * k))


def spectral_noise(n, beta, seed, fmin=1.0):
    """Tileable fBm by spectral synthesis, normalised to zero mean and unit std."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal((n, n))
    fx = np.fft.fftfreq(n)[None, :] * n
    fy = np.fft.fftfreq(n)[:, None] * n
    f = np.sqrt(fx * fx + fy * fy)
    f[0, 0] = 1.0
    amp = 1.0 / np.maximum(f, fmin) ** (beta / 2)
    amp[0, 0] = 0.0
    out = np.real(np.fft.ifft2(np.fft.fft2(white) * amp))
    return (out - out.mean()) / out.std()


def noise_1d(n, beta, seed):
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    f = np.abs(np.fft.fftfreq(n) * n)
    f[0] = 1.0
    out = np.real(np.fft.ifft(np.fft.fft(white) / f ** (beta / 2)))
    out -= out.mean()
    return out / out.std()


def gaussian_blur(img, sigma_m, px):
    """FFT gaussian blur; sigma in metres."""
    n = img.shape[0]
    s = sigma_m / px
    fx = np.fft.fftfreq(n)[None, :]
    fy = np.fft.fftfreq(n)[:, None]
    g = np.exp(-2 * (math.pi ** 2) * (s ** 2) * (fx * fx + fy * fy))
    return np.real(np.fft.ifft2(np.fft.fft2(img) * g))


def catmull_rom(pts, samples=40):
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = [np.array(p, float) for p in pts[i - 1:i + 3]]
        for t in np.linspace(0, 1, samples, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    out.append(np.array(pts[-2], float))
    return np.array(out)


def road_x(ys):
    c = catmull_rom(ROAD_CTRL)
    return np.interp(ys, c[:, 1], c[:, 0])


def rasterize_convex(mask, poly, px):
    """Fill a convex polygon (world xy) into mask."""
    poly = np.asarray(poly)
    n = mask.shape[0]
    i0 = max(int((poly[:, 0].min() - X0) / px) - 1, 0); i1 = min(int((poly[:, 0].max() - X0) / px) + 2, n)
    j0 = max(int((poly[:, 1].min() - Y0) / px) - 1, 0); j1 = min(int((poly[:, 1].max() - Y0) / px) + 2, n)
    if i1 <= i0 or j1 <= j0:
        return
    xs = X0 + (np.arange(i0, i1) + 0.5) * px
    ys = Y0 + (np.arange(j0, j1) + 0.5) * px
    X, Y = np.meshgrid(xs, ys)
    inside = np.ones_like(X, bool)
    m = len(poly)
    area = sum(poly[k, 0] * poly[(k + 1) % m, 1] - poly[(k + 1) % m, 0] * poly[k, 1] for k in range(m))
    sgn = 1.0 if area > 0 else -1.0
    for k in range(m):
        ax, ay = poly[k]; bx, by = poly[(k + 1) % m]
        inside &= sgn * ((bx - ax) * (Y - ay) - (by - ay) * (X - ax)) >= 0
    mask[j0:j1, i0:i1] |= inside


def convex_hull(points):
    pts = sorted(set(map(tuple, np.round(points, 4))))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0: lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0: upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def build_maps(footprints, n=2048, seed=11):
    """footprints: dict class -> list of convex polygons (world xy).
    Classes: 'house', 'wallpost' (wall stones, fence posts), 'other' (rocks, barrel, cart...).
    Returns height (m, float32 [n,n]), masks RGBA float [n,n,4], and diagnostics."""
    px = S / n
    xs = X0 + (np.arange(n) + 0.5) * px
    ys = Y0 + (np.arange(n) + 0.5) * px
    X, Y = np.meshgrid(xs, ys)

    xc = road_x(ys)
    slope = np.gradient(xc, ys)
    d = (X - xc[:, None]) / np.sqrt(1 + slope[:, None] ** 2)
    t = np.abs(d)

    f_low = spectral_noise(n, 3.6, seed + 1, fmin=2.0)
    f_mid = spectral_noise(n, 2.6, seed + 2)
    f_mid2 = spectral_noise(n, 2.8, seed + 3)
    f_hi = spectral_noise(n, 1.9, seed + 4)
    f_churn = spectral_noise(n, 1.7, seed + 5)

    # footprints
    fp = {k: np.zeros((n, n), bool) for k in ("house", "wallpost", "other")}
    for k, polys in footprints.items():
        for poly in polys:
            if len(poly) >= 3:
                rasterize_convex(fp[k], poly, px)
    fp_all = (fp["house"] | fp["wallpost"] | fp["other"]).astype(np.float32)

    # cross-section: sunken compacted track, soft shoulders, raised uneven verges
    sb = smoothstep(TRAVELED_HALF_WIDTH, 2.9, t + 0.28 * f_mid2)
    crown = 0.012 * np.exp(-(d / 0.42) ** 2)
    road_lvl = -0.035 + 0.004 * f_mid + 0.0015 * f_hi + 0.0045 * f_churn + crown   # churned mud lumps
    verge = 0.022 + 0.02 * f_low + 0.006 * f_mid + 0.0025 * f_hi
    verge = smooth_max(verge, WATER_LEVEL + 0.03)
    base = road_lvl * (1 - sb) + verge * sb
    base = smooth_max(base, WATER_LEVEL + 0.008, 0.004)

    # wheel ruts: shallow, wandering, depth varying along the road
    ny = n
    ruts = np.zeros((n, n), np.float32)
    track = np.zeros((n, n), np.float32)
    for side, sd in ((-1, 0), (1, 10)):
        wob = 0.05 * noise_1d(ny, 3.0, seed + 20 + sd)
        width = 0.14 * (1 + 0.22 * noise_1d(ny, 2.6, seed + 21 + sd))
        depth = np.clip(0.0105 + 0.0085 * noise_1d(ny, 1.7, seed + 22 + sd), 0.003, None)
        c = side * (0.78 + wob)
        u = (d - c[:, None]) / width[:, None]
        ruts += -depth[:, None] * np.exp(-np.abs(u) ** 2.6)
        ruts += 0.22 * depth[:, None] * np.exp(-((np.abs(u) - 1.7) / 0.55) ** 2)   # pushed-up lips
        c2 = side * (0.98 + wob * 0.6)
        ruts += -0.35 * depth[:, None] * np.exp(-(((d - c2[:, None]) / (width[:, None] * 0.8)) ** 2))
        track = np.maximum(track, np.exp(-(((d - c[:, None]) / (width[:, None] * 1.6)) ** 2)))
    ruts *= (1 - sb)
    track *= (1 - sb)

    # hoofprints along the centre line in the near stretch
    rng = np.random.default_rng(seed + 30)
    hoof = np.zeros((n, n), np.float32)
    yv = -6.0
    k = 0
    while yv < 22.0:
        yv += rng.uniform(0.28, 0.42)
        k += 1
        hx = float(road_x(np.array([yv]))[0]) + (0.11 if k % 2 else -0.11) + rng.normal(0, 0.04)
        r = rng.uniform(0.045, 0.06); dep = rng.uniform(0.008, 0.016)
        i0 = int((hx - 0.15 - X0) / px); j0 = int((yv - 0.15 - Y0) / px)
        w = int(0.3 / px) + 1
        sl = (slice(max(j0, 0), min(j0 + w, n)), slice(max(i0, 0), min(i0 + w, n)))
        dx = X[sl] - hx; dy = Y[sl] - yv
        rr = np.sqrt((dx / r) ** 2 + (dy / (r * 1.15)) ** 2)
        hoof[sl] += -dep * (1 - smoothstep(0.55, 1.05, rr)) + 0.25 * dep * np.exp(-((rr - 1.15) / 0.2) ** 2)
    hoof *= (1 - sb)

    # puddle depressions with irregular, noise-warped outlines
    warp = spectral_noise(n, 3.3, seed + 40)
    pud = np.zeros((n, n), np.float32)
    for (cx, cy, rx, ry, dep) in PUDDLES:
        rr = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2) * (1 + 0.22 * warp)
        pud = np.minimum(pud, -dep * (1 - smoothstep(0.2, 1.1, rr)))
    pud *= (1 - 0.7 * sb)

    # soil built up against wall footings, posts and house sills (keeps them grounded)
    mound = (0.06 * np.clip(gaussian_blur(fp["wallpost"].astype(np.float32), 0.16, px) * 4, 0, 1)
             + 0.03 * np.clip(gaussian_blur(fp["house"].astype(np.float32), 0.3, px) * 2.2, 0, 1)) * sb

    h = (base + ruts + hoof + pud + mound).astype(np.float32)

    # masks: R road surface, G sheltered litter zones, B wheel tracks, A obstacle footprints
    road = 1 - smoothstep(1.5, 2.85, t + 0.3 * f_mid2)
    shelter = np.clip(1.4 * gaussian_blur(fp_all, 0.55, px) + 2.2 * gaussian_blur(fp_all, 0.14, px), 0, 1)
    shelter = np.clip(shelter + 0.3 * np.exp(-((t - 2.8) / 0.45) ** 2) * (0.6 + 0.4 * f_mid), 0, 1)
    obstacle = np.clip(gaussian_blur(fp_all, 0.03, px) * 3.0, 0, 1)
    masks = np.stack([road, shelter, track, obstacle], -1).astype(np.float32)

    diag = {
        "px_m": px,
        "traveled_overlap_px": int(((t < TRAVELED_HALF_WIDTH) & (fp_all > 0.5)).sum()),
        "traveled_overlap_by_class": {k: int(((t < TRAVELED_HALF_WIDTH) & v).sum()) for k, v in fp.items()},
        "water_area_m2": float((h < WATER_LEVEL).sum() * px * px),
        "water_outside_road_m2": float(((h < WATER_LEVEL) & (t > 2.9)).sum() * px * px),
        "h_range": (float(h.min()), float(h.max())),
        "t": t, "d": d, "fp_all": fp_all, "track": track,
    }
    return h, masks, diag


def detail_tile(n=1024, seed=5, tile_m=1.6):
    """Tileable mud micro-height (grit, embedded pebbles, small pits), values 0..1."""
    rng = np.random.default_rng(seed)
    base = 0.5 * spectral_noise(n, 2.1, seed) + 0.25 * spectral_noise(n, 1.6, seed + 1)
    tile = base * 0.12
    px = tile_m / n
    yy, xx = np.mgrid[0:n, 0:n]
    def bumps(count, rmin, rmax, hmin, hmax, sign):
        nonlocal tile
        for _ in range(count):
            cx, cy = rng.uniform(0, n), rng.uniform(0, n)
            r = rng.uniform(rmin, rmax) / px
            hgt = rng.uniform(hmin, hmax) * sign
            w = int(r * 1.3) + 2
            ix = (np.arange(int(cx) - w, int(cx) + w + 1)) % n
            iy = (np.arange(int(cy) - w, int(cy) + w + 1)) % n
            gx, gy = np.meshgrid(np.arange(int(cx) - w, int(cx) + w + 1) - cx, np.arange(int(cy) - w, int(cy) + w + 1) - cy)
            q = np.clip(1 - (gx * gx + gy * gy) / (r * r), 0, None)
            tile[np.ix_(iy, ix)] += hgt * np.sqrt(q)
    bumps(2600, 0.0012, 0.004, 0.08, 0.25, 1)     # grit
    bumps(140, 0.005, 0.014, 0.3, 0.6, 1)         # embedded pebbles
    bumps(380, 0.002, 0.006, 0.05, 0.18, -1)      # pits
    tile -= tile.min()
    tile /= tile.max()
    return tile.astype(np.float32)
