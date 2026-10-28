"""Ground detail pass for the haunted village: v2 -> v3.

Opens the saved v2 scene (it does not rerun the scene-generation script), then:
  * generates world-space height + mask maps and a tileable mud micro-height map,
  * replaces the flat road strip and disc puddles with a Geometry Nodes terrain whose
    vertex density follows the camera (dense near, coarse far) and is displaced by the height map,
  * fills puddles with a water surface at one level, so water only shows in real depressions,
  * scatters embedded pebbles, fallen leaves, twigs and dry grass as GN instances, steered by
    the masks (road, wheel tracks, sheltered corners, obstacle footprints),
  * saves haunted_village_v3.blend with the maps packed.

Usage: python3 ground_detail.py <in.blend> <out.blend> <texture_dir>
"""
import bpy, bmesh, math, random, sys, os, json
import numpy as np
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ground_maps as gm

IN_BLEND, OUT_BLEND, TEX_DIR = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(TEX_DIR, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=IN_BLEND)
scene = bpy.context.scene
cam = scene.camera
W = gm.WATER_LEVEL
log = {"removed": [], "added": [], "changed": []}

# ---------------------------------------------------------------- footprints from the scene
VOLUME_MATS = {"mist", "smoke", "sky", "halo", "moon"}


def classify(o):
    n = o.name.split(".")[0]
    if n in ("main", "house2", "vh", "lh"):
        return "house"
    if n in ("st", "post", "fpost"):
        return "wallpost"
    return "other"


footprints = {"house": [], "wallpost": [], "other": []}
contact_objs = []
for o in scene.objects:
    if o.type != "MESH" or not o.visible_get():
        continue
    base = o.name.split(".")[0]
    if base.startswith(("weeds", "tree", "road", "puddle")) or base in ("cb", "w", "f", "m", "door", "portico"):
        continue
    if any(s.material and s.material.name.split(".")[0] in VOLUME_MATS for s in o.material_slots):
        continue
    if o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "ground":
        continue
    mw = o.matrix_world
    pts = [mw @ v.co for v in o.data.vertices]
    if not pts:
        continue
    lo = [p for p in pts if p.z < 0.12]
    if len(lo) < 3:
        continue
    span = max(p.x for p in pts) - min(p.x for p in pts)
    if span > 40:
        continue
    hull = gm.convex_hull(np.array([(p.x, p.y) for p in lo]))
    footprints[classify(o)].append(hull)
    contact_objs.append(o)

# ---------------------------------------------------------------- maps
print("building maps ...")
height, masks, diag = gm.build_maps(footprints)
tile = gm.detail_tile()

from PIL import Image


def save_u16(arr01, path):
    Image.fromarray(np.flipud(np.clip(arr01 * 65535 + 0.5, 0, 65535)).astype(np.uint16)).save(path)


h01 = (height - gm.H_MIN) / (gm.H_MAX - gm.H_MIN)
save_u16(h01, os.path.join(TEX_DIR, "terrain_height_2048.png"))
m_small = masks.reshape(1024, 2, 1024, 2, 4).mean(axis=(1, 3))
Image.fromarray(np.flipud(np.clip(m_small * 255 + 0.5, 0, 255)).astype(np.uint8), "RGBA").save(os.path.join(TEX_DIR, "terrain_masks_1024.png"))
save_u16(tile, os.path.join(TEX_DIR, "mud_detail_tile_1024.png"))


def load_img(name, packed_alpha=False):
    img = bpy.data.images.load(os.path.join(TEX_DIR, name))
    img.colorspace_settings.name = "Non-Color"
    if packed_alpha:
        img.alpha_mode = "CHANNEL_PACKED"
    img.pack()
    return img


img_h = load_img("terrain_height_2048.png")
img_m = load_img("terrain_masks_1024.png", packed_alpha=True)
img_d = load_img("mud_detail_tile_1024.png")
log["added"] += ["image terrain_height_2048.png (16-bit)", "image terrain_masks_1024.png (RGBA 8-bit)", "image mud_detail_tile_1024.png (16-bit)"]

# contact check against the new terrain (bottom vertices vs. height under them)
def h_at(x, y):
    n = height.shape[0]
    i = int(np.clip((x - gm.X0) / gm.S * n, 0, n - 1)); j = int(np.clip((y - gm.Y0) / gm.S * n, 0, n - 1))
    return float(height[j, i])


def contact_gaps():
    """Lowest-vertex clearance above the terrain for unparented ground-contact objects.
    Barrel hoops (parented) are skipped: the barrel rests on its bulge, so its end hoops sit
    slightly above the ground by design. Wagon spokes never reach the ground (the rim does)."""
    gaps = []
    for o in contact_objs:
        if o.parent is not None or o.name.split(".")[0] == "sp":
            continue
        mw = o.matrix_world
        low = min((mw @ v.co for v in o.data.vertices), key=lambda p: p.z)
        gaps.append((o, low.z - h_at(low.x, low.y)))
    return gaps


floating_before = [(o.name, round(gp, 3)) for o, gp in contact_gaps() if gp > 0.005]
for o, gp in contact_gaps():
    if gp > 0.005:
        o.location.z -= gp + 0.01
        log["changed"].append("%s lowered %.3f m to sit on the new terrain" % (o.name, gp + 0.01))
bpy.context.view_layer.update()
floating = [(o.name, round(gp, 3)) for o, gp in contact_gaps() if gp > 0.005]

# ---------------------------------------------------------------- shader helpers
def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    return m, nt, nt.nodes["Material Output"]


