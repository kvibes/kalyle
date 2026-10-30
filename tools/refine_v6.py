"""Refine pass: v5 -> v6, keeping the RenderMan texture pipeline intact.

Opens the saved v5 scene (baked textures) and keeps its layout and camera. It changes:
  * moon: smaller, with a generated lunar albedo map (maria, craters, ray system) instead of blotchy noise;
  * sky: clouds near the moon lit from behind (silver edges, soft glow), written as a new sky map;
  * fog: cooler, and the warm village lamp no longer scatters in it (it lights the road and wall instead);
  * foreground brush: twiggy dead shrubs carrying the baked dry leaves, along the stone wall, the fence,
    around the barrel and on the verges, seated on the terrain and kept off the traveled road;
  * road: more gravel; village windows: frames and sills.
Every new or changed material is image-based, vertex-coloured or constant, and is recorded in
textures_rman/manifest_haunted_village_v6.json for tools/renderman_setup.py.

Usage: python3 refine_v6.py <v5.blend> <v6.blend>
"""
import bpy, bmesh, math, random, sys, os, json
import numpy as np
from mathutils import Vector, Matrix
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ground_maps as gm
from shader_helpers import SG, new_mat, principled

IN_BLEND, OUT_BLEND = sys.argv[1], sys.argv[2]
RENDERS = os.path.dirname(os.path.abspath(OUT_BLEND))
TEX = os.path.join(RENDERS, "textures_rman")
bpy.ops.wm.open_mainfile(filepath=IN_BLEND)
scene = bpy.context.scene
cam = scene.camera.matrix_world.translation.copy()
with open(os.path.join(TEX, "manifest.json")) as fh:
    manifest = json.load(fh)
log = {"added": [], "changed": []}


def srgb_to_lin(a):
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(a):
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, 12.92 * a, 1.055 * a ** (1 / 2.4) - 0.055)


def sphere_dirs(w, h):
    """Directions for an equirect texture in Blender's UV-sphere layout (u=0 at -X, v=1 at +Z)."""
    u = (np.arange(w) + 0.5) / w
    v = (np.arange(h) + 0.5) / h
    phi = 2 * np.pi * (u - 0.5)
    el = np.pi * (v - 0.5)
    P, E = np.meshgrid(phi, el)
    return np.stack([np.cos(E) * np.cos(P), np.cos(E) * np.sin(P), np.sin(E)], -1)   # row 0 = v near 0 (bottom)


def obj_with_mat(name):
    return next(o for o in scene.objects if o.type == "MESH" and o.material_slots and o.material_slots[0].material
                and o.material_slots[0].material.name == name)


# ------------------------------------------------------------------ 1. moon: generated lunar albedo, smaller disc
moon = obj_with_mat("moon")
f = (cam - moon.matrix_world.translation).normalized()            # moon -> camera
look = -f
right = look.cross(Vector((0, 0, 1))).normalized()
up = right.cross(look).normalized()
MW, MH = 2048, 1024
n = sphere_dirs(MW, MH)
fv, rv, uv_ = (np.array(v_, dtype=np.float32) for v_ in (f, right, up))
x, y = n @ rv, n @ uv_                                             # orthographic disc coordinates
rng = np.random.default_rng(42)
fbm = 0.6 * gm.spectral_noise(MW, 2.2, 7)[:MH] + 0.4 * gm.spectral_noise(MW, 1.6, 8)[:MH]
warp = gm.spectral_noise(MW, 2.8, 9)[:MH]
maria = np.zeros((MH, MW), np.float32)
for cx, cy, rx, ry, dep in [(-0.30, 0.28, 0.30, 0.22, 0.9), (-0.50, -0.05, 0.26, 0.42, 0.75), (0.13, 0.32, 0.17, 0.15, 0.85),
                            (0.27, 0.06, 0.21, 0.17, 0.85), (0.63, 0.22, 0.10, 0.12, 0.9), (-0.16, -0.36, 0.20, 0.13, 0.65),
                            (0.36, -0.24, 0.13, 0.11, 0.6)]:
    r = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2) * (1 + 0.18 * warp)
    maria = np.maximum(maria, dep * (1 - gm.smoothstep(0.55, 1.1, r)))
