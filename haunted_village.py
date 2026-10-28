"""Haunted village at night, built procedurally in Blender (bpy). Usage: python3 haunted_village.py [out.png] [width] [samples]"""
import bpy, bmesh, math, random, sys
from mathutils import Vector

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/render.png"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 960
SAMPLES = int(sys.argv[3]) if len(sys.argv) > 3 else 48
random.seed(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
col = bpy.data.collections.new("village"); scene.collection.children.link(col)


def link(o):
    col.objects.link(o); return o


def mat(name, color, rough=0.8, emission=None, strength=0, noise=None, bump=0.0, metallic=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    n = m.node_tree.nodes; l = m.node_tree.links
    b = n["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    if noise:
        tc = n.new("ShaderNodeTexCoord"); mp = n.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = noise.get("scale_vec", (1, 1, 1))
        nt = n.new("ShaderNodeTexNoise"); nt.inputs["Scale"].default_value = noise.get("scale", 6)
        nt.inputs["Detail"].default_value = 10
        l.new(tc.outputs["Object"], mp.inputs["Vector"]); l.new(mp.outputs["Vector"], nt.inputs["Vector"])
        ramp = n.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = color
        ramp.color_ramp.elements[1].color = noise["other"]
        l.new(nt.outputs["Fac"], ramp.inputs["Fac"])
        l.new(ramp.outputs["Color"], b.inputs["Base Color"])
        if bump:
            bp = n.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = bump
            l.new(nt.outputs["Fac"], bp.inputs["Height"]); l.new(bp.outputs["Normal"], b.inputs["Normal"])
    else:
        b.inputs["Base Color"].default_value = color
    if emission:
        b.inputs["Emission Color"].default_value = emission
        b.inputs["Emission Strength"].default_value = strength
    return m


def box(name, loc, size, m, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object; o.name = name; o.scale = (size[0] / 2, size[1] / 2, size[2] / 2)
    o.data.materials.append(m); col.objects.link(o); bpy.context.scene.collection.objects.unlink(o)
    return o


def prism_roof(name, cx, cy, z0, w, d, h, over, m, rot_z=0):
    """Gable roof, ridge along x."""
    me = bpy.data.meshes.new(name)
    x0, x1 = -w / 2 - over, w / 2 + over; y0, y1 = -d / 2 - over, d / 2 + over
    v = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0), (x0, 0, h), (x1, 0, h)]
    f = [(0, 1, 5, 4), (2, 3, 4, 5), (0, 4, 3), (1, 2, 5), (0, 3, 2, 1)]
    me.from_pydata(v, [], f); me.update()
    o = bpy.data.objects.new(name, me); o.location = (cx, cy, z0); o.rotation_euler[2] = rot_z
    o.data.materials.append(m); link(o)
    return o


# ---------- materials ----------
wood_dark = mat("wood", (0.035, 0.028, 0.025, 1), 0.85, noise={"other": (0.09, 0.07, 0.055, 1), "scale": 4, "scale_vec": (0.3, 0.3, 6)}, bump=0.6)
wood_warm = mat("wood_lit", (0.03, 0.026, 0.022, 1), 0.85, noise={"other": (0.085, 0.07, 0.055, 1), "scale": 4, "scale_vec": (0.3, 0.3, 6)}, bump=0.6)
roof_m = mat("roof", (0.03, 0.03, 0.036, 1), 0.7, noise={"other": (0.09, 0.09, 0.1, 1), "scale": 25}, bump=0.8)
brick = mat("brick", (0.03, 0.02, 0.018, 1), 0.9, noise={"other": (0.09, 0.05, 0.04, 1), "scale": 14}, bump=0.8)
stone = mat("stone", (0.04, 0.04, 0.045, 1), 0.95, noise={"other": (0.12, 0.115, 0.11, 1), "scale": 7}, bump=1.0)
ground_m = mat("ground", (0.02, 0.018, 0.016, 1), 0.55, noise={"other": (0.07, 0.06, 0.05, 1), "scale": 3, "scale_vec": (1, 1, 1)}, bump=1.2)
puddle_m = mat("puddle", (0.01, 0.012, 0.018, 1), 0.015)
road_m = mat("road", (0.01, 0.009, 0.008, 1), 0.62, noise={"other": (0.05, 0.045, 0.04, 1), "scale": 9}, bump=0.9)
stave_m = mat("stave", (0.035, 0.024, 0.016, 1), 0.75, noise={"other": (0.11, 0.075, 0.045, 1), "scale": 3, "scale_vec": (8, 8, 0.25)}, bump=0.5)
shrub_m = mat("shrub", (0.02, 0.013, 0.007, 1), 0.95, noise={"other": (0.1, 0.06, 0.025, 1), "scale": 30}, bump=1.5)
weed_m = mat("weed", (0.14, 0.08, 0.03, 1), 0.7, noise={"other": (0.5, 0.3, 0.1, 1), "scale": 20})
bark = mat("bark", (0.012, 0.01, 0.01, 1), 0.9)
glow = mat("window", (1, 0.55, 0.2, 1), 0.3, emission=(1.0, 0.5, 0.15, 1), strength=18)
glow2 = mat("window2", (1, 0.55, 0.2, 1), 0.3, emission=(1.0, 0.45, 0.12, 1), strength=7)
dark_win = mat("darkwin", (0.005, 0.007, 0.012, 1), 0.1)
trim = mat("trim", (0.12, 0.1, 0.085, 1), 0.8)
moon_m = mat("moon", (1, 1, 1, 1), 0.9, emission=(0.85, 0.9, 1.0, 1), strength=7, noise={"other": (0.6, 0.65, 0.75, 1), "scale": 5})
iron = mat("iron", (0.02, 0.02, 0.02, 1), 0.5, metallic=0.8)

# ---------- ground ----------
bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 40, 0))
g = bpy.context.object; g.data.materials.append(ground_m); col.objects.link(g); scene.collection.objects.unlink(g)
bpy.ops.object.shade_smooth()
sub = g.modifiers.new("s", "SUBSURF"); sub.subdivision_type = "SIMPLE"; sub.levels = 6; sub.render_levels = 6
disp = g.modifiers.new("d", "DISPLACE"); tex = bpy.data.textures.new("gt", "CLOUDS"); tex.noise_scale = 0.8
disp.texture = tex; disp.strength = 0.08