class SG:
    """Tiny shader-graph builder."""
    def __init__(self, nt): self.nt = nt; self.n = nt.nodes; self.l = nt.links
    def node(self, t, **kw):
        nd = self.n.new(t)
        for k, v in kw.items(): setattr(nd, k, v)
        return nd
    def put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket): self.l.new(v, sock)
        else: sock.default_value = v
    def math(self, op, a, b=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(nd.inputs[0], a)
        if b is not None: self.put(nd.inputs[1], b)
        return nd.outputs[0]
    def mix(self, fac, a, b, kind="RGBA"):
        nd = self.node("ShaderNodeMix", data_type=kind)
        if kind == "RGBA":
            self.put(nd.inputs["Factor"], fac); self.put(nd.inputs[6], a); self.put(nd.inputs[7], b)
            return nd.outputs[2]
        self.put(nd.inputs["Factor"], fac); self.put(nd.inputs[2], a); self.put(nd.inputs[3], b)
        return nd.outputs[0]
    def maprange(self, v, a, b, c, d):
        nd = self.node("ShaderNodeMapRange", clamp=True)
        self.put(nd.inputs["Value"], v); nd.inputs["From Min"].default_value = a; nd.inputs["From Max"].default_value = b
        nd.inputs["To Min"].default_value = c; nd.inputs["To Max"].default_value = d
        return nd.outputs["Result"]
    def sep(self, v):
        nd = self.node("ShaderNodeSeparateXYZ"); self.put(nd.inputs[0], v); return nd.outputs
    def comb(self, x, y, z=0.0):
        nd = self.node("ShaderNodeCombineXYZ")
        self.put(nd.inputs[0], x); self.put(nd.inputs[1], y); self.put(nd.inputs[2], z)
        return nd.outputs[0]
    def noise(self, vec, scale, detail=4.0, rough=0.55):
        nd = self.node("ShaderNodeTexNoise")
        self.put(nd.inputs["Vector"], vec); nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail; nd.inputs["Roughness"].default_value = rough
        return nd.outputs[0]
    def img(self, image, vec, interp="Linear", ext="REPEAT"):
        nd = self.node("ShaderNodeTexImage", interpolation=interp, extension=ext)
        nd.image = image; self.put(nd.inputs["Vector"], vec)
        return nd
    def ramp(self, fac, stops):
        nd = self.node("ShaderNodeValToRGB")
        self.put(nd.inputs["Fac"], fac)
        els = nd.color_ramp.elements
        while len(els) < len(stops): els.new(0.5)
        for e, (p, c) in zip(els, stops):
            e.position = p; e.color = (*c, 1.0)
        return nd.outputs["Color"]
    def attr(self, name, kind="INSTANCER"):
        return self.node("ShaderNodeAttribute", attribute_type=kind, attribute_name=name).outputs["Fac"]
    def wet_from_height(self, z, band=0.028):
        return self.maprange(z, W + band, W + 0.002, 0.0, 1.0)


def principled(g, out, color, rough, normal=None, translucent=0.0):
    b = g.node("ShaderNodeBsdfPrincipled")
    g.put(b.inputs["Base Color"], color); g.put(b.inputs["Roughness"], rough)
    if normal is not None: g.put(b.inputs["Normal"], normal)
    shader = b.outputs[0]
    if translucent > 0:
        tr = g.node("ShaderNodeBsdfTranslucent"); g.put(tr.inputs["Color"], color)
        if normal is not None: g.put(tr.inputs["Normal"], normal)
        mx = g.node("ShaderNodeMixShader"); mx.inputs[0].default_value = translucent
        g.l.new(shader, mx.inputs[1]); g.l.new(tr.outputs[0], mx.inputs[2]); shader = mx.outputs[0]
    g.l.new(shader, out.inputs["Surface"])
    return b


# ---------------------------------------------------------------- terrain material
mat_terrain, nt, out = new_mat("terrain_mud")
g = SG(nt)
P = g.node("ShaderNodeNewGeometry").outputs["Position"]
px_, py_, pz_ = g.sep(P)
uv_map = g.comb(g.math("DIVIDE", g.math("SUBTRACT", px_, gm.X0), gm.S), g.math("DIVIDE", g.math("SUBTRACT", py_, gm.Y0), gm.S))
mk = g.img(img_m, uv_map, "Linear", "EXTEND")
mks = g.node("ShaderNodeSeparateColor"); g.put(mks.inputs[0], mk.outputs["Color"])
road, shelter, track = mks.outputs[0], mks.outputs[1], mks.outputs[2]
d1 = g.img(img_d, g.comb(g.math("DIVIDE", px_, 1.6), g.math("DIVIDE", py_, 1.6))).outputs["Color"]
rx = g.math("ADD", g.math("MULTIPLY", px_, 0.799), g.math("MULTIPLY", py_, 0.602))
ry = g.math("SUBTRACT", g.math("MULTIPLY", py_, 0.799), g.math("MULTIPLY", px_, 0.602))
d2 = g.img(img_d, g.comb(g.math("ADD", g.math("DIVIDE", rx, 2.3), 0.37), g.math("ADD", g.math("DIVIDE", ry, 2.3), 0.71))).outputs["Color"]
tile_mix = g.maprange(g.noise(P, 0.35, 2.0), 0.4, 0.6, 0.0, 1.0)
micro = g.sep(g.mix(tile_mix, d1, d2))[0]
wetz = g.wet_from_height(pz_)
damp = g.math("ADD", g.math("MULTIPLY", road, 0.3), g.math("MULTIPLY", track, 0.3), clamp=True)
wet = g.math("MAXIMUM", wetz, damp)
var = g.noise(P, 1.3, 6.0, 0.6)
mud = g.mix(g.math("ADD", g.math("MULTIPLY", var, 0.7), g.math("MULTIPLY", micro, 0.5)), (0.017, 0.013, 0.0095, 1), (0.052, 0.04, 0.028, 1))
leafmold = g.noise(P, 4.0, 5.0, 0.6)
verge = g.mix(leafmold, (0.018, 0.015, 0.01, 1), (0.062, 0.047, 0.027, 1))
darken = g.maprange(wet, 0.0, 1.0, 1.0, 0.4)
cm = g.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
cm.inputs["Factor"].default_value = 1.0
g.l.new(g.mix(road, verge, mud), cm.inputs[6]); g.l.new(g.comb(darken, darken, darken), cm.inputs[7])
col = cm.outputs[2]
# rough on grit and clods, slicker in micro-hollows where water lingers; never mirror-like
rough = g.mix(road, 0.92, 0.8, "FLOAT")
hollow = g.math("SUBTRACT", 1.0, g.maprange(micro, 0.25, 0.6, 0.0, 1.0))
rough = g.math("SUBTRACT", rough, g.math("MULTIPLY", g.math("MULTIPLY", damp, hollow), 0.35))
rough = g.mix(wetz, rough, 0.5, "FLOAT")
rough = g.math("ADD", rough, g.math("MULTIPLY", g.math("SUBTRACT", var, 0.5), 0.1), clamp=True)
clods = g.node("ShaderNodeBump"); clods.inputs["Distance"].default_value = 0.01
g.put(clods.inputs["Strength"], g.maprange(wetz, 0.0, 1.0, 0.8, 0.1))
g.put(clods.inputs["Height"], g.noise(P, 6.0, 3.0, 0.5))
bump = g.node("ShaderNodeBump")
bump.inputs["Distance"].default_value = 0.012
g.put(bump.inputs["Strength"], g.maprange(wetz, 0.0, 1.0, 1.0, 0.12))
g.put(bump.inputs["Height"], micro)
g.l.new(clods.outputs["Normal"], bump.inputs["Normal"])
bt_ = principled(g, out, col, rough, bump.outputs["Normal"])
bt_.inputs["IOR"].default_value = 1.4

# ---------------------------------------------------------------- water material (turbid, reflective)
mat_water, nt, out = new_mat("puddle_water")
g = SG(nt)
Pw = g.node("ShaderNodeNewGeometry").outputs["Position"]
ripple = g.node("ShaderNodeBump"); ripple.inputs["Strength"].default_value = 0.025
g.put(ripple.inputs["Height"], g.noise(Pw, 14.0, 3.0))
wr = g.math("ADD", 0.025, g.math("MULTIPLY", g.noise(Pw, 0.9, 2.0), 0.03))
b = principled(g, out, (0.016, 0.013, 0.01, 1), wr, ripple.outputs["Normal"])
b.inputs["IOR"].default_value = 1.333

# ---------------------------------------------------------------- asset materials
mat_leaf, nt, out = new_mat("leaf_litter")
g = SG(nt)
lr, ld = g.attr("leaf_rand"), g.attr("leaf_damp")
uv = g.node("ShaderNodeTexCoord").outputs["UV"]
lu, lv, _ = g.sep(uv)
mid = g.math("ABSOLUTE", g.math("SUBTRACT", lv, 0.5))
base_col = g.ramp(lr, [(0.0, (0.07, 0.035, 0.015)), (0.25, (0.13, 0.06, 0.022)), (0.5, (0.28, 0.14, 0.04)),
                       (0.7, (0.22, 0.09, 0.03)), (0.85, (0.12, 0.1, 0.04)), (1.0, (0.09, 0.06, 0.03))])
blot = g.maprange(g.noise(uv, 9.0, 4.0), 0.45, 0.7, 1.0, 0.55)
veins = g.math("SINE", g.math("MULTIPLY", g.math("SUBTRACT", g.math("MULTIPLY", lu, 14.0), g.math("MULTIPLY", mid, 9.0)), math.pi))
veins = g.maprange(veins, 0.82, 1.0, 1.0, 0.82)
midrib = g.maprange(mid, 0.0, 0.035, 1.25, 1.0)
edge = g.maprange(mid, 0.33, 0.5, 1.0, 0.7)
shade = g.math("MULTIPLY", g.math("MULTIPLY", blot, veins), g.math("MULTIPLY", midrib, edge))
shade = g.math("MULTIPLY", shade, g.maprange(ld, 0.0, 1.0, 1.0, 0.55))
lm = g.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); lm.inputs["Factor"].default_value = 1.0
g.l.new(base_col, lm.inputs[6]); g.l.new(g.comb(shade, shade, shade), lm.inputs[7])
lbump = g.node("ShaderNodeBump"); lbump.inputs["Strength"].default_value = 0.15; lbump.inputs["Distance"].default_value = 0.0005
g.put(lbump.inputs["Height"], g.math("MULTIPLY", veins, midrib))
principled(g, out, lm.outputs[2], g.maprange(ld, 0.0, 1.0, 0.68, 0.32), lbump.outputs["Normal"], translucent=0.12)