alb = 0.67 - 0.31 * maria + 0.045 * fbm
craters = rng.normal(size=(320, 3)); craters /= np.linalg.norm(craters, axis=1, keepdims=True)
craters[:220] = craters[:220] * 0.4 + fv * 0.9                     # most on the visible side
craters /= np.linalg.norm(craters, axis=1, keepdims=True)
for i, c in enumerate(craters.astype(np.float32)):
    rad = np.radians(rng.uniform(0.6, 3.5) if i > 6 else rng.uniform(4, 7))
    ang = np.arccos(np.clip(n @ c, -1, 1)) / rad
    alb += np.where(ang < 1, -0.035 * (1 - ang ** 2), 0) + 0.05 * np.exp(-((ang - 1) / 0.18) ** 2) * (1 - 0.6 * maria)
tycho = (-0.12 * rv - 0.62 * uv_ + np.sqrt(1 - 0.12 ** 2 - 0.62 ** 2) * fv); tycho /= np.linalg.norm(tycho)
ang = np.degrees(np.arccos(np.clip(n @ tycho, -1, 1)))
bearing = np.arctan2(n @ np.cross(tycho, fv), n @ (fv - tycho * (fv @ tycho)) + 1e-6)
rays = np.clip(np.sin(bearing * 9 + 2.0) * np.sin(bearing * 5) , 0, 1) ** 3
alb += 0.07 * rays * np.exp(-ang / 30) * (ang > 3) + 0.06 * np.exp(-(ang / 4) ** 2)
alb = np.clip(alb, 0.12, 0.95)
rgb = np.stack([alb * 1.0, alb * 0.985, alb * 0.95], -1)
moon_png = os.path.join(TEX, "moon_albedo_v6.png")
Image.fromarray(np.flipud((lin_to_srgb(rgb * 0.85) * 255 + 0.5).astype(np.uint8)), "RGB").save(moon_png, optimize=True)
mm = bpy.data.materials["moon"]
for nd in mm.node_tree.nodes:
    if nd.bl_idname == "ShaderNodeTexImage":
        nd.image = bpy.data.images.load(moon_png, check_existing=True); nd.image.colorspace_settings.name = "sRGB"
    if nd.bl_idname == "ShaderNodeEmission":
        nd.inputs["Strength"].default_value = 1.9
moon.scale = (0.72, 0.72, 0.72)
manifest["materials"]["moon"] = {"kind": "emissive", "maps": {"emission": "textures_rman/moon_albedo_v6.png"}, "constants": {"intensity": 1.9}}
log["changed"].append("moon: radius 9 -> 6.5 m, generated lunar albedo (7 maria, 320 craters, a rayed crater) replaces the blotchy noise; emission 3.6 -> 1.9 so the maria and craters read")

halo = next((o for o in scene.objects if o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "halo"), None)
if halo:
    for nd in halo.material_slots[0].material.node_tree.nodes:
        if nd.bl_idname == "ShaderNodeMath" and nd.operation == "MULTIPLY" and abs(nd.inputs[1].default_value - 1.6) < 1e-3:
            nd.inputs[1].default_value = 2.3
            log["changed"].append("moon halo card: glow 1.6 -> 2.3 (Cycles only)")

