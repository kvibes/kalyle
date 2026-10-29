"""Polish pass for the haunted village: v3 -> v4.

Opens the saved v3 scene and keeps its layout. It refines what still read as placeholder geometry:
  * main house: lapped siding with corner boards and a stone plinth in place of the 25 strips;
    real window openings (Boolean cuts) with thin glass, sashes, sills and recessed reveals;
    rooms behind the glass (plaster, floors, beams, curtains, a few silhouettes); the upstairs
    window is lit by a hidden lamp inside instead of an emissive panel; shingled roofs;
  * stone wall: the 140 box stones become irregular fieldstones (10 shared meshes) at the same
    positions, rotations and sizes;
  * fence: bevelled posts and rails with weathered, grain-following wood;
  * moon: visible surface detail instead of a saturated disc; warmer fieldstone.

Usage: python3 polish_v4.py <in.blend> <out.blend> <report.json>
"""
import bpy, bmesh, math, random, sys, os, json
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shader_helpers import SG, new_mat, reset_mat, principled

IN_BLEND, OUT_BLEND, REPORT = sys.argv[1], sys.argv[2], sys.argv[3]
bpy.ops.wm.open_mainfile(filepath=IN_BLEND)
scene = bpy.context.scene
log = {"removed": [], "added": [], "changed": []}

# ------------------------------------------------------------------ house frame (read from the scene)
main = bpy.data.objects["main"]
HX, HY, HR = main.location.x, main.location.y, main.rotation_euler.z
W, D, H = main.scale.x * 2, main.scale.y * 2, main.scale.z * 2
MH = Matrix.Translation((HX, HY, 0.0)) @ Matrix.Rotation(HR, 4, "Z")
MH_inv = MH.inverted()
FRONT = -D / 2


def local(o):
    return MH_inv @ o.matrix_world.translation


def coll(name):
    c = bpy.data.collections.new(name)
    scene.collection.children.link(c)
    return c


c_house, c_interior, c_helpers = coll("House_v4"), coll("House_v4_interior"), coll("House_v4_cutters")

CUBE = bpy.data.meshes.new("unit_cube")
_bm = bmesh.new(); bmesh.ops.create_cube(_bm, size=2.0); _bm.to_mesh(CUBE); _bm.free()
CUBE.materials.append(None)
PANE = bpy.data.meshes.new("unit_pane")      # 2 x 2 plane in local XZ, facing -Y
PANE.from_pydata([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)], [], [(0, 1, 2, 3)])
PANE.materials.append(None)


def place(name, mesh, lpos, size, mat, c, rot=None):
    """Object sharing `mesh`, positioned in house-local space; material linked per object."""
    o = bpy.data.objects.new(name, mesh)
    o.material_slots[0].link = "OBJECT"
    o.material_slots[0].material = mat
    R = rot if rot is not None else Matrix.Identity(4)
    o.matrix_world = MH @ Matrix.Translation(lpos) @ R @ Matrix.Diagonal((size[0] / 2, size[1] / 2, size[2] / 2, 1.0))
    c.objects.link(o)
    return o


def box(name, lpos, size, mat, c=None, rot=None):
    return place(name, CUBE, lpos, size, mat, c or c_house, rot)


# ------------------------------------------------------------------ materials
def wood_grain_mat(name, c1, c2, along, rough=0.78, seams=False, dirt_band=True):
    """Weathered wood whose grain follows the object's long mesh axis ('x' or 'z')."""
    m, nt, out = new_mat(name)
    g = SG(nt)
    ob = g.coords("Object")
    rnd = g.node("ShaderNodeObjectInfo").outputs["Random"]
    sc = (0.7, 40, 40) if along == "x" else (40, 40, 0.7)
    grain = g.noise(g.mapping(ob, sc), 3.0, 6.0, 0.62)
    fine = g.noise(g.mapping(ob, tuple(s * 3 for s in sc)), 4.0, 3.0, 0.5)
    v = g.add(g.mul(grain, 0.6), g.mul(fine, 0.25), g.mul(g.math("SUBTRACT", rnd, 0.5), 0.25))
    col = g.ramp(v, [(0.25, c1), (0.75, c2)])
    P = g.position()
    shade = g.maprange(g.noise(g.mapping(P, (6, 6, 0.35)), 2.0, 4.0), 0.4, 0.7, 1.0, 0.72)   # vertical weather streaks
    if dirt_band:
        shade = g.mul(shade, g.maprange(g.sep(P)[2], 0.25, 1.3, 0.6, 1.0))                  # splash dirt near the ground
    height = g.mul(grain, 0.5)
    if seams:
        sx = g.math("FRACT", g.add(g.mul(g.sep(ob)[0], 0.85), g.mul(rnd, 7.0)))
        gap = g.math("MAXIMUM", g.maprange(sx, 0.0, 0.006, 1.0, 0.0), g.maprange(sx, 0.994, 1.0, 0.0, 1.0))
        shade = g.mul(shade, g.maprange(gap, 0.0, 1.0, 1.0, 0.3))
        height = g.math("SUBTRACT", height, g.mul(gap, 0.6))
    principled(g, out, g.tint(col, shade), g.add(rough, g.mul(fine, 0.12)), g.bump(height, 0.35, 0.003))
    return m