# wet road: runs from the foreground-left back into the village street
rme = bpy.data.meshes.new("road"); rbm = bmesh.new()
pts = [(-5.0, -14), (-4.8, -4), (-5.2, 4), (-6.2, 12), (-6.8, 20), (-6.0, 30), (-5.0, 45)]
rows = []
for (x, y) in pts:
    rows.append([rbm.verts.new((x + o, y, 0.05)) for o in (-3.0, -1.5, 0.0, 1.5, 3.0)])
for a_, b_ in zip(rows[:-1], rows[1:]):
    for k in range(4):
        rbm.faces.new((a_[k], a_[k + 1], b_[k + 1], b_[k]))
rbm.to_mesh(rme); rbm.free()
road = bpy.data.objects.new("road", rme); road.data.materials.append(road_m); link(road)
rs = road.modifiers.new("s", "SUBSURF"); rs.levels = 4; rs.render_levels = 4
rd_ = road.modifiers.new("d", "DISPLACE"); rt = bpy.data.textures.new("rt", "CLOUDS"); rt.noise_scale = 0.5
rd_.texture = rt; rd_.strength = 0.06
for f in rme.polygons: f.use_smooth = True

# puddles (left road & foreground)
random.seed(5)
for (x, y, sx, sy) in [(-4.6, -0.6, 2.6, 0.9), (-6.0, 2.8, 1.6, 0.5), (-4.4, 5.0, 1.0, 0.35), (-5.6, 8.0, 1.3, 0.4), (-7.0, 13, 1.5, 0.45), (-6.4, 18, 1.0, 0.3)]:
    pbm = bmesh.new(); n_ = 40; ph = [random.uniform(0, 6.28) for _ in range(3)]
    vs_ = []
    for k in range(n_):
        a_ = 2 * math.pi * k / n_
        rr = 1 + 0.18 * math.sin(3 * a_ + ph[0]) + 0.1 * math.sin(5 * a_ + ph[1]) + 0.06 * math.sin(9 * a_ + ph[2])
        vs_.append(pbm.verts.new((x + sx * rr * math.cos(a_), y + sy * rr * math.sin(a_), 0.085)))
    pbm.faces.new(vs_); pme = bpy.data.meshes.new("puddle"); pbm.to_mesh(pme); pbm.free()
    p = bpy.data.objects.new("puddle", pme); p.data.materials.append(puddle_m); link(p)

# ---------- main house ----------
HR = math.radians(-48)  # rotation about z
hx, hy = 8.0, 10.0


def house_local(lx, ly, lz):
    c, s = math.cos(HR), math.sin(HR)
    return (hx + lx * c - ly * s, hy + lx * s + ly * c, lz)