# ------------------------------------------------------------------ 2. sky: clouds lit around the moon (new map)
sky = obj_with_mat("sky")
sky_src = os.path.join(TEX, "sky_emission.png")
s_img = srgb_to_lin(np.flipud(np.asarray(Image.open(sky_src).convert("RGB")).astype(np.float32) / 255.0))
SH, SW = s_img.shape[:2]
dn = sphere_dirs(SW, SH) * sky.scale.x                             # dome points
view = dn - np.array(cam, dtype=np.float32)
view /= np.linalg.norm(view, axis=-1, keepdims=True)
mdir = np.array((moon.matrix_world.translation - cam).normalized(), dtype=np.float32)
ang = np.degrees(np.arccos(np.clip(view @ mdir, -1, 1)))
lum = s_img @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
cloud = gm.smoothstep(0.02, 0.14, lum)
g1, g2 = np.exp(-(ang / 9.0) ** 2), np.exp(-(ang / 28.0) ** 2)
lit = s_img * (1 + (cloud * (2.0 * g1 + 0.35 * g2))[..., None])
lit += np.array([0.55, 0.62, 0.78], dtype=np.float32) * (0.03 * g1 + 0.012 * g2)[..., None]
lit *= (0.8 + 0.2 * np.exp(-(ang / 60.0) ** 2))[..., None]        # deeper blue away from the moon
SKY_SCALE = 0.4                                                   # headroom: lit cloud edges stay below 1.0 in the 8-bit map
sky_png = os.path.join(TEX, "sky_emission_v6.png")
Image.fromarray(np.flipud((lin_to_srgb(lit * SKY_SCALE) * 255 + 0.5).astype(np.uint8)), "RGB").save(sky_png, optimize=True)
sm = bpy.data.materials["sky"]
for nd in sm.node_tree.nodes:
    if nd.bl_idname == "ShaderNodeTexImage":
        nd.image = bpy.data.images.load(sky_png, check_existing=True); nd.image.colorspace_settings.name = "sRGB"
    if nd.bl_idname == "ShaderNodeEmission":
        base = nd.inputs["Strength"].default_value
        nd.inputs["Strength"].default_value = base / SKY_SCALE
manifest["materials"]["sky"] = {"kind": "emissive", "maps": {"emission": "textures_rman/sky_emission_v6.png"},
                                "constants": {"intensity": round(base / SKY_SCALE, 4)}}
log["changed"].append("sky: clouds within ~30 deg of the moon lit from behind (silver edges, soft glow), far sky up to 20% darker; new map sky_emission_v6.png")

# ------------------------------------------------------------------ 3. fog colour and the warm village lamp
for nd in bpy.data.materials["mist"].node_tree.nodes:
    if nd.bl_idname == "ShaderNodeVolumeScatter":
        nd.inputs["Color"].default_value = (0.5, 0.62, 0.92, 1)
for nd in scene.world.node_tree.nodes:
    if nd.bl_idname == "ShaderNodeVolumeScatter":
        nd.inputs["Color"].default_value = (0.5, 0.6, 0.9, 1)
manifest["volumes"]["mist"]["color"] = [0.5, 0.62, 0.92]
manifest["volumes"]["world"]["color"] = [0.5, 0.6, 0.9]
vl_ = bpy.data.objects["vlight"]
vl_.visible_volume_scatter = False
vl_.data.energy = 1200.0; vl_.data.shadow_soft_size = 1.0
log["changed"].append("fog: mist and world volume colours cooler; vlight (warm village lamp) 500 -> 1200 W, radius 1 m, no longer scatters in the fog")

# ------------------------------------------------------------------ helpers: terrain height, road distance
himg = bpy.data.images["terrain_height_2048.png"]
hn = himg.size[0]
hpx = np.empty(hn * hn * 4, np.float32); himg.pixels.foreach_get(hpx)
hmap = hpx.reshape(hn, hn, 4)[..., 0] * (gm.H_MAX - gm.H_MIN) + gm.H_MIN


def terrain_h(x_, y_):
    fx = (x_ - gm.X0) / gm.S * hn - 0.5; fy = (y_ - gm.Y0) / gm.S * hn - 0.5
    i, j = int(np.clip(np.floor(fx), 0, hn - 2)), int(np.clip(np.floor(fy), 0, hn - 2))
    tx, ty = min(max(fx - i, 0.0), 1.0), min(max(fy - j, 0.0), 1.0)
    return float((hmap[j, i] * (1 - tx) + hmap[j, i + 1] * tx) * (1 - ty) + (hmap[j + 1, i] * (1 - tx) + hmap[j + 1, i + 1] * tx) * ty)