mat_siding = wood_grain_mat("siding_weathered", (0.034, 0.029, 0.025), (0.1, 0.087, 0.071), "x", seams=True)
mat_post = wood_grain_mat("fence_post_wood", (0.04, 0.036, 0.031), (0.12, 0.108, 0.092), "z")
mat_rail = wood_grain_mat("fence_rail_wood", (0.04, 0.036, 0.031), (0.12, 0.108, 0.092), "x")
mat_trim = bpy.data.materials["trim"]
nt, out = reset_mat(mat_trim); g = SG(nt)
P = g.position()
grime = g.maprange(g.noise(g.mapping(P, (4, 4, 1.2)), 3.0, 6.0), 0.35, 0.75, 0.55, 1.0)
principled(g, out, g.tint((0.085, 0.077, 0.065, 1), grime), g.maprange(grime, 0.55, 1.0, 0.85, 0.6))
log["changed"].append("trim material (casings, sashes, sills, corner boards, portico): darker weathered paint with grime instead of clean pale")

m_door, nt, out = new_mat("door_wood"); g = SG(nt)
ox = g.sep(g.coords("Object"))[0]
plank = g.maprange(g.math("FRACT", g.mul(ox, 2.5)), 0.0, 0.03, 0.45, 1.0)
principled(g, out, g.tint(g.mix(g.noise(g.mapping(g.coords("Object"), (30, 30, 0.6)), 3.0), (0.03, 0.02, 0.013, 1), (0.065, 0.045, 0.03, 1)), plank), 0.7)

def plaster(name, color):
    m, nt, out = new_mat(name); g = SG(nt)
    stain = g.maprange(g.noise(g.position(), 1.6, 5.0), 0.35, 0.75, 0.75, 1.05)
    principled(g, out, g.tint((*color, 1), stain), 0.92)
    return m


m_plaster = plaster("interior_plaster", (0.45, 0.39, 0.31))          # lit room
m_plaster_dark = plaster("interior_plaster_dim", (0.16, 0.14, 0.12))  # unlit rooms

m_floor, nt, out = new_mat("floor_boards"); g = SG(nt)
principled(g, out, g.mix(g.noise(g.mapping(g.position(), (1, 25, 1)), 3.0), (0.04, 0.026, 0.016, 1), (0.09, 0.06, 0.036, 1)), 0.6)

m_darkwood, nt, out = new_mat("dark_wood"); g = SG(nt)
principled(g, out, g.mix(g.noise(g.mapping(g.coords("Object"), (2, 30, 2)), 3.0), (0.025, 0.016, 0.01, 1), (0.06, 0.04, 0.025, 1)), 0.7)

m_canvas, nt, out = new_mat("painting_canvas"); g = SG(nt)
principled(g, out, g.ramp(g.noise(g.coords("Object"), 2.5, 5.0), [(0.3, (0.05, 0.06, 0.04)), (0.6, (0.2, 0.14, 0.07)), (0.8, (0.12, 0.09, 0.06))]), 0.8)


def curtain_mat(name, color, translucent):
    m, nt, out = new_mat(name); g = SG(nt)
    weave = g.maprange(g.noise(g.mapping(g.coords("Object"), (40, 40, 3)), 4.0, 2.0), 0.3, 0.7, 0.85, 1.05)
    principled(g, out, g.tint((*color, 1), weave), 0.85, translucent=translucent, **{"Sheen Weight": 0.3})
    return m


m_curtain_warm = curtain_mat("curtain_warm", (0.42, 0.24, 0.1), 0.45)
m_curtain_pale = curtain_mat("curtain_pale", (0.34, 0.32, 0.28), 0.25)