mat_grass, nt, out = new_mat("dry_grass")
g = SG(nt)
br, tr_ = g.attr("blade_rand", "GEOMETRY"), g.attr("tuft_rand")
gv = g.sep(g.node("ShaderNodeTexCoord").outputs["UV"])[1]
gcol = g.ramp(br, [(0.0, (0.05, 0.034, 0.018)), (0.35, (0.12, 0.085, 0.045)), (0.65, (0.24, 0.16, 0.065)), (0.85, (0.085, 0.085, 0.035)), (1.0, (0.16, 0.12, 0.06))])
gsh = g.math("MULTIPLY", g.maprange(gv, 0.0, 0.6, 0.5, 1.0), g.maprange(tr_, 0.0, 1.0, 0.75, 1.15))
gm_ = g.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); gm_.inputs["Factor"].default_value = 1.0
g.l.new(gcol, gm_.inputs[6]); g.l.new(g.comb(gsh, gsh, gsh), gm_.inputs[7])
principled(g, out, gm_.outputs[2], 0.7, None, translucent=0.2)

mat_peb, nt, out = new_mat("pebble")
g = SG(nt)
Pp = g.node("ShaderNodeNewGeometry").outputs["Position"]
pcol = g.ramp(g.attr("peb_rand"), [(0.0, (0.03, 0.029, 0.027)), (0.4, (0.065, 0.062, 0.057)), (0.75, (0.08, 0.066, 0.05)), (1.0, (0.11, 0.105, 0.095))])
ob = g.node("ShaderNodeTexCoord").outputs["Object"]
pv = g.maprange(g.noise(ob, 3.0, 6.0), 0.3, 0.7, 0.75, 1.15)
pw = g.wet_from_height(g.sep(Pp)[2], 0.05)
psh = g.math("MULTIPLY", pv, g.maprange(pw, 0.0, 1.0, 1.0, 0.5))
pm = g.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); pm.inputs["Factor"].default_value = 1.0
g.l.new(pcol, pm.inputs[6]); g.l.new(g.comb(psh, psh, psh), pm.inputs[7])
pb = g.node("ShaderNodeBump"); pb.inputs["Strength"].default_value = 0.35; pb.inputs["Distance"].default_value = 0.02
g.put(pb.inputs["Height"], g.noise(ob, 6.0, 8.0))
principled(g, out, pm.outputs[2], g.maprange(pw, 0.0, 1.0, 0.72, 0.28), pb.outputs["Normal"])