def road_dist(x_, y_):
    return abs(x_ - float(gm.road_x(np.array([y_]))[0]))


# ------------------------------------------------------------------ 4. foreground brush
twig_m, nt, out = new_mat("brush_twig")
g = SG(nt)
ca = g.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name="bake_col").outputs["Color"]
principled(g, out, ca, 0.85)
leaf_mats = [bpy.data.materials["leaf_litter_%d" % i] for i in range(6)]
leaf_meshes = sorted([o.data for o in bpy.data.objects if o.name.startswith("leaf_") and o.type == "MESH"], key=lambda m_: m_.name)


def shrub_mesh(name, seed, height, spread, leafiness):
    rng_ = random.Random(seed)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    col = bm.verts.layers.float_color.new("bake_col")
    tips = []

    def tube(pts, r0, r1, shade):
        rings = []
        for i, p in enumerate(pts):
            t = i / (len(pts) - 1)
            d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            side = d.cross(Vector((0.3, 0.7, 0.1))).normalized()
            upv = side.cross(d).normalized()
            r = r0 + (r1 - r0) * t
            ring = []
            for k in range(4):
                a = 2 * math.pi * k / 4
                v_ = bm.verts.new(p + (side * math.cos(a) + upv * math.sin(a)) * r)
                c = shade * (0.75 + 0.5 * t)
                v_[col] = (0.13 * c, 0.098 * c, 0.068 * c, 1.0) if rng_.random() > 0.15 else (0.17 * c, 0.085 * c, 0.048 * c, 1.0)
                ring.append(v_)
            rings.append(ring)
        for a_, b_ in zip(rings[:-1], rings[1:]):
            for k in range(4):
                fc = bm.faces.new((a_[k], a_[(k + 1) % 4], b_[(k + 1) % 4], b_[k]))
                fc.material_index = 0

    def branch(p0, d, length, r, depth):
        segs = 4
        pts = [p0]
        dd = d.normalized()
        for _ in range(segs):
            dd = (dd + Vector((rng_.gauss(0, 0.22), rng_.gauss(0, 0.22), rng_.gauss(0.02, 0.12)))).normalized()
            pts.append(pts[-1] + dd * (length / segs))
        tube(pts, r, r * 0.45, rng_.uniform(0.8, 1.2))
        if depth == 0 or r < 0.0012:
            tips.append((pts[-1], dd))
            return
        for _ in range(rng_.choice((1, 2, 2, 3))):
            k = rng_.randint(1, segs)
            nd_ = (dd + Vector((rng_.gauss(0, 0.8), rng_.gauss(0, 0.8), rng_.uniform(-0.1, 0.5)))).normalized()
            branch(pts[k], nd_, length * rng_.uniform(0.45, 0.7), r * 0.55, depth - 1)
        tips.append((pts[-1], dd))

    for s in range(rng_.randint(6, 10)):
        a = rng_.uniform(0, 2 * math.pi)
        base = Vector((math.cos(a), math.sin(a), 0)) * rng_.uniform(0, spread * 0.25) + Vector((0, 0, -0.03))
        d = Vector((math.cos(a) * rng_.uniform(0.15, 0.6), math.sin(a) * rng_.uniform(0.15, 0.6), 1.0))
        branch(base, d, height * rng_.uniform(0.55, 0.85), rng_.uniform(0.006, 0.011), 3)
    # dry leaves on a share of the twig tips (real leaf geometry, keeping each shape's baked material and UVs)
    for p, d in tips:
        if rng_.random() > leafiness:
            continue
        for _ in range(rng_.choice((1, 1, 2, 3))):
            li = rng_.randrange(len(leaf_meshes))
            lm = leaf_meshes[li]
            s_ = rng_.uniform(0.045, 0.075)
            rot = (Matrix.Rotation(rng_.uniform(0, 6.28), 4, "Z") @ Matrix.Rotation(rng_.uniform(-1.2, 1.2), 4, "X")
                   @ Matrix.Rotation(rng_.uniform(-0.6, 0.6), 4, "Y"))
            M = Matrix.Translation(p) @ rot @ Matrix.Scale(s_, 4)
            luv = lm.uv_layers.active
            vmap = [bm.verts.new(M @ v_.co) for v_ in lm.vertices]
            for v_ in vmap:
                v_[col] = (0.1, 0.06, 0.03, 1.0)
            for poly in lm.polygons:
                try:
                    fc = bm.faces.new([vmap[i] for i in poly.vertices])
                except ValueError:
                    continue
                fc.material_index = 1 + li
                for loop, li_ in zip(fc.loops, poly.loop_indices):
                    loop[uvl].uv = luv.data[li_].uv
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    me.materials.append(twig_m)
    for lmat in leaf_mats:
        me.materials.append(lmat)
    me.color_attributes.active_color = me.color_attributes["bake_col"]
    me.color_attributes.render_color_index = list(me.color_attributes).index(me.color_attributes["bake_col"])
    for poly in me.polygons:
        poly.use_smooth = True
    return me