W_, D_, H_ = 9.0, 5.5, 5.6
box("main", house_local(0, 0, H_ / 2), (W_, D_, H_), wood_dark, (0, 0, HR))
# clapboards (thin horizontal strips on front)
for i in range(int(H_ / 0.22)):
    box("cb", house_local(0, -D_ / 2 - 0.02, 0.15 + i * 0.22), (W_ + 0.05, 0.06, 0.07), wood_warm, (0, 0, HR))
roof = prism_roof("roof", *house_local(0, 0, H_)[:2], H_, W_, D_, 3.4, 0.5, roof_m, HR)
# chimney (right end)
box("chimney", house_local(W_ / 2 - 0.9, 0.3, H_ + 2.2), (1.3, 1.2, 5.5), brick, (0, 0, HR))
box("chimcap", house_local(W_ / 2 - 0.9, 0.3, H_ + 5.0), (1.6, 1.5, 0.25), stone, (0, 0, HR))
# front windows: (lx, lz, glow?)
for (lx, lz, lit, ww, wh) in [(-3.4, 1.6, 0, 0.8, 1.5), (-2.2, 1.6, 0, 0.8, 1.5), (-3.2, 4.2, 0, 0.8, 1.5), (-1.5, 4.2, 0, 0.8, 1.5),
                              (1.8, 1.7, 0, 2.6, 1.5), (1.6, 4.2, 1, 0.9, 1.6), (-0.1, 4.2, 0, 0.8, 1.5), (3.4, 4.2, 0, 0.8, 1.5)]:
    p = house_local(lx, -D_ / 2 - 0.05, lz)
    box("w", p, (ww, 0.08, wh), glow if lit else dark_win, (0, 0, HR))
    # frame + mullions
    for fx in (-ww / 2, ww / 2):
        box("f", house_local(lx + fx, -D_ / 2 - 0.09, lz), (0.08, 0.06, wh + 0.1), trim, (0, 0, HR))
    for fz in (-wh / 2, wh / 2):
        box("f", house_local(lx, -D_ / 2 - 0.09, lz + fz), (ww + 0.1, 0.06, 0.08), trim, (0, 0, HR))
    box("m", house_local(lx, -D_ / 2 - 0.1, lz), (0.05, 0.05, wh), trim, (0, 0, HR))
    for k in (-1, 0, 1):
        box("m", house_local(lx, -D_ / 2 - 0.1, lz + k * wh / 3.2), (ww, 0.05, 0.04), trim, (0, 0, HR))
# door + portico
box("door", house_local(-0.2, -D_ / 2 - 0.05, 1.1), (1.1, 0.1, 2.2), dark_win, (0, 0, HR))
box("portico", house_local(-0.2, -D_ / 2 - 0.5, 2.5), (2.0, 1.0, 0.15), trim, (0, 0, HR))
# lit window warm light
lw = bpy.data.lights.new("winlight", "POINT"); lw.energy = 900; lw.color = (1, 0.55, 0.2); lw.shadow_soft_size = 0.4
lo = bpy.data.objects.new("winlight", lw); lo.location = house_local(1.6, -D_ / 2 - 1.0, 4.2); link(lo)
lw2 = bpy.data.lights.new("winlight2", "POINT"); lw2.energy = 1500; lw2.color = (1, 0.55, 0.25)
lo2 = bpy.data.objects.new("winlight2", lw2); lo2.location = house_local(1.0, -D_ / 2 - 3, 1.5); link(lo2)

# ---------- right-hand house ----------
rx, ry = 20.0, 17.0
box("house2", (rx, ry, 2.2), (7, 5, 4.4), wood_dark, (0, 0, math.radians(-8)))
prism_roof("roof2", rx, ry, 4.4, 7, 5, 2.8, 0.45, roof_m, math.radians(-8))
box("chim2", (rx + 2.0, ry, 6.6), (1, 1, 3), brick)
for dx in (-2, 0, 2):
    box("w2", (rx + dx, ry - 2.55, 2.6), (0.7, 0.06, 1.3), dark_win)
box("w2lit", (rx + 2, ry - 2.55, 1.0), (0.7, 0.06, 1.0), glow2)