mat_twig, nt, out = new_mat("twig_bark")
g = SG(nt)
ob = g.node("ShaderNodeTexCoord").outputs["Object"]
tcol = g.mix(g.noise(ob, 30.0, 4.0), (0.03, 0.024, 0.019, 1), (0.07, 0.058, 0.045, 1))
principled(g, out, tcol, 0.85)

# ---------------------------------------------------------------- asset meshes
asset_root = bpy.data.collections.new("GroundAssets")
scene.collection.children.link(asset_root)


def asset_coll(name):
    c = bpy.data.collections.new(name)
    asset_root.children.link(c)
    return c


def mesh_obj(name, verts, faces, coll, mat, uvs=None, point_attr=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    if uvs is not None:
        uvl = me.uv_layers.new(name="UVMap")
        for f in me.polygons:
            for li in f.loop_indices:
                uvl.data[li].uv = uvs[me.loops[li].vertex_index]
    if point_attr is not None:
        a = me.attributes.new(point_attr[0], "FLOAT", "POINT")
        a.data.foreach_set("value", point_attr[1])
    for f in me.polygons:
        f.use_smooth = True
    me.materials.append(mat)
    me.validate()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    return o


def leaf(name, kind, seed, coll):
    rng = random.Random(seed)
    nt_, across = 16, (-1.0, -0.5, 0.0, 0.5, 1.0)
    fold = rng.uniform(0.04, 0.12); curl = rng.uniform(-0.12, 0.22); tip = rng.uniform(0.0, 0.3); roll = rng.uniform(0.05, 0.25)
    verts, uvs, faces = [], [], []
    for i in range(nt_ + 1):
        t = 0.01 + 0.98 * i / nt_
        if kind == "oak":
            w = 0.3 * math.sin(math.pi * t ** 0.9) ** 0.8 * (0.55 + 0.45 * abs(math.sin(math.pi * (t * 4.5 + 0.2))))
        elif kind == "lance":
            w = 0.15 * math.sin(math.pi * t) ** 0.75
        elif kind == "birch":
            w = 0.62 * t ** 0.55 * (1 - t) ** 0.95 * (1 + 0.06 * (1 - abs((t * 18) % 2 - 1)))
        else:  # ovate, finely toothed
            w = 0.36 * math.sin(math.pi * t ** 0.85) ** 0.9 * (1 + 0.05 * (1 - abs((t * 14) % 2 - 1)))
        w = max(w, 0.004)
        for a in across:
            y = a * w
            z = fold * abs(y) + curl * (t - 0.45) ** 2 + tip * max(0.0, t - 0.78) ** 2 * 6 + roll * a * a * w
            verts.append((t, y, z)); uvs.append((t, 0.5 + 0.5 * a))
    for i in range(nt_):
        for k in range(4):
            a0 = i * 5 + k
            faces.append((a0, a0 + 5, a0 + 6, a0 + 1))
    base = len(verts)  # petiole
    for x in (-0.14, 0.01):
        for y in (-0.007, 0.007):
            verts.append((x, y, 0.004 + (0.02 if x < 0 else 0.0))); uvs.append((0.0, 0.5))
    faces.append((base, base + 2, base + 3, base + 1))
    return mesh_obj(name, verts, faces, coll, mat_leaf, uvs)


def tuft(name, blades, hmin, hmax, wmin, wmax, seed, coll, segs=4):
    rng = random.Random(seed)
    verts, faces, uvs, attr = [], [], [], []
    for b in range(blades):
        ang = rng.uniform(0, 2 * math.pi); rad = rng.uniform(0, 0.05)
        out_a = ang + rng.gauss(0, 0.5)
        h = rng.uniform(hmin, hmax); lean = rng.uniform(0.15, 0.65) if rng.random() > 0.15 else rng.uniform(0.8, 1.2)
        w0 = rng.uniform(wmin, wmax); r_b = rng.random()
        dx, dy = math.cos(out_a), math.sin(out_a); wx, wy = -dy, dx
        bx, by = rad * math.cos(ang), rad * math.sin(ang)
        start = len(verts)
        for s in range(segs + 1):
            t = s / segs
            px_ = bx + dx * lean * h * t * t; py_ = by + dy * lean * h * t * t
            pz = -0.015 + h * t * (1 - 0.3 * lean * t * t)
            w = w0 * (1 - t ** 1.4) + 0.0002
            verts += [(px_ - wx * w / 2, py_ - wy * w / 2, pz), (px_ + wx * w / 2, py_ + wy * w / 2, pz)]
            uvs += [(0.0, t), (1.0, t)]; attr += [r_b, r_b]
        for s in range(segs):
            a0 = start + 2 * s
            faces.append((a0, a0 + 1, a0 + 3, a0 + 2))
    return mesh_obj(name, verts, faces, coll, mat_grass, uvs, ("blade_rand", attr))


def pebble(name, seed, coll):
    rng = random.Random(seed)
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
    waves = [(Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized() * rng.uniform(1.2, 3.5), rng.uniform(0, 6.28), rng.uniform(0.04, 0.12)) for _ in range(6)]
    ax, flat = rng.uniform(0.65, 1.0), rng.uniform(0.42, 0.68)
    for v in bm.verts:
        r = 1 + sum(a * math.sin(k.dot(v.co) + ph) for k, ph, a in waves)
        v.co = Vector((v.co.x * r, v.co.y * r * ax, v.co.z * r * flat - 0.12))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for f in me.polygons: f.use_smooth = True
    me.materials.append(mat_peb)
    o = bpy.data.objects.new(name, me); coll.objects.link(o)
    return o


def twig(name, seed, coll):
    rng = random.Random(seed)
    bm = bmesh.new()
    def branch(p0, direction, length, r0, r1, segs):
        pts = [p0]
        d = direction.normalized()
        for s in range(segs):
            d = (d + Vector((rng.gauss(0, 0.25), rng.gauss(0, 0.25), 0))).normalized()
            pts.append(pts[-1] + d * (length / segs))
        rings = []
        for i, p in enumerate(pts):
            r = r0 + (r1 - r0) * i / segs
            tdir = (pts[min(i + 1, segs)] - pts[max(i - 1, 0)]).normalized()
            side = tdir.cross(Vector((0, 0, 1))).normalized()
            up = side.cross(tdir).normalized()
            rings.append([bm.verts.new(p + (side * math.cos(a) + up * math.sin(a)) * r) for a in [2 * math.pi * k / 5 for k in range(5)]])
        for a_, b_ in zip(rings[:-1], rings[1:]):
            for k in range(5):
                bm.faces.new((a_[k], a_[(k + 1) % 5], b_[(k + 1) % 5], b_[k]))
        return pts
    L = rng.uniform(0.18, 0.34)
    pts = branch(Vector((-L / 2, 0, 0.004)), Vector((1, 0, 0)), L, 0.0045, 0.0015, 5)
    if rng.random() > 0.3:
        branch(pts[2], Vector((rng.uniform(0.3, 0.8), rng.choice((-1, 1)) * 0.7, 0)), L * 0.4, 0.0022, 0.001, 3)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for f in me.polygons: f.use_smooth = True
    me.materials.append(mat_twig)
    o = bpy.data.objects.new(name, me); coll.objects.link(o)
    return o


c_leaf, c_peb, c_twig = asset_coll("GA_leaves"), asset_coll("GA_pebbles"), asset_coll("GA_twigs")
c_grass, c_grass_far = asset_coll("GA_grass_near"), asset_coll("GA_grass_far")
for i, kind in enumerate(["ovate", "ovate", "oak", "oak", "lance", "birch"]):
    leaf("leaf_%s_%d" % (kind, i), kind, 100 + i, c_leaf)
for i in range(5):
    pebble("pebble_%d" % i, 200 + i, c_peb)
for i in range(3):
    twig("twig_%d" % i, 300 + i, c_twig)
tuft("tuft_near_0", 46, 0.12, 0.32, 0.0025, 0.004, 400, c_grass)
tuft("tuft_near_1", 60, 0.18, 0.42, 0.0025, 0.0042, 401, c_grass)
tuft("tuft_near_2", 34, 0.08, 0.22, 0.002, 0.0035, 402, c_grass)
tuft("tuft_far_0", 12, 0.15, 0.35, 0.006, 0.009, 410, c_grass_far, segs=2)
bpy.context.view_layer.layer_collection.children["GroundAssets"].exclude = True
log["added"].append("GroundAssets collection (excluded from view layer): 6 leaf, 5 pebble, 3 twig, 3 near + 1 far grass tuft meshes")

# ---------------------------------------------------------------- geometry nodes
ng = bpy.data.node_groups.new("GN_TerrainGround", "GeometryNodeTree")
itf = ng.interface
itf.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
itf.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
CONTROLS = [
    ("Angular Resolution", "NodeSocketInt", 640, 16, 4000, "Terrain vertices across the camera wedge"),
    ("Radial Resolution", "NodeSocketInt", 480, 16, 4000, "Terrain vertex rows from near to far (spaced for perspective)"),
    ("Near Distance", "NodeSocketFloat", 5.0, 0.5, 50.0, "Closest terrain distance from the camera (m)"),
    ("Far Distance", "NodeSocketFloat", 180.0, 10.0, 1000.0, "Farthest terrain distance from the camera (m)"),
    ("Half Angle", "NodeSocketFloat", 44.0, 5.0, 89.0, "Half width of the terrain wedge around the view direction (degrees)"),
    ("Water Level", "NodeSocketFloat", W, -1.0, 1.0, "Puddle surface height; nothing is scattered below it"),
    ("Seed", "NodeSocketInt", 7, 0, 100000, "Stable random seed for all scattering"),
    ("Leaf Density", "NodeSocketFloat", 1.0, 0.0, 10.0, "Fallen-leaf density multiplier"),
    ("Pebble Density", "NodeSocketFloat", 1.0, 0.0, 10.0, "Embedded-pebble density multiplier"),
    ("Twig Density", "NodeSocketFloat", 1.0, 0.0, 10.0, "Fallen-twig density multiplier"),
    ("Grass Density", "NodeSocketFloat", 1.0, 0.0, 10.0, "Dry-grass tuft density multiplier"),
    ("Litter Range", "NodeSocketFloat", 32.0, 2.0, 200.0, "Leaves, pebbles and twigs fade out by this distance (m)"),
    ("Grass Detail Range", "NodeSocketFloat", 24.0, 2.0, 200.0, "Detailed grass tufts switch to low-poly tufts here (m)"),
]
for name, typ, dv, mn, mx, desc in CONTROLS:
    s = itf.new_socket(name, in_out="INPUT", socket_type=typ)
    s.default_value = dv; s.min_value = mn; s.max_value = mx; s.description = desc


class GG(SG):
    def rand(self, mn, mx, seed_off, kind="FLOAT"):
        nd = self.node("FunctionNodeRandomValue", data_type=kind)
        ins = [s for s in nd.inputs if s.enabled]
        self.put(ins[0], mn); self.put(ins[1], mx)
        self.put(nd.inputs["Seed"], self.math("ADD", gi.outputs["Seed"], seed_off))
        return [s for s in nd.outputs if s.enabled][0]
    def vmath(self, op, a, b=None):
        nd = self.node("ShaderNodeVectorMath", operation=op)
        self.put(nd.inputs[0], a)
        if b is not None: self.put(nd.inputs[1], b)
        return nd.outputs[1] if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else nd.outputs[0]
    def mul(self, *vals):
        acc = vals[0]
        for v in vals[1:]: acc = self.math("MULTIPLY", acc, v)
        return acc
    def add(self, *vals):
        acc = vals[0]
        for v in vals[1:]: acc = self.math("ADD", acc, v)
        return acc


g = GG(ng)
gi = g.node("NodeGroupInput"); go = g.node("NodeGroupOutput")
I = gi.outputs

# camera wedge grid: columns in angle, rows uniform in 1/distance (matches ground foreshortening)
grid = g.node("GeometryNodeMeshGrid")
grid.inputs["Size X"].default_value = 1.0; grid.inputs["Size Y"].default_value = 1.0
g.put(grid.inputs["Vertices X"], I["Angular Resolution"]); g.put(grid.inputs["Vertices Y"], I["Radial Resolution"])
gx, gy, _ = g.sep(g.node("GeometryNodeInputPosition").outputs[0])
u = g.math("ADD", gx, 0.5); v = g.math("ADD", gy, 0.5)
ci = g.node("GeometryNodeObjectInfo", transform_space="RELATIVE"); ci.inputs["Object"].default_value = cam
fwd = g.node("FunctionNodeRotateVector"); fwd.inputs["Vector"].default_value = (0, 0, -1)
g.l.new(ci.outputs["Rotation"], fwd.inputs["Rotation"])
fx, fy, _ = g.sep(fwd.outputs[0])
theta = g.add(g.math("ARCTAN2", fy, fx), g.mul(g.math("SUBTRACT", 0.5, u), g.math("RADIANS", I["Half Angle"]), 2.0))
inv_n = g.math("DIVIDE", 1.0, I["Near Distance"]); inv_f = g.math("DIVIDE", 1.0, I["Far Distance"])
r = g.math("DIVIDE", 1.0, g.add(inv_n, g.mul(v, g.math("SUBTRACT", inv_f, inv_n))))
cx, cy, _ = g.sep(ci.outputs["Location"])
X = g.add(cx, g.mul(r, g.math("COSINE", theta)))
Y = g.add(cy, g.mul(r, g.math("SINE", theta)))


def map_uv(x, y):
    return g.comb(g.math("DIVIDE", g.math("SUBTRACT", x, gm.X0), gm.S), g.math("DIVIDE", g.math("SUBTRACT", y, gm.Y0), gm.S))


hti = g.node("GeometryNodeImageTexture", interpolation="Cubic", extension="EXTEND")
hti.inputs["Image"].default_value = img_h
g.l.new(map_uv(X, Y), hti.inputs["Vector"])
hsep = g.node("FunctionNodeSeparateColor"); g.l.new(hti.outputs["Color"], hsep.inputs[0])
Z = g.add(gm.H_MIN, g.mul(hsep.outputs[0], gm.H_MAX - gm.H_MIN))
setpos = g.node("GeometryNodeSetPosition")
g.l.new(grid.outputs["Mesh"], setpos.inputs["Geometry"]); g.l.new(g.comb(X, Y, Z), setpos.inputs["Position"])
smooth = g.node("GeometryNodeSetShadeSmooth"); g.l.new(setpos.outputs[0], smooth.inputs[0])
setmat = g.node("GeometryNodeSetMaterial"); setmat.inputs["Material"].default_value = mat_terrain
g.l.new(smooth.outputs[0], setmat.inputs["Geometry"])
terrain = setmat.outputs[0]

# scatter fields, evaluated on the displaced terrain
px2, py2, pz2 = g.sep(g.node("GeometryNodeInputPosition").outputs[0])
mti = g.node("GeometryNodeImageTexture", interpolation="Linear", extension="EXTEND")
mti.inputs["Image"].default_value = img_m
g.l.new(map_uv(px2, py2), mti.inputs["Vector"])
msep = g.node("FunctionNodeSeparateColor"); g.l.new(mti.outputs["Color"], msep.inputs[0])
f_road, f_shelter, f_track = msep.outputs[0], msep.outputs[1], msep.outputs[2]
f_obst = mti.outputs["Alpha"]
dist = g.vmath("LENGTH", g.comb(g.math("SUBTRACT", px2, cx), g.math("SUBTRACT", py2, cy)))
dry = g.math("GREATER_THAN", pz2, g.math("ADD", I["Water Level"], 0.006))
free = g.mul(g.math("SUBTRACT", 1.0, f_obst), dry)
clump = g.maprange(g.noise(g.node("GeometryNodeInputPosition").outputs[0], 0.55, 3.0), 0.42, 0.62, 0.0, 1.0)
shoulder = g.mul(4.0, f_road, g.math("SUBTRACT", 1.0, f_road))
not_track = g.math("SUBTRACT", 1.0, f_track)


def fade(rng_sock, frac=0.6):
    nd = g.node("ShaderNodeMapRange", clamp=True)
    g.put(nd.inputs["Value"], dist)
    g.put(nd.inputs["From Min"], g.math("MULTIPLY", rng_sock, frac)); g.put(nd.inputs["From Max"], rng_sock)
    nd.inputs["To Min"].default_value = 1.0; nd.inputs["To Max"].default_value = 0.0
    return nd.outputs["Result"]


leaf_d = g.mul(I["Leaf Density"], fade(I["Litter Range"]), free, g.math("SUBTRACT", 1.0, g.mul(f_track, 0.95)),
               g.add(g.mul(220.0, g.math("POWER", f_shelter, 1.6), g.add(0.35, g.mul(0.65, clump))),
                     g.mul(14.0, g.math("SUBTRACT", 1.0, f_road), g.add(0.3, clump)),
                     g.mul(25.0, shoulder, g.add(0.3, clump)), g.mul(1.2, f_road)))
peb_d = g.mul(I["Pebble Density"], fade(g.math("MULTIPLY", I["Litter Range"], 1.2)), free, g.math("SUBTRACT", 1.0, g.mul(f_track, 0.92)),
              g.add(f_road, g.mul(6.0, shoulder), g.mul(1.2, g.math("SUBTRACT", 1.0, f_road))))
twig_d = g.mul(I["Twig Density"], fade(g.math("MULTIPLY", I["Litter Range"], 0.8)), free, not_track,
               g.add(0.12, g.mul(2.2, f_shelter)), g.math("SUBTRACT", 1.0, g.mul(0.7, f_road)))
grass_base = g.add(g.mul(g.math("SUBTRACT", 1.0, f_road), g.add(2.5, g.mul(14.0, clump, clump))),
                   g.mul(6.0, f_shelter, g.math("SUBTRACT", 1.0, f_road)),
                   g.mul(3.0, shoulder, not_track))
near_w = fade(I["Grass Detail Range"], 0.8)
grass_near_d = g.mul(I["Grass Density"], free, not_track, grass_base, near_w)
grass_far_d = g.mul(I["Grass Density"], 0.45, free, not_track, grass_base, g.math("SUBTRACT", 1.0, near_w), fade(g.math("MULTIPLY", I["Grass Detail Range"], 2.8), 0.75))

wet_inst = g.maprange(pz2, W + 0.03, W + 0.005, 0.0, 1.0)


def scatter(density, coll, n_items, seed_off, smin, smax, align, tilt, z_flat=None, sink=0.0, attrs=()):
    dp = g.node("GeometryNodeDistributePointsOnFaces", distribute_method="RANDOM")
    g.l.new(terrain, dp.inputs["Mesh"]); g.put(dp.inputs["Density"], density)
    g.put(dp.inputs["Seed"], g.math("ADD", I["Seed"], seed_off))
    pts = dp.outputs["Points"]
    for name, field in attrs:
        st = g.node("GeometryNodeStoreNamedAttribute", data_type="FLOAT", domain="POINT")
        st.inputs["Name"].default_value = name
        g.l.new(pts, st.inputs["Geometry"]); g.put(st.inputs["Value"], field)
        pts = st.outputs[0]
    al = g.node("FunctionNodeAlignRotationToVector", axis="Z")
    al.inputs["Factor"].default_value = align
    g.l.new(dp.outputs["Normal"], al.inputs["Vector"])
    spin = g.node("FunctionNodeEulerToRotation")
    g.l.new(g.comb(g.rand(-tilt, tilt, seed_off + 1), g.rand(-tilt, tilt, seed_off + 2), g.rand(0.0, 6.2832, seed_off + 3)), spin.inputs[0])
    rot = g.node("FunctionNodeRotateRotation", rotation_space="LOCAL")
    g.l.new(al.outputs[0], rot.inputs["Rotation"]); g.l.new(spin.outputs[0], rot.inputs["Rotate By"])
    s = g.rand(smin, smax, seed_off + 4)
    zs = s if z_flat is None else g.mul(s, z_flat)
    ci_ = g.node("GeometryNodeCollectionInfo"); ci_.inputs["Collection"].default_value = coll
    ci_.inputs["Separate Children"].default_value = True; ci_.inputs["Reset Children"].default_value = True
    iop = g.node("GeometryNodeInstanceOnPoints")
    g.l.new(pts, iop.inputs["Points"]); g.l.new(ci_.outputs[0], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    g.put(iop.inputs["Instance Index"], g.rand(0, n_items - 1, seed_off + 5, "INT"))
    g.l.new(rot.outputs[0], iop.inputs["Rotation"]); g.l.new(g.comb(s, s, zs), iop.inputs["Scale"])
    res = iop.outputs[0]
    if sink:
        tr = g.node("GeometryNodeTranslateInstances")
        tr.inputs["Local Space"].default_value = True
        g.l.new(res, tr.inputs["Instances"])
        g.put(tr.inputs["Translation"], g.comb(0.0, 0.0, g.mul(s, g.rand(0.0, sink, seed_off + 6), -1.0)))
        res = tr.outputs[0]
    return res


leaf_rand = g.rand(0.0, 1.0, 50)
leaf_damp = g.math("MINIMUM", 1.0, g.add(wet_inst, g.mul(g.rand(0.0, 1.0, 51), 0.55), g.mul(f_shelter, 0.25)))
leaves = scatter(leaf_d, c_leaf, 6, 10, 0.07, 0.12, 1.0, 0.18, z_flat=g.maprange(leaf_damp, 0.0, 1.0, 1.0, 0.3),
                 attrs=(("leaf_rand", leaf_rand), ("leaf_damp", leaf_damp)))
pebbles = scatter(peb_d, c_peb, 5, 20, 0.012, 0.045, 1.0, 0.25, sink=0.35, attrs=(("peb_rand", g.rand(0.0, 1.0, 52)),))
twigs = scatter(twig_d, c_twig, 3, 30, 0.8, 1.4, 1.0, 0.05)
grass_n = scatter(grass_near_d, c_grass, 3, 40, 0.7, 1.3, 0.3, 0.12, attrs=(("tuft_rand", g.rand(0.0, 1.0, 53)),))
grass_f = scatter(grass_far_d, c_grass_far, 1, 60, 0.8, 1.5, 0.3, 0.1, attrs=(("tuft_rand", g.rand(0.0, 1.0, 54)),))

join = g.node("GeometryNodeJoinGeometry")
for geo in (terrain, leaves, pebbles, twigs, grass_n, grass_f):
    g.l.new(geo, join.inputs[0])
g.l.new(join.outputs[0], go.inputs[0])

# ---------------------------------------------------------------- foreground fieldstones
# The v2 rocks were faceted, uniformly lit icospheres. Keep their placement; give them lumpy
# silhouettes, smooth shading, soil grime where they meet the ground, and bury them a little deeper.
mat_rock, nt, out = new_mat("fieldstone")
g = SG(nt)
ob = g.node("ShaderNodeTexCoord").outputs["Object"]
zr = g.sep(g.node("ShaderNodeNewGeometry").outputs["Position"])[2]
n1 = g.noise(ob, 2.5, 8.0, 0.6); n2 = g.noise(ob, 9.0, 6.0, 0.55)
rcol = g.ramp(n1, [(0.3, (0.04, 0.038, 0.035)), (0.55, (0.08, 0.075, 0.066)), (0.78, (0.11, 0.1, 0.087))])
rcol = g.mix(g.maprange(zr, 0.0, 0.16, 0.85, 0.0), rcol, (0.026, 0.02, 0.014, 1))
rb = g.node("ShaderNodeBump"); rb.inputs["Strength"].default_value = 0.6; rb.inputs["Distance"].default_value = 0.03
g.put(rb.inputs["Height"], g.math("ADD", g.math("MULTIPLY", n2, 0.6), g.math("MULTIPLY", n1, 0.4)))
principled(g, out, rcol, g.math("SUBTRACT", 0.85, g.math("MULTIPLY", n2, 0.15)), rb.outputs["Normal"])
lumps = bpy.data.textures.new("rock_lumps", "CLOUDS"); lumps.noise_scale = 0.35; lumps.noise_depth = 3
rocks = [o for o in scene.objects if o.name.startswith("Icosphere") and o.data.materials and o.data.materials[0] and o.data.materials[0].name == "stone"]
for o in rocks:
    sub = o.modifiers.new("Subdiv", "SUBSURF"); sub.levels = 1; sub.render_levels = 2
    dsp = o.modifiers.new("Lumps", "DISPLACE"); dsp.texture = lumps; dsp.texture_coords = "GLOBAL"; dsp.strength = 0.22
    o.data.materials[0] = mat_rock
    for p in o.data.polygons: p.use_smooth = True
    o.location.z -= o.scale.z * 0.15
log["changed"].append("%d foreground rocks: smooth shading, subdivision + lumpy displacement (global-coordinate clouds, so no two match), "
                      "fieldstone material with soil grime at the base, sunk %.0f%% of their height deeper; positions kept" % (len(rocks), 15))

# ---------------------------------------------------------------- scene objects
ground_coll = bpy.data.collections.new("Ground")
scene.collection.children.link(ground_coll)
terr = bpy.data.objects.new("terrain_gn", bpy.data.meshes.new("terrain_gn"))
ground_coll.objects.link(terr)
mod = terr.modifiers.new("GN_TerrainGround", "NODES")
mod.node_group = ng
log["added"].append("terrain_gn object with GN_TerrainGround modifier (camera-wedge terrain + instanced litter/grass)")

# water surface over the road band; it only shows where the terrain dips below it
ys = np.linspace(-8, 36, 45)
xs = gm.road_x(ys)
wv = [(x - 2.4, y, W) for x, y in zip(xs, ys)] + [(x + 2.4, y, W) for x, y in zip(xs, ys)]
n_ = len(ys)
wf = [(i, i + n_, i + n_ + 1, i + 1) for i in range(n_ - 1)]
wme = bpy.data.meshes.new("puddle_water"); wme.from_pydata(wv, [], wf); wme.materials.append(mat_water)
for f in wme.polygons: f.use_smooth = True
wobj = bpy.data.objects.new("puddle_water", wme); ground_coll.objects.link(wobj)
log["added"].append("puddle_water: one flat water surface at z=%.3f over the road band" % W)

# retire the flat road strip and disc puddles; keep the old plane as a low backdrop
for o in list(bpy.data.objects):
    base = o.name.split(".")[0]
    if base in ("road", "puddle"):
        log["removed"].append(o.name)
        bpy.data.objects.remove(o, do_unlink=True)
for o in list(scene.objects):
    if o.type == "MESH" and o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "ground":
        for m_ in list(o.modifiers):
            o.modifiers.remove(m_)
        o.location.z = -0.3
        o.name = "ground_backdrop"
        for c in list(o.users_collection): c.objects.unlink(o)
        ground_coll.objects.link(o)
        log["changed"].append("ground plane -> ground_backdrop: subdivision+displace removed, lowered to z=-0.3 under the GN terrain")
for m_ in ("road",):
    if m_ in bpy.data.materials and bpy.data.materials[m_].users == 0:
        bpy.data.materials.remove(bpy.data.materials[m_])
for t in ("gt", "rt"):
    if t in bpy.data.textures and bpy.data.textures[t].users == 0:
        bpy.data.textures.remove(bpy.data.textures[t])

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True)

report = {
    "footprints": {k: len(v) for k, v in footprints.items()},
    "traveled_way_overlap_px": diag["traveled_overlap_px"],
    "traveled_way_overlap_by_class": diag["traveled_overlap_by_class"],
    "water_area_m2": round(diag["water_area_m2"], 2),
    "water_outside_road_m2": round(diag["water_outside_road_m2"], 3),
    "height_range_m": [round(x, 3) for x in diag["h_range"]],
    "objects_floating_over_5mm_before_fix": floating_before,
    "objects_floating_over_5mm_after_fix": floating,
    "log": log,
}
with open(os.path.join(TEX_DIR, "ground_report.json"), "w") as fh:
    json.dump(report, fh, indent=1)
np.save(os.path.join(TEX_DIR, "_height.npy"), height)
np.save(os.path.join(TEX_DIR, "_fp.npy"), diag["fp_all"].astype(np.uint8))
print(json.dumps({k: v for k, v in report.items() if k != "log"}, indent=1))
print("saved", OUT_BLEND)