variants = [shrub_mesh("brush_%d" % i, 700 + i, h, sp, lf) for i, (h, sp, lf) in
            enumerate([(1.0, 0.9, 0.7), (0.75, 0.8, 0.6), (1.2, 1.1, 0.75), (0.6, 0.7, 0.5), (0.9, 1.0, 0.65)])]
c_brush = bpy.data.collections.new("Refine_v6")
scene.collection.children.link(c_brush)
spots = []
for t in np.linspace(0.02, 0.98, 11):                              # road side of the stone wall
    wx, wy = -1.0 - 2.6 * t, 0.5 + 11.5 * t
    spots.append((wx - 0.55, wy, 1.0))
for t in np.linspace(0.05, 0.95, 6):                               # yard side of the wall
    spots.append((-1.0 - 2.6 * t + 0.6, 0.5 + 11.5 * t, 0.9))
spots += [(-0.5, 0.35, 0.8), (1.35, 0.05, 0.85), (1.9, -1.0, 0.7), (-0.9, -0.9, 0.6),        # around the barrel
          (2.7, -1.6, 0.8), (4.4, -0.7, 1.0), (5.7, -1.7, 0.9), (3.6, 0.5, 0.9), (6.6, -0.4, 1.1),  # foreground right
          (0.3, 1.55, 0.9), (2.5, 1.7, 0.8), (4.3, 1.55, 1.0), (6.1, 1.45, 0.9),                  # front fence line
          (-9.3, -3.0, 0.8), (-9.7, 1.0, 0.9), (-10.0, 4.8, 1.0), (-10.2, 8.4, 0.9), (-9.0, -5.8, 0.7)]  # village verge
rng = random.Random(77)
placed = 0
for (sx, sy, sc) in spots:
    sx += rng.uniform(-0.2, 0.2); sy += rng.uniform(-0.25, 0.25)
    if road_dist(sx, sy) < gm.TRAVELED_HALF_WIDTH + 0.35:
        continue
    o = bpy.data.objects.new("brush", rng.choice(variants))
    o.location = (sx, sy, terrain_h(sx, sy))
    o.rotation_euler = (rng.uniform(-0.06, 0.06), rng.uniform(-0.06, 0.06), rng.uniform(0, 6.28))
    s_ = sc * rng.uniform(0.85, 1.15)
    o.scale = (s_, s_, s_ * rng.uniform(0.85, 1.1))
    c_brush.objects.link(o)
    placed += 1
manifest["materials"]["brush_twig"] = {"kind": "vertex_color", "primvar": "Cs", "constants": {"roughness": 0.85}, "translucency": 0.0}
log["added"].append("foreground brush: 5 twiggy shrub meshes (tapered twigs, dry leaves reusing the 6 baked leaf materials), %d placements "
                    "along the wall, fence, barrel, foreground and verges, seated on the terrain, none within %.2f m of the road centreline"
                    % (placed, gm.TRAVELED_HALF_WIDTH + 0.35))