m_glass, nt, out = new_mat("window_glass"); g = SG(nt)
ob = g.coords("Object")
gx, _, gz = g.sep(ob)
edge = g.math("MAXIMUM", g.math("ABSOLUTE", gx), g.math("ABSOLUTE", gz))
smudge = g.noise(g.mapping(ob, (3, 3, 3)), 4.0, 4.0)
grime = g.mul(g.maprange(edge, 0.78, 1.0, 0.0, 1.0), g.maprange(smudge, 0.35, 0.7, 0.4, 1.0))
glass = g.node("ShaderNodeBsdfPrincipled")
glass.inputs["Base Color"].default_value = (0.9, 0.95, 0.92, 1)
glass.inputs["Transmission Weight"].default_value = 1.0
glass.inputs["IOR"].default_value = 1.52
glass.inputs["Thin Wall"].default_value = True
g.put(glass.inputs["Roughness"], g.add(0.01, g.mul(g.maprange(smudge, 0.45, 0.75, 0.0, 1.0), 0.035), g.mul(grime, 0.3)))
dirt = g.node("ShaderNodeBsdfPrincipled")
dirt.inputs["Base Color"].default_value = (0.11, 0.1, 0.085, 1); dirt.inputs["Roughness"].default_value = 0.95
mixg = g.node("ShaderNodeMixShader")
g.put(mixg.inputs[0], g.mul(grime, 0.6))
g.l.new(glass.outputs[0], mixg.inputs[1]); g.l.new(dirt.outputs[0], mixg.inputs[2]); g.l.new(mixg.outputs[0], out.inputs["Surface"])

m_plinth, nt, out = new_mat("plinth_stone"); g = SG(nt)
P = g.position()
vor = g.node("ShaderNodeTexVoronoi", feature="DISTANCE_TO_EDGE"); g.put(vor.inputs["Vector"], g.mapping(P, (1.0, 1.0, 1.8))); vor.inputs["Scale"].default_value = 3.2
cell = g.node("ShaderNodeTexVoronoi"); g.put(cell.inputs["Vector"], g.mapping(P, (1.0, 1.0, 1.8))); cell.inputs["Scale"].default_value = 3.2
joint = g.maprange(vor.outputs["Distance"], 0.0, 0.05, 0.25, 1.0)
scol = g.ramp(g.sep(cell.outputs["Color"])[0], [(0.0, (0.04, 0.037, 0.032)), (1.0, (0.1, 0.092, 0.08))])
principled(g, out, g.tint(scol, joint), 0.85, g.bump(vor.outputs["Distance"], 0.6, 0.02))

m_gable, nt, out = new_mat("gable_boards"); g = SG(nt)
z = g.sep(g.position())[2]
groove = g.maprange(g.math("FRACT", g.math("DIVIDE", z, 0.18)), 0.0, 0.08, 1.0, 0.0)
gcol = g.mix(g.noise(g.mapping(g.position(), (0.6, 0.6, 30)), 3.0), (0.034, 0.029, 0.025, 1), (0.09, 0.078, 0.064, 1))
principled(g, out, g.tint(gcol, g.maprange(groove, 0.0, 1.0, 1.0, 0.35)), 0.8, g.bump(groove, 0.4, 0.01))

m_soffit, nt, out = new_mat("soffit_wood"); g = SG(nt)
principled(g, out, (0.028, 0.022, 0.017, 1), 0.8)