# ---------- village (left) ----------
village = [(-13, 13, 5, 6, 5, 1.45), (-14, 21, 5, 7, 6, 1.5), (-13, 30, 5, 6, 5.5, 1.6), (-15, 40, 6, 7, 6.5, 1.5), (-1, 30, 7, 5, 5.5, 0.15), (2, 42, 8, 6, 7, 0)]
for i, (x, y, w, d, h, r) in enumerate(village):
    box("vh", (x, y, h / 2), (w, d, h), wood_dark, (0, 0, r))
    prism_roof("vr", x, y, h, w, d, 2.8, 0.4, roof_m, r)
    rot = lambda lx, ly: (x + lx * math.cos(r) - ly * math.sin(r), y + lx * math.sin(r) + ly * math.cos(r))
    box("vc", (*rot(w * 0.25, 0), h + 2.2), (0.9, 0.9, 2.8), brick, (0, 0, r))
    for k in range(3):
        for lz in (h * 0.3, h * 0.7):
            box("vw", (*rot((k - 1) * w * 0.3, -d / 2 - 0.05), lz), (0.6, 0.06, 1.0), glow2 if (i, k, lz) in ((1, 1, h * 0.3), (4, 0, h * 0.7), (2, 2, h * 0.3)) else dark_win, (0, 0, r))
# lit first village house glow
lv = bpy.data.lights.new("vlight", "POINT"); lv.energy = 500; lv.color = (1, 0.5, 0.2)
lvo = bpy.data.objects.new("vlight", lv); lvo.location = (-11.5, 6.5, 2.5); link(lvo)
# left foreground house edge, lit
box("lh", (-15, 4, 3), (6, 7, 6), wood_warm, (0, 0, 0.1))
prism_roof("lhr", -15, 4, 6, 6, 7, 2.6, 0.4, roof_m, 0.1)
box("lhw", (-11.95, 3.0, 3.0), (0.06, 1.0, 1.4), glow2, (0, 0, 0.1))
box("lhw2", (-11.95, 5.5, 1.4), (0.06, 1.0, 1.3), glow2, (0, 0, 0.1))

# ---------- fences ----------
def fence(p0, p1, nposts, h=1.1, jitter=0.12):
    ps = []
    for i in range(nposts):
        t = i / (nposts - 1)
        x = p0[0] + (p1[0] - p0[0]) * t; y = p0[1] + (p1[1] - p0[1]) * t
        hh = h * random.uniform(0.75, 1.15)
        o = box("post", (x, y, hh / 2), (0.14, 0.14, hh), wood_warm, (random.uniform(-jitter, jitter), random.uniform(-jitter, jitter), 0))
        ps.append((x, y))
    for z in (0.45, 0.85):
        for a, b in zip(ps[:-1], ps[1:]):
            if random.random() < 0.15: continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            L = math.hypot(b[0] - a[0], b[1] - a[1]); ang = math.atan2(b[1] - a[1], b[0] - a[0])
            box("rail", (mx, my, z + random.uniform(-0.05, 0.05)), (L, 0.06, 0.12), wood_warm, (0, random.uniform(-0.05, 0.05), ang))

# front fence leading toward foreground-right
fence((-1.2, 1.2), (1.5, 1.0), 3, 1.5, 0.05)
fence((1.5, 2.2), (7, 1.4), 4, 1.2)
fence((-9.5, -6), (-10.5, 12), 9, 1.0)   # village side of the road
# wall + fence heading to village bend (left)
fence((-1.6, 1.8), (-3.8, 12.0), 7, 1.2)
# low stone wall
random.seed(3)
for i in range(70):
    t = i / 69
    x = -1.0 - t * 2.6; y = 0.5 + t * 11.5
    for j in range(2):
        s = random.uniform(0.35, 0.6)
        box("st", (x + random.uniform(-0.1, 0.1), y + random.uniform(-0.1, 0.1), 0.2 + j * 0.38), (s * 1.3, s, s * 0.8), stone, (0, 0, random.uniform(0, 3)))

# right foreground fence post + rocks
box("fpost", (3.4, -1.2, 0.9), (0.22, 0.22, 1.8), wood_warm, (0.04, -0.05, 0.2))
box("frail", (4.3, -1.0, 1.15), (1.8, 0.1, 0.18), wood_warm, (0, 0.06, 0.2))
for i in range(16):
    sz = random.uniform(0.25, 0.6)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1, location=(random.uniform(1.6, 5.0), random.uniform(-1.8, 0.2), sz * 0.25))
    rk = bpy.context.object; rk.scale = (sz * 1.3, sz, sz * 0.6); rk.rotation_euler[2] = random.uniform(0, 3)
    rk.data.materials.append(stone); col.objects.link(rk); scene.collection.objects.unlink(rk)