# warm light raking in from just outside the frame on the right, as in the reference's foreground
yl = bpy.data.lights.new("yard_spill", "AREA")
yl.energy = 450.0; yl.color = (1.0, 0.62, 0.3); yl.shape = "DISK"; yl.size = 2.0
yo = bpy.data.objects.new("yard_spill", yl)
yo.location = (9.0, -2.5, 2.2)
yo.rotation_euler = (Vector((-0.5, 1.0, 0.4)) - yo.location).to_track_quat("-Z", "Y").to_euler()
yo.visible_glossy = False
c_brush.objects.link(yo)
log["added"].append("yard_spill: 450 W warm 2 m disc light just outside the frame on the right, raking across the barrel, wall and brush")

# ------------------------------------------------------------------ 5. road gravel
terr = bpy.data.objects["terrain_gn"]
mod = terr.modifiers["GN_TerrainGround"]
ids = {it.name: it.identifier for it in mod.node_group.interface.items_tree if getattr(it, "in_out", "") == "INPUT"}
getattr(mod.properties.inputs, ids["Pebble Density"]).value = 3.0
log["changed"].append("road: pebble density x3 (more gravel on the road and shoulders; wheel tracks still kept mostly clear)")

# ------------------------------------------------------------------ 6. village window frames
vt = bpy.data.materials.get("village_trim") or new_mat("village_trim")[0]
if not vt.node_tree.nodes.get("Principled BSDF"):
    g = SG(vt.node_tree); principled(g, vt.node_tree.nodes["Material Output"], (0.05, 0.045, 0.038, 1), 0.8)
cube = bpy.data.meshes["unit_cube"]
framed = 0
for w in [o for o in scene.objects if o.name.split(".")[0] in ("vw", "w2")]:
    M = Matrix.Translation(w.location) @ w.rotation_euler.to_matrix().to_4x4()
    hw, hh = w.scale.x, w.scale.z
    for (lx, ly, lz, sx, sy, sz) in [(-hw - 0.03, -0.03, 0, 0.06, 0.05, 2 * hh + 0.12), (hw + 0.03, -0.03, 0, 0.06, 0.05, 2 * hh + 0.12),
                                     (0, -0.03, hh + 0.03, 2 * hw + 0.12, 0.05, 0.06), (0, -0.03, -hh - 0.03, 2 * hw + 0.12, 0.05, 0.06),
                                     (0, -0.07, -hh - 0.08, 2 * hw + 0.2, 0.12, 0.05)]:
        fo = bpy.data.objects.new("village_frame", cube)
        fo.material_slots[0].link = "OBJECT"; fo.material_slots[0].material = vt
        fo.matrix_world = M @ Matrix.Translation((lx, ly, lz)) @ Matrix.Diagonal((sx / 2, sy / 2, sz / 2, 1))
        c_brush.objects.link(fo)
    framed += 1
manifest["materials"]["village_trim"] = {"kind": "surface", "maps": {}, "constants": {"baseColor": [0.05, 0.045, 0.038], "roughness": 0.8, "ior": 1.5, "metallic": 0.0}}
log["added"].append("frames and sills on %d village and right-hand-house windows" % framed)

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True, relative_remap=True)
manifest["notes"] = manifest.get("notes", []) + ["v6: brush twigs use a vertex colour (Cs); brush leaves reuse leaf_litter_0..5."]
mpath = os.path.join(TEX, "manifest_%s.json" % os.path.splitext(os.path.basename(OUT_BLEND))[0])
with open(mpath, "w") as fh:
    json.dump(manifest, fh, indent=1)
with open(os.path.join(RENDERS, "refine_v6_log.json"), "w") as fh:
    json.dump(log, fh, indent=1)
print(json.dumps(log, indent=1))
print("saved", OUT_BLEND, "and", mpath)