# shingles: rebuild the shared roof material in place, so every roof that uses it updates
roof_m = bpy.data.materials["roof"]
nt, out = reset_mat(roof_m); g = SG(nt)
ob = g.coords("Object")
ox, oy, oz = g.sep(ob)
s = g.mul(oz, 1.38)                     # distance up the slope from the eave
brick = g.node("ShaderNodeTexBrick", offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
g.put(brick.inputs["Vector"], g.comb(ox, s, 0.0))
for k, v in (("Scale", 1.0), ("Brick Width", 0.26), ("Row Height", 0.17), ("Mortar Size", 0.006), ("Mortar Smooth", 0.3), ("Bias", 0.0)):
    brick.inputs[k].default_value = v
brick.inputs["Color1"].default_value = (0.05, 0.047, 0.044, 1)
brick.inputs["Color2"].default_value = (0.085, 0.079, 0.071, 1)
brick.inputs["Mortar"].default_value = (0.008, 0.008, 0.008, 1)
course = g.math("FRACT", g.math("DIVIDE", s, 0.17))
wobble = g.noise(g.comb(ox, s, 0.0), 6.0, 3.0)
height = g.add(g.mul(g.math("SUBTRACT", 1.0, course), 0.75), g.mul(g.math("SUBTRACT", 1.0, brick.outputs["Factor"]), 0.2), g.mul(wobble, 0.2))
odd = g.maprange(g.noise(g.mapping(g.comb(ox, s, 0.0), (3.8, 5.9, 1.0)), 9.0, 1.0), 0.62, 0.7, 1.0, 0.55)   # scattered darker, newer or damp shingles
moss = g.mul(g.maprange(g.noise(g.position(), 0.9, 5.0), 0.55, 0.72, 0.0, 1.0), g.maprange(oz, 0.0, 1.5, 1.0, 0.35))
rcol = g.mix(g.mul(moss, 0.7), g.tint(brick.outputs["Color"], odd), (0.03, 0.036, 0.018, 1))
principled(g, out, rcol, g.add(0.8, g.mul(wobble, 0.12)), g.bump(height, 0.8, 0.03))
log["changed"].append("roof material rebuilt in place as weathered shingles (staggered courses, butt-edge relief, moss toward the eaves); used by all 9 roofs")

# ------------------------------------------------------------------ siding, corner boards, plinth
for o in [o for o in bpy.data.objects if o.name.split(".")[0] == "cb"]:
    log["removed"].append(o.name)
    bpy.data.objects.remove(o, do_unlink=True)

BH, BT, EXP, Z0 = 0.21, 0.022, 0.18, 0.42      # board height, thickness, exposure, first course
TILT = Matrix.Rotation(math.radians(-5.5), 4, "X")   # bottom edge kicks out over the course below
front_boards, side_boards = [], []
n_rows = int((H - 0.1 - Z0) / EXP) + 1
for i in range(n_rows):
    zc = Z0 + i * EXP + BH / 2
    front_boards.append(box("siding_front", (0.0, FRONT - 0.012 - BT / 2, zc), (W + 0.04, BT, BH), mat_siding, rot=TILT))
    side_boards.append(box("siding_right", (W / 2 + 0.012 + BT / 2, 0.0, zc), (D + 0.04, BT, BH), mat_siding,
                           rot=Matrix.Rotation(math.radians(90), 4, "Z") @ TILT))
for (cx, cy) in ((W / 2 + 0.035, FRONT - 0.035), (W / 2 + 0.035, -FRONT + 0.035), (-W / 2 - 0.035, FRONT - 0.035)):
    box("corner_board", (cx, cy, (Z0 + H) / 2), (0.14, 0.14, H - Z0), mat_trim)
box("plinth", (0.0, 0.0, 0.18), (W + 0.16, D + 0.16, 0.5), m_plinth)
log["added"].append("lapped siding: %d front + %d right-side boards (21 cm, 18 cm exposure, kicked out 5.5 deg), 3 corner boards, stone plinth" % (n_rows, n_rows))

# ------------------------------------------------------------------ windows: read the v2 openings
windows = []
for o in [o for o in bpy.data.objects if o.name.split(".")[0] == "w"]:
    p = local(o)
    windows.append({"x": p.x, "z": p.z, "w": o.scale.x * 2, "h": o.scale.z * 2,
                    "lit": o.material_slots[0].material.name == "window"})
    log["removed"].append(o.name)
    bpy.data.objects.remove(o, do_unlink=True)
windows.sort(key=lambda w: (w["z"], w["x"]))

ROOM_Y0, ROOM_Y1 = FRONT + 0.3, FRONT + 3.3          # wall 30 cm thick, rooms 3 m deep
FLOORS = {"down": (0.3, 3.0), "up": (3.25, H - 0.3)}


def cutter(name, boxes, mat):
    bm = bmesh.new()
    for (x0, x1, y0, y1, z0, z1) in boxes:
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r["verts"]:
            v.co = Vector((x0 + (v.co.x + 0.5) * (x1 - x0), y0 + (v.co.y + 0.5) * (y1 - y0), z0 + (v.co.z + 0.5) * (z1 - z0)))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    o.matrix_world = MH
    o.display_type = "WIRE"; o.hide_render = True
    c_helpers.objects.link(o)
    return o


rooms = cutter("cut_rooms", [(-W / 2 + 0.3, W / 2 - 0.3, ROOM_Y0, ROOM_Y1, z0, z1) for z0, z1 in FLOORS.values()], m_plaster_dark)
openings = cutter("cut_openings", [(w["x"] - w["w"] / 2, w["x"] + w["w"] / 2, FRONT - 0.3, ROOM_Y0 + 0.05,
                                     w["z"] - w["h"] / 2, w["z"] + w["h"] / 2) for w in windows], m_plaster_dark)


def boolean(o, cut, name):
    m = o.modifiers.new(name, "BOOLEAN")
    m.operation = "DIFFERENCE"; m.solver = "EXACT"; m.object = cut; m.material_mode = "TRANSFER"
    return m


boolean(main, rooms, "Rooms")
boolean(main, openings, "Openings")
for b in front_boards:
    boolean(b, openings, "Openings")
log["added"].append("window openings cut through the wall and siding (Boolean, exact); 2 room cavities 3 m deep behind them")

GLASS_Y = FRONT + 0.04
for w in windows:
    x, z, ww, wh = w["x"], w["z"], w["w"], w["h"]
    g_o = place("glass", PANE, (x, GLASS_Y, z), (ww - 0.05, 1.0, wh - 0.05), m_glass, c_house)
    # only the lit window passes direct light (the lamp out to the yard); the others keep the
    # big fill light from flooding the unlit rooms, which then read dark and show reflections
    g_o.visible_shadow = not w["lit"]
    for dz in (-1, 1):
        box("sash", (x, GLASS_Y, z + dz * (wh / 2 - 0.025)), (ww, 0.05, 0.05), mat_trim)
    for dx in (-1, 1):
        box("sash", (x + dx * (ww / 2 - 0.025), GLASS_Y, z), (0.05, 0.05, wh), mat_trim)
    box("sill", (x, FRONT - 0.06, z - wh / 2 - 0.035), (ww + 0.18, 0.12, 0.05), mat_trim)
    for o in bpy.data.objects:
        base = o.name.split(".")[0]
        if base not in ("m", "f"):
            continue
        p = local(o)
        if abs(p.x - x) <= ww / 2 + 0.12 and abs(p.z - z) <= wh / 2 + 0.12:
            if base == "m":     # glazing bars sit on the glass, not 14 cm in front of it
                o.location = MH @ Vector((p.x, FRONT + 0.012, p.z)); o.scale.y = 0.015
            else:               # casings sit on the siding instead of floating 1 cm off it
                o.location = MH @ Vector((p.x, FRONT - 0.075, p.z))
log["added"].append("%d windows: thin glass (IOR 1.52, edge grime, smudged roughness), sash frames, sills; glazing bars moved onto the glass, casings onto the siding" % len(windows))

# ------------------------------------------------------------------ interiors
lit = [w for w in windows if w["lit"]][0]
up_z0, up_z1 = FLOORS["up"]; dn_z0, dn_z1 = FLOORS["down"]
for name, (z0, z1) in FLOORS.items():
    box("floor_" + name, (0.0, (ROOM_Y0 + ROOM_Y1) / 2, z0 + 0.01), (W - 0.6, ROOM_Y1 - ROOM_Y0, 0.02), m_floor, c_interior)
    for bx in [v * 0.6 for v in range(-6, 7)]:
        box("beam_" + name, (bx, (ROOM_Y0 + ROOM_Y1) / 2, z1 - 0.08), (0.12, ROOM_Y1 - ROOM_Y0, 0.16), m_darkwood, c_interior)
lit_x0, lit_x1 = lit["x"] - 1.0, lit["x"] + 1.05
for px, (z0, z1), pm in ((lit_x0, FLOORS["up"], m_plaster), (lit_x1, FLOORS["up"], m_plaster),
                         (-2.35, FLOORS["up"], m_plaster_dark), (-1.25, FLOORS["down"], m_plaster_dark)):
    box("partition", (px, (ROOM_Y0 + ROOM_Y1) / 2, (z0 + z1) / 2), (0.1, ROOM_Y1 - ROOM_Y0 + 0.02, z1 - z0 + 0.02), pm, c_interior)
box("lit_back_wall", ((lit_x0 + lit_x1) / 2, ROOM_Y1 - 0.01, (up_z0 + up_z1) / 2), (lit_x1 - lit_x0, 0.02, up_z1 - up_z0), m_plaster, c_interior)
box("lit_ceiling", ((lit_x0 + lit_x1) / 2, (ROOM_Y0 + ROOM_Y1) / 2, up_z1 - 0.005), (lit_x1 - lit_x0, ROOM_Y1 - ROOM_Y0, 0.01), m_plaster, c_interior)
# lit room: a picture on the left partition, a wardrobe against the back wall
box("picture_frame", (lit_x0 + 0.07, ROOM_Y0 + 1.2, up_z0 + 1.2), (0.03, 0.55, 0.45), m_darkwood, c_interior)
box("picture", (lit_x0 + 0.085, ROOM_Y0 + 1.2, up_z0 + 1.2), (0.01, 0.45, 0.35), m_canvas, c_interior)
box("wardrobe", (lit_x0 + 0.45, ROOM_Y1 - 0.3, up_z0 + 0.95), (0.7, 0.5, 1.9), m_darkwood, c_interior)


def curtain(name, x, z, width, height, mat, folds=4, amp=0.025, seed=0):
    rng = random.Random(seed)
    nx, nz = folds * 8, 10
    ph = rng.uniform(0, 6.28)
    verts, faces = [], []
    for j in range(nz + 1):
        zt = j / nz
        for i in range(nx + 1):
            xt = i / nx
            verts.append(((xt - 0.5) * width, amp * math.sin(2 * math.pi * folds * xt + ph) * (0.6 + 0.4 * zt), (zt - 0.5) * height))
    for j in range(nz):
        for i in range(nx):
            a = j * (nx + 1) + i
            faces.append((a, a + 1, a + nx + 2, a + nx + 1))
    me = bpy.data.meshes.new(name); me.from_pydata(verts, [], faces)
    for f in me.polygons: f.use_smooth = True
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    o.matrix_world = MH @ Matrix.Translation((x, ROOM_Y0 + 0.04, z))
    c_interior.objects.link(o)
    return o


def dress(w, mat, sides, width, seed):
    top = w["z"] + w["h"] / 2 + 0.25
    hgt = w["h"] + 0.4
    for k, side in enumerate(sides):
        cx = w["x"] + side * (w["w"] / 2 - width / 2 + 0.08)
        curtain("curtain", cx, top - hgt / 2, width, hgt, mat, seed=seed + k)
    box("curtain_rod", (w["x"], ROOM_Y0 + 0.04, top + 0.02), (w["w"] + 0.5, 0.025, 0.025), m_darkwood, c_interior)


dress(lit, m_curtain_warm, (-1, 1), 0.3, 10)
others = [w for w in windows if not w["lit"]]
up_others = sorted([w for w in others if w["z"] > 3.0], key=lambda w: w["x"])
dn_others = sorted([w for w in others if w["z"] <= 3.0], key=lambda w: w["x"])
dress(up_others[0], m_curtain_pale, (1,), 0.42, 20)          # far-left upstairs: one panel drawn
dress(up_others[-1], m_curtain_pale, (-1, 1), 0.32, 30)      # right upstairs: both panels part-closed
dress(max(dn_others, key=lambda w: w["w"]), m_curtain_pale, (-1, 1), 0.5, 40)   # big downstairs window
log["added"].append("interiors: plaster rooms, floors, ceiling beams, partitions, curtains (warm in the lit room, pale elsewhere), picture and wardrobe silhouettes in the lit room")

# hidden lamp inside the lit room, out of the line of sight through the glass
lamp = bpy.data.lights.new("room_lamp", "POINT")
lamp.energy = 5000.0; lamp.color = (1.0, 0.6, 0.27); lamp.shadow_soft_size = 0.12
lamp_o = bpy.data.objects.new("room_lamp", lamp)
# beside the window, behind its right-hand jamb as seen from the camera: it rakes across the
# left curtain and reveal, which is what reads as a lit window from outside
lamp_o.location = MH @ Vector((lit["x"] + lit["w"] / 2 + 0.3, ROOM_Y0 + 0.2, lit["z"]))
c_interior.objects.link(lamp_o)
for n, e in (("winlight", 150.0), ("winlight2", None)):
    o = bpy.data.objects[n]
    o.visible_glossy = False            # no highlight blobs in the new glass
    if e is not None:
        log["changed"].append("%s: %.0f W -> %.0f W (the room lamp now carries the window glow); hidden from glossy rays" % (n, o.data.energy, e))
        o.data.energy = e
w2 = bpy.data.objects["winlight2"]
log["changed"].append("winlight2: %.0f W -> 1000 W, radius 0.25 -> 1.2 m (softer, no hot spot in the weeds)" % w2.data.energy)
w2.data.energy = 1000.0; w2.data.shadow_soft_size = 1.2
fill = bpy.data.objects["fill"]
log["changed"].append("fill: %.0f W -> 2600 W so the facade sits back and the lit window leads" % fill.data.energy)
fill.data.energy = 2600.0
log["changed"].append("winlight2 hidden from glossy rays (it made a lamp-like blob in the downstairs glass)")
log["added"].append("room_lamp: 5000 W warm point light inside the upstairs room, hidden from the camera; replaces the emissive window panel")
bpy.data.objects["door"].material_slots[0].link = "OBJECT"
bpy.data.objects["door"].material_slots[0].material = m_door

# main roof: gable ends read as boarded wall, underside as soffit
roof = bpy.data.objects["roof"]
roof.data.materials.append(m_gable); roof.data.materials.append(m_soffit)
for f in roof.data.polygons:
    if len(f.vertices) == 3:
        f.material_index = 1
    elif abs(f.normal.z + 1.0) < 1e-3:
        f.material_index = 2
log["changed"].append("main roof: gable triangles use boarded siding, underside uses soffit wood")

# ------------------------------------------------------------------ stone wall
fs = bpy.data.materials["fieldstone"]
nt, out = reset_mat(fs); g = SG(nt)
ob = g.coords("Object")
zr = g.sep(g.position())[2]
n1 = g.noise(ob, 2.5, 8.0, 0.6); n2 = g.noise(ob, 9.0, 6.0, 0.55)
n3 = g.noise(ob, 28.0, 4.0, 0.6)
rcol = g.ramp(g.add(g.mul(n1, 0.8), g.mul(n3, 0.2)), [(0.3, (0.045, 0.042, 0.038)), (0.55, (0.08, 0.076, 0.068)), (0.8, (0.115, 0.108, 0.095))])
lichen = g.maprange(g.noise(ob, 14.0, 3.0), 0.62, 0.69, 0.0, 1.0)
rcol = g.mix(g.mul(lichen, 0.55), rcol, (0.17, 0.17, 0.13, 1))
rcol = g.mix(g.maprange(zr, 0.0, 0.16, 0.85, 0.0), rcol, (0.026, 0.02, 0.014, 1))
principled(g, out, rcol, g.math("SUBTRACT", 0.88, g.mul(n2, 0.15)),
           g.bump(g.add(g.mul(n2, 0.45), g.mul(n1, 0.25), g.mul(n3, 0.3)), 0.7, 0.012))
log["changed"].append("fieldstone material: grey-brown stone with fine grain, sparse lichen, soil grime at ground level")


def stone_mesh(name, seed):
    rng = random.Random(seed)
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    waves = [(Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))).normalized() * rng.uniform(1.5, 5.0),
              rng.uniform(0, 6.28), rng.uniform(0.01, 0.035)) for _ in range(8)]
    e = rng.uniform(0.28, 0.42)         # superellipsoid exponent: blocky with softened corners
    # flat bedding planes top and bottom plus a few chipped faces
    planes = [(Vector((0, 0, 1)), rng.uniform(0.68, 0.82)), (Vector((0, 0, -1)), rng.uniform(0.72, 0.88))]
    planes += [(Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 0.5))).normalized(), rng.uniform(0.7, 0.9)) for _ in range(rng.randint(4, 7))]
    for v in bm.verts:
        d = v.co.normalized()
        p = Vector([math.copysign(abs(c) ** e, c) for c in d])
        for n, off in planes:
            h = p.dot(n)
            if h > off:
                p -= n * (h - off)
        v.co = p * (1 + sum(a * math.sin(k.dot(d) + ph) for k, ph, a in waves))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for f in me.polygons: f.use_smooth = True
    me.materials.append(fs)
    return me