# ---------- barrel (tipped) ----------
barrel = bpy.data.objects.new("barrel_root", None); link(barrel)
barrel.location = (0.5, -0.6, 0.5); barrel.rotation_euler = (math.radians(90), math.radians(10), math.radians(105))
bbm = bmesh.new(); ring_n, seg = 9, 28; L_ = 1.25; rings = []
for i in range(ring_n):
    z = -L_ / 2 + L_ * i / (ring_n - 1)
    rad = 0.44 + 0.08 * math.cos(math.pi * z / L_)
    rings.append([bbm.verts.new((rad * math.cos(2 * math.pi * k / seg), rad * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)])
for a_, b_ in zip(rings[:-1], rings[1:]):
    for k in range(seg):
        bbm.faces.new((a_[k], a_[(k + 1) % seg], b_[(k + 1) % seg], b_[k]))
bbm.faces.new(rings[0][::-1]); bbm.faces.new(rings[-1])
bme = bpy.data.meshes.new("barrel"); bbm.to_mesh(bme); bbm.free()
for f in bme.polygons: f.use_smooth = True
bo = bpy.data.objects.new("barrel", bme); bo.data.materials.append(stave_m); link(bo); bo.parent = barrel
for z in (-0.5, -0.2, 0.2, 0.5):
    rad = 0.44 + 0.08 * math.cos(math.pi * z / L_) + 0.012
    bpy.ops.mesh.primitive_torus_add(location=(0, 0, z), major_radius=rad, minor_radius=0.018, major_segments=40)
    t = bpy.context.object; t.data.materials.append(iron); col.objects.link(t); scene.collection.objects.unlink(t); t.parent = barrel

# ---------- cart ----------
cx, cy = 14.5, 8.5
box("cartbody", (cx, cy, 1.9), (3.2, 1.6, 0.9), wood_dark)
box("carttop", (cx, cy, 3.1), (3.4, 1.8, 0.1), wood_dark)
for sx_ in (-1.5, 1.5):
    for sy_ in (-0.8, 0.8):
        box("cp", (cx + sx_, cy + sy_, 2.5), (0.07, 0.07, 1.2), wood_dark)
for sy_ in (-1.0, 1.0):
    bpy.ops.mesh.primitive_torus_add(location=(cx + 0.7, cy + sy_, 1.0), rotation=(math.radians(90), 0, 0), major_radius=1.0, minor_radius=0.05)
    w = bpy.context.object; w.data.materials.append(wood_dark); col.objects.link(w); scene.collection.objects.unlink(w)
    for k in range(8):
        a = k * math.pi / 8
        box("sp", (cx + 0.7, cy + sy_, 1.0), (2.0, 0.05, 0.05), wood_dark, (0, a, 0))
box("shaft", (cx - 3.0, cy, 0.8), (3.5, 0.08, 0.1), wood_dark, (0, math.radians(8), 0))

# ---------- weeds / dry brush ----------
def weeds(n, area, hmin, hmax, seed):
    random.seed(seed)
    bm = bmesh.new()
    for _ in range(n):
        x = random.uniform(area[0], area[1]); y = random.uniform(area[2], area[3])
        h = random.uniform(hmin, hmax); lean = Vector((random.uniform(-.4, .4), random.uniform(-.4, .4)))
        for k in range(random.randint(3, 6)):
            d = Vector((random.uniform(-.5, .5), random.uniform(-.5, .5)))
            base = Vector((x, y, 0)); mid = base + Vector((d.x * .3 + lean.x * .3, d.y * .3 + lean.y * .3, h * .55))
            tip = base + Vector((d.x + lean.x, d.y + lean.y, h))
            r = bmesh.ops.create_cone(bm, cap_ends=False, segments=3, radius1=0.012, radius2=0.002, depth=1.0)
            vs = r["verts"]
            # orient cone from base to tip
            dirv = tip - base; L = dirv.length
            q = Vector((0, 0, 1)).rotation_difference(dirv.normalized())
            for v in vs:
                v.co = q @ Vector((v.co.x, v.co.y, (v.co.z + 0.5) * L)) + base
            # small twigs
            for _ in range(2):
                f = random.uniform(0.4, 0.8); p0 = base + dirv * f
                r2 = bmesh.ops.create_cone(bm, cap_ends=False, segments=3, radius1=0.007, radius2=0.001, depth=1.0)
                dd = Vector((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.3, 1))).normalized() * L * 0.3
                q2 = Vector((0, 0, 1)).rotation_difference(dd.normalized())
                for v in r2["verts"]:
                    v.co = q2 @ Vector((v.co.x, v.co.y, (v.co.z + 0.5) * dd.length)) + p0
    me = bpy.data.meshes.new("weeds"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("weeds", me); o.data.materials.append(weed_m); link(o)

weeds(420, (-1, 14, 1.5, 9), 0.8, 2.2, 1)     # behind fence & beside house
weeds(110, (1.4, 9, -2, 1.2), 0.4, 1.4, 2)     # foreground right of the barrel
weeds(60, (-2.2, -0.8, -7, 10), 0.3, 1.0, 4)  # road edge along the wall
weeds(90, (-11, -8.5, -6, 12), 0.3, 1.0, 3)   # far verge

# hedge / dark shrub mass right of house
for (lx, ly, sc) in [(W_ / 2 + 1.6, -1.5, 1.7), (W_ / 2 + 3.6, -1.0, 1.4), (W_ / 2 + 2.4, -3.2, 1.2)]:
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=1, location=house_local(lx, ly, sc * 0.7))
    sh = bpy.context.object; sh.scale = (sc * 1.3, sc, sc * 0.9)
    sd = sh.modifiers.new("d", "DISPLACE"); st_ = bpy.data.textures.new("sh", "CLOUDS"); st_.noise_scale = 0.35; sd.texture = st_; sd.strength = 0.5
    sh.data.materials.append(shrub_m); col.objects.link(sh); scene.collection.objects.unlink(sh)
    bpy.ops.object.shade_smooth()