stones = [stone_mesh("wall_stone_%d" % i, 500 + i) for i in range(10)]
c_wall = coll("StoneWall_v4")
rng = random.Random(9)
old = [o for o in bpy.data.objects if o.name.split(".")[0] == "st"]
for o in old:
    s = o.scale
    n = bpy.data.objects.new("wall_stone", rng.choice(stones))
    n.location = o.location.copy()
    n.rotation_euler = (rng.uniform(-0.08, 0.08), rng.uniform(-0.08, 0.08), o.rotation_euler.z)
    n.scale = (s.x * 1.05, s.y * 1.08, s.z * 1.05)
    c_wall.objects.link(n)
    bpy.data.objects.remove(o, do_unlink=True)
# the foreground rocks get the same stone meshes (their v3 subdivision + displacement made pillows)
rocks = [o for o in bpy.data.objects if o.name.startswith("Icosphere") and o.data.materials and o.data.materials[0] and o.data.materials[0].name == "fieldstone"]
for o in rocks:
    for m_ in list(o.modifiers):
        o.modifiers.remove(m_)
    o.data = rng.choice(stones)
    o.scale = (o.scale.x * 0.95, o.scale.y * 0.95, o.scale.z * 1.05)
log["changed"].append("%d foreground rocks: subdivision/displacement removed, now share the faceted fieldstone meshes; positions kept" % len(rocks))
log["changed"].append("stone wall: %d box stones replaced in place by irregular fieldstones (10 shared meshes, same positions, yaw and size)" % len(old))