weeds(160, (house_local(W_ / 2 + 1, -3, 0)[0], house_local(W_ / 2 + 5, -3, 0)[0], 2, 7), 1.2, 2.6, 5)

# ---------- bare trees ----------
def tree(base, height, seed):
    random.seed(seed)
    bm = bmesh.new()
    def branch(p, d, length, rad, depth):
        end = p + d * length
        r = bmesh.ops.create_cone(bm, cap_ends=False, segments=5, radius1=rad, radius2=rad * 0.65, depth=1.0)
        q = Vector((0, 0, 1)).rotation_difference(d)
        for v in r["verts"]:
            v.co = q @ Vector((v.co.x, v.co.y, (v.co.z + 0.5) * length)) + p
        if depth == 0 or rad < 0.01: return
        for _ in range(random.randint(2, 3)):
            nd = (d + Vector((random.uniform(-.8, .8), random.uniform(-.8, .8), random.uniform(-.1, .5)))).normalized()
            branch(end, nd, length * random.uniform(0.65, 0.85), rad * 0.62, depth - 1)
    branch(Vector(base), Vector((random.uniform(-.1, .1), random.uniform(-.1, .1), 1)).normalized(), height * 0.35, height * 0.03, 6)
    me = bpy.data.meshes.new("tree"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("tree", me); o.data.materials.append(bark); link(o)
    return o

tree((-9, 9, 0), 9, 11)
tree((-17, 14, 0), 8, 12)
tree((-13, 24, 0), 10, 13)
tree((22, 11, 0), 9, 14)
tree((26, 22, 0), 8, 15)
# large foreground-right branch silhouette entering from top right

# ---------- sky, moon, lights ----------
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wl = world.node_tree.links
bg = wn["Background"]
bg.inputs["Color"].default_value = (0.01, 0.02, 0.05, 1)
bg.inputs["Strength"].default_value = 0.6
# cloud dome (world-nodes noise proved constant headless, so use an emissive dome)
bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0), segments=64, ring_count=32)
dome = bpy.context.object; dome.scale = (400, 400, 400); col.objects.link(dome); scene.collection.objects.unlink(dome)
dm = bpy.data.materials.new("sky"); dm.use_nodes = True
dn = dm.node_tree.nodes; dl = dm.node_tree.links
for n_ in list(dn): dn.remove(n_)
o_ = dn.new("ShaderNodeOutputMaterial"); em = dn.new("ShaderNodeEmission")
tcd = dn.new("ShaderNodeTexCoord"); mpd = dn.new("ShaderNodeMapping"); ntd = dn.new("ShaderNodeTexNoise")
mpd.inputs["Scale"].default_value = (1.2, 1.2, 3.0)
ntd.inputs["Scale"].default_value = 3.0; ntd.inputs["Detail"].default_value = 12; ntd.inputs["Roughness"].default_value = 0.6
dl.new(tcd.outputs["Object"], mpd.inputs["Vector"]); dl.new(mpd.outputs["Vector"], ntd.inputs["Vector"])
rd = dn.new("ShaderNodeValToRGB")
rd.color_ramp.elements[0].position = 0.46; rd.color_ramp.elements[0].color = (0.004, 0.01, 0.03, 1)
rd.color_ramp.elements[1].position = 0.68; rd.color_ramp.elements[1].color = (0.35, 0.45, 0.65, 1)
dl.new(ntd.outputs["Fac"], rd.inputs["Fac"]); dl.new(rd.outputs["Color"], em.inputs["Color"])
em.inputs["Strength"].default_value = 0.45
dl.new(em.outputs["Emission"], o_.inputs["Surface"])
dome.data.materials.append(dm); dome.visible_shadow = False
# volume fog
vol = wn.new("ShaderNodeVolumeScatter"); vol.inputs["Density"].default_value = 0.0008
vol.inputs["Color"].default_value = (0.55, 0.65, 0.85, 1)
wl.new(vol.outputs["Volume"], wn["World Output"].inputs["Volume"])

# moon (upper left of camera view, far)
bpy.ops.mesh.primitive_uv_sphere_add(radius=9, location=(-30, 160, 50), segments=48, ring_count=24)
mo = bpy.context.object; mo.data.materials.append(moon_m); col.objects.link(mo); scene.collection.objects.unlink(mo)
mo.visible_shadow = False
sun = bpy.data.lights.new("moonlight", "SUN"); sun.energy = 2.2; sun.color = (0.55, 0.68, 1.0); sun.angle = math.radians(2)
so = bpy.data.objects.new("moonlight", sun); link(so)
so.rotation_euler = (math.radians(-58), 0, math.radians(30))   # from upper-left/behind toward camera
# cool fill so shadows keep a blue cast
fill = bpy.data.lights.new("fill", "AREA"); fill.energy = 3500; fill.color = (0.3, 0.4, 0.8); fill.size = 30
fo = bpy.data.objects.new("fill", fill); fo.location = (-10, -10, 25); fo.rotation_euler = (math.radians(30), 0, math.radians(-20)); link(fo)

# ground-hugging mist near the road (local volume)
bpy.ops.mesh.primitive_cube_add(location=(-7, 26, 2.5), scale=(9, 18, 2.5))
mist = bpy.context.object; mist.display_type = "WIRE"; col.objects.link(mist); scene.collection.objects.unlink(mist)
mm = bpy.data.materials.new("mist"); mm.use_nodes = True
mn = mm.node_tree.nodes; ml = mm.node_tree.links
for n_ in list(mn): mn.remove(n_)
out = mn.new("ShaderNodeOutputMaterial"); vs = mn.new("ShaderNodeVolumeScatter")
nt2 = mn.new("ShaderNodeTexNoise"); nt2.inputs["Scale"].default_value = 0.25
tc2 = mn.new("ShaderNodeTexCoord"); ml.new(tc2.outputs["Object"], nt2.inputs["Vector"])
mul = mn.new("ShaderNodeMath"); mul.operation = "MULTIPLY"; mul.inputs[1].default_value = 0.09
ml.new(nt2.outputs["Fac"], mul.inputs[0]); ml.new(mul.outputs["Value"], vs.inputs["Density"])
vs.inputs["Color"].default_value = (0.6, 0.7, 0.9, 1)
ml.new(vs.outputs["Volume"], out.inputs["Volume"])
mist.data.materials.append(mm)

# moon halo: camera-facing additive glow card just behind the moon
bpy.ops.mesh.primitive_plane_add(size=90, location=(-30, 175, 50), rotation=(math.radians(90), 0, 0))
halo = bpy.context.object; col.objects.link(halo); scene.collection.objects.unlink(halo)
hm = bpy.data.materials.new("halo"); hm.use_nodes = True
hn = hm.node_tree.nodes; hl = hm.node_tree.links
for n_ in list(hn): hn.remove(n_)
ho = hn.new("ShaderNodeOutputMaterial"); htc = hn.new("ShaderNodeTexCoord"); hlen = hn.new("ShaderNodeVectorMath"); hlen.operation = "LENGTH"
hmr = hn.new("ShaderNodeMapRange"); hmr.inputs["From Min"].default_value = 0.0; hmr.inputs["From Max"].default_value = 1.0
hmr.inputs["To Min"].default_value = 1.0; hmr.inputs["To Max"].default_value = 0.0
hpw = hn.new("ShaderNodeMath"); hpw.operation = "POWER"; hpw.inputs[1].default_value = 3.0
hem = hn.new("ShaderNodeEmission"); hem.inputs["Color"].default_value = (0.55, 0.65, 0.9, 1)
hms = hn.new("ShaderNodeMath"); hms.operation = "MULTIPLY"; hms.inputs[1].default_value = 1.6
htr = hn.new("ShaderNodeBsdfTransparent"); had = hn.new("ShaderNodeAddShader")
hl.new(htc.outputs["Object"], hlen.inputs[0]); hl.new(hlen.outputs["Value"], hmr.inputs["Value"])
hl.new(hmr.outputs["Result"], hpw.inputs[0]); hl.new(hpw.outputs["Value"], hms.inputs[0]); hl.new(hms.outputs["Value"], hem.inputs["Strength"])
hl.new(htr.outputs[0], had.inputs[0]); hl.new(hem.outputs[0], had.inputs[1]); hl.new(had.outputs[0], ho.inputs["Surface"])
halo.data.materials.append(hm); halo.visible_shadow = False; halo.visible_diffuse = False; halo.visible_glossy = False