# seat bottom-course stones on the terrain: their flat bedding planes sit higher than the old box
# bottoms did, so a few lifted off the soil. Heights come from the packed v3 height map.
import numpy as np
import ground_maps as gm
himg = bpy.data.images["terrain_height_2048.png"]
hn = himg.size[0]
hpx = np.empty(hn * hn * 4, np.float32); himg.pixels.foreach_get(hpx)
hmap = hpx.reshape(hn, hn, 4)[..., 0] * (gm.H_MAX - gm.H_MIN) + gm.H_MIN


def terrain_h(x, y):
    fx = (x - gm.X0) / gm.S * hn - 0.5; fy = (y - gm.Y0) / gm.S * hn - 0.5
    i, j = int(np.clip(np.floor(fx), 0, hn - 2)), int(np.clip(np.floor(fy), 0, hn - 2))
    tx, ty = min(max(fx - i, 0.0), 1.0), min(max(fy - j, 0.0), 1.0)
    return float((hmap[j, i] * (1 - tx) + hmap[j, i + 1] * tx) * (1 - ty) + (hmap[j + 1, i] * (1 - tx) + hmap[j + 1, i + 1] * tx) * ty)


bpy.context.view_layer.update()
seated = 0
for o in list(c_wall.objects) + rocks:
    low = min((o.matrix_world @ v.co for v in o.data.vertices), key=lambda p: p.z)
    if low.z > 0.15:
        continue                         # upper course rests on stones, not soil
    gap = low.z - terrain_h(low.x, low.y)
    if gap > 0.004:
        o.location.z -= gap + 0.01
        seated += 1