# chimney smoke: drifting volume plume above the main chimney
top = Vector(house_local(W_ / 2 - 0.9, 0.3, H_ + 5.1))
bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=0.6, radius2=3.0, depth=9, location=top + Vector((-1.7, 0.0, 4.2)))
smoke = bpy.context.object; smoke.rotation_euler = (0, math.radians(-22), 0)
smoke.display_type = "WIRE"; col.objects.link(smoke); scene.collection.objects.unlink(smoke)
sm = bpy.data.materials.new("smoke"); sm.use_nodes = True
sn = sm.node_tree.nodes; sl = sm.node_tree.links
for n_ in list(sn): sn.remove(n_)
so_ = sn.new("ShaderNodeOutputMaterial"); svs = sn.new("ShaderNodeVolumeScatter"); svs.inputs["Color"].default_value = (0.75, 0.8, 0.9, 1)
stc = sn.new("ShaderNodeTexCoord"); snt = sn.new("ShaderNodeTexNoise"); snt.inputs["Scale"].default_value = 1.4; snt.inputs["Detail"].default_value = 6
sgr = sn.new("ShaderNodeSeparateXYZ"); sfade = sn.new("ShaderNodeMapRange")
sfade.inputs["From Min"].default_value = -1.0; sfade.inputs["From Max"].default_value = 1.0; sfade.inputs["To Min"].default_value = 1.0; sfade.inputs["To Max"].default_value = 0.0
scr = sn.new("ShaderNodeMapRange"); scr.inputs["From Min"].default_value = 0.4; scr.inputs["From Max"].default_value = 0.65
smul = sn.new("ShaderNodeMath"); smul.operation = "MULTIPLY"
smul2 = sn.new("ShaderNodeMath"); smul2.operation = "MULTIPLY"; smul2.inputs[1].default_value = 6.0
sl.new(stc.outputs["Object"], snt.inputs["Vector"]); sl.new(snt.outputs["Fac"], scr.inputs["Value"])
sl.new(stc.outputs["Generated"], sgr.inputs[0]); sl.new(sgr.outputs["Z"], sfade.inputs["Value"])
sfade.inputs["From Min"].default_value = 0.0; sfade.inputs["From Max"].default_value = 1.0
sl.new(scr.outputs["Result"], smul.inputs[0]); sl.new(sfade.outputs["Result"], smul.inputs[1])
sl.new(smul.outputs["Value"], smul2.inputs[0]); sl.new(smul2.outputs["Value"], svs.inputs["Density"])
sl.new(svs.outputs["Volume"], so_.inputs["Volume"])
smoke.data.materials.append(sm)

# ---------- camera ----------
cam = bpy.data.cameras.new("cam"); cam.lens = 26
co = bpy.data.objects.new("cam", cam); link(co); scene.camera = co
co.location = (-3.0, -9.0, 1.7)
target = Vector((2.5, 9, 3.8))
d = target - co.location
co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()

# ---------- render ----------
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"; scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6; scene.cycles.volume_bounces = 1
scene.cycles.volume_step_rate = 4.0
scene.render.resolution_x = W; scene.render.resolution_y = int(W * 9 / 16)
scene.render.filepath = OUT; scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"; scene.view_settings.look = "AgX - Punchy"
scene.view_settings.exposure = 0.6
bpy.ops.wm.save_as_mainfile(filepath=OUT.rsplit(".", 1)[0] + ".blend")
bpy.ops.render.render(write_still=True)
print("done", OUT)