log["changed"].append("%d bottom-course wall stones lowered onto the terrain (they floated up to a few cm)" % seated)

# ------------------------------------------------------------------ fence
n_f = 0
for o in bpy.data.objects:
    base = o.name.split(".")[0]
    if base in ("post", "fpost", "rail", "frail"):
        o.material_slots[0].link = "OBJECT"
        o.material_slots[0].material = mat_post if "post" in base else mat_rail
        bv = o.modifiers.new("Bevel", "BEVEL"); bv.width = 0.012; bv.segments = 2; bv.limit_method = "ANGLE"
        n_f += 1
log["changed"].append("%d fence posts and rails: 12 mm bevels, weathered wood with grain along each piece" % n_f)

# ------------------------------------------------------------------ moon
moon = bpy.data.materials["moon"]
nt, out = reset_mat(moon); g = SG(nt)
ob = g.coords("Object")
big = g.noise(ob, 0.75, 2.5, 0.5)                        # broad dark maria
craters = g.noise(ob, 7.0, 3.0, 0.5)                     # faint small-scale texture
maria = g.ramp(g.add(g.mul(big, 0.85), g.mul(craters, 0.15)), [(0.42, (0.42, 0.43, 0.46)), (0.56, (1.0, 0.99, 0.95))])
facing = g.node("ShaderNodeLayerWeight").outputs["Facing"]
em = g.node("ShaderNodeEmission")
g.put(em.inputs["Color"], g.tint(maria, g.maprange(facing, 0.0, 1.0, 1.0, 0.7)))
em.inputs["Strength"].default_value = 3.6
g.l.new(em.outputs[0], out.inputs["Surface"])
log["changed"].append("moon: emission 7 -> 3.6 with broad darker maria and limb darkening, so the disc shows surface detail")

# exposure: +0.25 EV to give back the shadow detail the lower fill took away; the lamp/facade
# ratio set above is unchanged, so the lit window still leads
log["changed"].append("view exposure: %.2f -> 0.85" % scene.view_settings.exposure)
scene.view_settings.exposure = 0.85

bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True)
with open(REPORT, "w") as fh:
    json.dump({"windows": windows, "log": log}, fh, indent=1)
print(json.dumps(log, indent=1))
print("saved", OUT_BLEND)
