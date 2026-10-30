"""Bake the haunted village's procedural materials into image maps (v4 -> v5).

RenderMan cannot evaluate Blender's procedural shader nodes: RenderMan for Blender falls back to a
flat viewport colour for any material without a RenderMan node tree, and its Cycles converter only
understands image textures, bump/normal maps, ramps and math. So every procedural material is baked
here to UV image maps (base colour, roughness, tangent normal; emission, glass grime and vertex
colours where needed), each material is rebuilt as an image-driven Principled BSDF (so the result can
be checked in Cycles against v4), and a manifest records how each material maps onto RenderMan nodes.
`renderman_setup.py` reads that manifest inside Blender with RenderMan for Blender installed.

Usage: python3 bake_rman_textures.py <in.blend> <out.blend> <texture_dir> <manifest.json> <stage>
  stage 1: atlas groups (unique meshes, packed UVs), from v4; saves an intermediate .blend
  stage 2: shared-mesh groups, glass, leaves, vertex colours, emitters, terrain, constants; saves v5
The final v5 .blend is expected next to <texture_dir> (manifest paths are relative to that folder).
"""
import bpy, math, os, sys, json, time
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ground_maps as gm

IN_BLEND, OUT_BLEND, TEX_DIR, MANIFEST, STAGE = sys.argv[1:6]
os.makedirs(TEX_DIR, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=IN_BLEND)
scene = bpy.context.scene
vl = bpy.context.view_layer
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
render_samples = scene.cycles.samples
scene.cycles.samples = 1
scene.render.bake.margin = 4
scene.render.bake.margin_type = "EXTEND"
# Bakes run in a scene that holds only the objects being baked: in the full scene every bake call
# re-syncs the GN terrain, ~11k instances, weeds and volumes (a 256^2 test took 113 s there vs 0.4 s isolated).
BAKE_SCENE = bpy.data.scenes.new("rman_bake")
BAKE_SCENE.render.engine = "CYCLES"; BAKE_SCENE.cycles.device = "CPU"; BAKE_SCENE.cycles.samples = 1
BAKE_SCENE.render.bake.margin = 4; BAKE_SCENE.render.bake.margin_type = "EXTEND"
BAKE_VL = BAKE_SCENE.view_layers[0]
assets_lc = vl.layer_collection.children.get("GroundAssets")
if assets_lc:
    assets_lc.exclude = False           # assets must be in the view layer to be selected and baked

manifest = {"textures_dir": os.path.basename(TEX_DIR.rstrip("/")), "materials": {}, "volumes": {}, "lights": [], "notes": []}
if STAGE == "2" and os.path.exists(MANIFEST):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
t_start = time.time()


# ------------------------------------------------------------------ helpers
def mat(name):
    return bpy.data.materials[name]


def objs_with(m, prefix=None):
    out = []
    for o in scene.objects:
        if o.type == "MESH" and any(s.material == m for s in o.material_slots):
            if prefix is None or o.name.startswith(prefix):
                out.append(o)
    return out


def output_node(m):
    return next(n for n in m.node_tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output)


def surface_principled(m):
    out = output_node(m)
    if not out.inputs["Surface"].is_linked:
        return None
    todo = [out.inputs["Surface"].links[0].from_node]
    while todo:
        n = todo.pop(0)
        if n.bl_idname == "ShaderNodeBsdfPrincipled":
            return n
        if n.bl_idname in ("ShaderNodeMixShader", "ShaderNodeAddShader"):
            todo += [s.links[0].from_node for s in n.inputs if s.type == "SHADER" and s.is_linked]
    return None


def src(sock):
    return sock.links[0].from_socket if sock.is_linked else None


def value_of(sock):
    s = src(sock)
    if s is not None:
        return s
    v = sock.default_value
    return tuple(v) if hasattr(v, "__len__") else float(v)


def as_rgba(v):
    if isinstance(v, tuple):
        return v if len(v) == 4 else v + (1.0,)
    return (v, v, v, 1.0)


def select_only(objs):
    for o in scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    vl.objects.active = objs[0]


def make_unique(objs):
    for o in objs:
        if o.data.users > 1:
            o.data = o.data.copy()


def unwrap(objs, margin=0.003, smart=True):
    select_only(objs)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    if smart:
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin)
    bpy.ops.uv.pack_islands(margin=margin, rotate=True, shape_method="AABB")
    bpy.ops.object.mode_set(mode="OBJECT")


BAKE_NODE, EMIT_NODE = "__rman_bake__", "__rman_emit__"


def set_bake_image(materials, img):
    for m in materials:
        nt = m.node_tree
        n = nt.nodes.get(BAKE_NODE) or nt.nodes.new("ShaderNodeTexImage")
        n.name = BAKE_NODE
        n.image = img
        nt.nodes.active = n


def bake(objs, materials, w, h, btype, getter=None, target="IMAGE_TEXTURES"):
    """Bake into a new float image. With getter, each material's surface is temporarily replaced by an
    Emission shader fed from getter(material) (a socket or a constant), so any value bakes exactly."""
    img = bpy.data.images.new("bake_%s_%dx%d" % (btype, w, h), w, h, float_buffer=True, alpha=False) if target == "IMAGE_TEXTURES" else None
    if img is not None:
        set_bake_image(materials, img)
    saved = []
    if getter is not None:
        for m in materials:
            nt = m.node_tree
            out = output_node(m)
            old = src(out.inputs["Surface"])
            em = nt.nodes.new("ShaderNodeEmission"); em.name = EMIT_NODE
            em.inputs["Strength"].default_value = 1.0
            v = getter(m)
            if isinstance(v, bpy.types.NodeSocket):
                nt.links.new(v, em.inputs["Color"])
            else:
                em.inputs["Color"].default_value = as_rgba(v)
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            saved.append((m, old, em))
    for o in objs:
        BAKE_SCENE.collection.objects.link(o)
    for o in BAKE_SCENE.objects:
        o.select_set(o in objs, view_layer=BAKE_VL)
    BAKE_VL.objects.active = objs[0]
    with bpy.context.temp_override(scene=BAKE_SCENE, view_layer=BAKE_VL, active_object=objs[0], object=objs[0],
                                   selected_objects=objs, selected_editable_objects=objs):
        bpy.ops.object.bake(type="EMIT" if getter is not None else btype, use_clear=True, target=target)
    for o in objs:
        BAKE_SCENE.collection.objects.unlink(o)
    for m, old, em in saved:
        nt = m.node_tree
        nt.nodes.remove(em)
        if old is not None:
            nt.links.new(old, output_node(m).inputs["Surface"])
    return img


def to_srgb(rgb):
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, 12.92 * rgb, 1.055 * np.power(rgb, 1 / 2.4) - 0.055)


def save(img, name, mode):
    """mode: 'srgb' colour (8-bit sRGB), 'gray' scalar (8-bit), 'normal' tangent normal (8-bit)."""
    w, h = img.size
    buf = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(buf)
    rgb = buf.reshape(h, w, 4)[..., :3]
    path = os.path.join(TEX_DIR, name + ".png")
    if mode == "gray":
        Image.fromarray(np.flipud((np.clip(rgb[..., 0], 0, 1) * 255 + 0.5).astype(np.uint8)), "L").save(path, optimize=True)
    else:
        rgb = to_srgb(rgb) if mode == "srgb" else np.clip(rgb, 0, 1)
        Image.fromarray(np.flipud((rgb * 255 + 0.5).astype(np.uint8)), "RGB").save(path, optimize=True)
    bpy.data.images.remove(img)
    return path


def rel(path):
    # relative to the folder that holds the final v5 .blend (the parent of the texture folder)
    return os.path.relpath(path, os.path.dirname(os.path.abspath(TEX_DIR.rstrip("/")))).replace(os.sep, "/")


def load(path, colorspace):
    img = bpy.data.images.load(path, check_existing=True)
    img.colorspace_settings.name = colorspace
    return img


def bake_standard(name, objs, materials, size, translucency=None, extra_maps=None):
    """Bake base colour / roughness / normal for materials sharing one atlas; rebuild each material."""
    w, h = size if isinstance(size, tuple) else (size, size)
    t0 = time.time()
    p_of = {m.name: surface_principled(m) for m in materials}
    maps = {"baseColor": save(bake(objs, materials, w, h, "EMIT", lambda m: value_of(p_of[m.name].inputs["Base Color"])), name + "_basecolor", "srgb")}
    if any(p_of[m.name].inputs["Roughness"].is_linked for m in materials):
        maps["roughness"] = save(bake(objs, materials, w, h, "EMIT", lambda m: value_of(p_of[m.name].inputs["Roughness"])), name + "_roughness", "gray")
    if any(p_of[m.name].inputs["Normal"].is_linked for m in materials):
        maps["normal"] = save(bake(objs, materials, w, h, "NORMAL"), name + "_normal", "normal")
    for k, (getter, mode) in (extra_maps or {}).items():
        maps[k] = save(bake(objs, materials, w, h, "EMIT", getter), name + "_" + k, mode)
    for m in materials:
        p = p_of[m.name]
        consts = {"roughness": float(p.inputs["Roughness"].default_value), "ior": float(p.inputs["IOR"].default_value),
                  "metallic": float(p.inputs["Metallic"].default_value)}
        rebuild(m, maps, consts, translucency.get(m.name, 0.0) if translucency else 0.0)
        manifest["materials"][m.name] = {"kind": "surface", "maps": {k: rel(v) for k, v in maps.items()}, "constants": consts,
                                         "translucency": translucency.get(m.name, 0.0) if translucency else 0.0}
    print("baked %-20s %-5s objs=%-4d %5.1fs" % (name, "%dx%d" % (w, h), len(objs), time.time() - t0), flush=True)
    return maps


def rebuild(m, maps, consts, translucency=0.0):
    nt = m.node_tree
    out = output_node(m)
    for n in list(nt.nodes):
        if n != out:
            nt.nodes.remove(n)
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = load(maps["baseColor"], "sRGB")
    nt.links.new(tex.outputs["Color"], p.inputs["Base Color"])
    if "roughness" in maps:
        r = nt.nodes.new("ShaderNodeTexImage"); r.image = load(maps["roughness"], "Non-Color")
        nt.links.new(r.outputs["Color"], p.inputs["Roughness"])
    else:
        p.inputs["Roughness"].default_value = consts["roughness"]
    if "normal" in maps:
        nn = nt.nodes.new("ShaderNodeTexImage"); nn.image = load(maps["normal"], "Non-Color")
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nn.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    p.inputs["IOR"].default_value = consts["ior"]
    p.inputs["Metallic"].default_value = consts["metallic"]
    shader = p.outputs[0]
    if translucency > 0:
        tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
        nt.links.new(tex.outputs["Color"], tr.inputs["Color"])
        mx = nt.nodes.new("ShaderNodeMixShader"); mx.inputs[0].default_value = translucency
        nt.links.new(shader, mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); shader = mx.outputs[0]
    nt.links.new(shader, out.inputs["Surface"])
    return p


def translucency_of(m):
    out = output_node(m)
    n = out.inputs["Surface"].links[0].from_node
    if n.bl_idname == "ShaderNodeMixShader" and n.inputs[2].is_linked and n.inputs[2].links[0].from_node.bl_idname == "ShaderNodeBsdfTranslucent":
        return float(n.inputs[0].default_value)
    return 0.0


def constant_entry(m, kind="surface"):
    p = surface_principled(m)
    if p is None:
        return
    def c(sock):
        v = sock.default_value
        return list(v)[:3] if hasattr(v, "__len__") else float(v)
    manifest["materials"][m.name] = {"kind": kind, "maps": {}, "constants": {
        "baseColor": c(p.inputs["Base Color"]), "roughness": c(p.inputs["Roughness"]), "ior": c(p.inputs["IOR"]),
        "metallic": c(p.inputs["Metallic"]), "emission": c(p.inputs["Emission Color"]), "emissionStrength": c(p.inputs["Emission Strength"])}}


def finish():
    """Restore the scene's settings, save the .blend and the manifest, and stop."""
    if assets_lc:
        assets_lc.exclude = True
    bpy.data.scenes.remove(BAKE_SCENE)
    scene.cycles.samples = render_samples
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True, relative_remap=True)
    manifest.setdefault("bake_seconds", {})["stage_" + STAGE] = round(time.time() - t_start, 1)
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("stage", STAGE, "saved", OUT_BLEND, "in %.0fs" % (time.time() - t_start), flush=True)
    sys.exit(0)


# ------------------------------------------------------------------ 1. atlas groups (unique meshes, packed UVs)
ATLAS = [  # material(s), object filter, size
    (["siding_weathered"], None, 2048),
    (["fieldstone"], None, 2048),
    (["roof", "gable_boards", "soffit_wood"], None, 2048),
    (["fence_post_wood", "fence_rail_wood"], None, 2048),
    (["trim"], None, 1024),
    (["plinth_stone"], None, 512),
    (["stave"], None, 512),
    (["shrub"], None, 512),
    (["curtain_warm"], None, 512),
    (["curtain_pale"], None, 512),
    (["pebble"], None, 256),
    (["twig_bark"], None, 256),
]
for names, _, size in (ATLAS if STAGE == "1" else []):
    materials = [mat(n) for n in names]
    objs = sorted({o for m in materials for o in objs_with(m)}, key=lambda o: o.name)
    make_unique(objs)
    unwrap(objs)
    trans = {m.name: translucency_of(m) for m in materials}
    if names == ["pebble"]:           # instance colour comes from the instancer; vary it per pebble mesh instead
        m = materials[0]
        for n in m.node_tree.nodes:
            if n.bl_idname == "ShaderNodeAttribute" and n.attribute_type == "INSTANCER":
                oi = m.node_tree.nodes.new("ShaderNodeObjectInfo")
                for l in list(n.outputs["Fac"].links):
                    m.node_tree.links.new(oi.outputs["Random"], l.to_socket)
    bake_standard("_".join(names[:1]), objs, materials, size, translucency=trans)

if STAGE == "1":
    finish()

# ------------------------------------------------------------------ 2. shared-mesh groups: one representative bake
REP = [("wood", "house2", 1024), ("wood_lit", "lh", 512), ("brick", "chimney", 512), ("stone", "chimcap", 256),
       ("dark_wood", "beam_up", 512), ("door_wood", "door", 512), ("painting_canvas", "picture", 256)]
if STAGE == "1":
    REP = []
cube_mesh = bpy.data.meshes.get("unit_cube")
for name, rep, size in REP:
    m = mat(name)
    o = next(o for o in objs_with(m) if o.name.startswith(rep))
    if o.data.uv_layers.active is None or o.data == cube_mesh:
        unwrap([o])                       # the shared unit cube had no UVs; this unwraps it for every user
    bake_standard(name, [o], [m], size)

# glass: roughness and an edge-grime mask on the shared pane mesh
g = mat("window_glass")
pane = next(o for o in objs_with(g))
unwrap([pane])
mix = output_node(g).inputs["Surface"].links[0].from_node
glass_p = mix.inputs[1].links[0].from_node
gmaps = {"roughness": save(bake([pane], [g], 512, 512, "EMIT", lambda m: value_of(glass_p.inputs["Roughness"])), "window_glass_roughness", "gray"),
         "grime": save(bake([pane], [g], 512, 512, "EMIT", lambda m: value_of(mix.inputs[0])), "window_glass_grime", "gray")}
nt = g.node_tree
r = nt.nodes.new("ShaderNodeTexImage"); r.image = load(gmaps["roughness"], "Non-Color")
nt.links.new(r.outputs["Color"], glass_p.inputs["Roughness"])
gr = nt.nodes.new("ShaderNodeTexImage"); gr.image = load(gmaps["grime"], "Non-Color")
nt.links.new(gr.outputs["Color"], mix.inputs[0])
manifest["materials"]["window_glass"] = {"kind": "glass", "maps": {k: rel(v) for k, v in gmaps.items()},
                                         "constants": {"ior": 1.52, "thin": True, "transmitColor": [0.9, 0.95, 0.92], "dirtColor": [0.11, 0.1, 0.085], "grimeScale": 1.0}}
print("baked window_glass")

# ------------------------------------------------------------------ 3. leaves: one material copy and texture per leaf shape
leaf_m = mat("leaf_litter")
leaves = sorted(objs_with(leaf_m), key=lambda o: o.name)
for i, o in enumerate(leaves):
    m = leaf_m.copy(); m.name = "leaf_litter_%d" % i
    o.data.materials[0] = m
    for n in m.node_tree.nodes:      # leaf_rand / leaf_damp come from the instancer; fix one variant per shape
        if n.bl_idname == "ShaderNodeAttribute" and n.attribute_type == "INSTANCER":
            v = m.node_tree.nodes.new("ShaderNodeValue")
            v.outputs[0].default_value = (i + 0.5) / len(leaves) if n.attribute_name == "leaf_rand" else 0.15
            for l in list(n.outputs["Fac"].links):
                m.node_tree.links.new(v.outputs[0], l.to_socket)
    bake_standard("leaf_%d" % i, [o], [m], 256, translucency={m.name: translucency_of(m)})
manifest["notes"].append("Leaves: one colour variant per leaf shape (6); the per-instance damp darkening near water is not carried over.")

# ------------------------------------------------------------------ 4. vertex colours: grass tufts and weeds (thin geometry)
for name in ("dry_grass", "weed"):
    m = mat(name)
    objs = objs_with(m)
    trans = translucency_of(m)
    for n in m.node_tree.nodes:
        if n.bl_idname == "ShaderNodeAttribute" and n.attribute_type == "INSTANCER":
            oi = m.node_tree.nodes.new("ShaderNodeObjectInfo")
            for l in list(n.outputs["Fac"].links):
                m.node_tree.links.new(oi.outputs["Random"], l.to_socket)
    for o in objs:
        ca = o.data.color_attributes.get("bake_col") or o.data.color_attributes.new("bake_col", "FLOAT_COLOR", "POINT")
        o.data.color_attributes.active_color = ca
        o.data.color_attributes.render_color_index = list(o.data.color_attributes).index(ca)
    p = surface_principled(m)
    rough = float(p.inputs["Roughness"].default_value)
    bake(objs, [m], 0, 0, "EMIT", lambda mm: value_of(surface_principled(mm).inputs["Base Color"]), target="VERTEX_COLORS")
    nt = m.node_tree; out = output_node(m)
    for n in list(nt.nodes):
        if n != out:
            nt.nodes.remove(n)
    a = nt.nodes.new("ShaderNodeAttribute"); a.attribute_type = "GEOMETRY"; a.attribute_name = "bake_col"
    pb = nt.nodes.new("ShaderNodeBsdfPrincipled"); pb.inputs["Roughness"].default_value = rough
    nt.links.new(a.outputs["Color"], pb.inputs["Base Color"])
    shader = pb.outputs[0]
    if trans > 0:
        tr = nt.nodes.new("ShaderNodeBsdfTranslucent"); nt.links.new(a.outputs["Color"], tr.inputs["Color"])
        mx = nt.nodes.new("ShaderNodeMixShader"); mx.inputs[0].default_value = trans
        nt.links.new(shader, mx.inputs[1]); nt.links.new(tr.outputs[0], mx.inputs[2]); shader = mx.outputs[0]
    nt.links.new(shader, out.inputs["Surface"])
    manifest["materials"][name] = {"kind": "vertex_color", "primvar": "Cs", "constants": {"roughness": rough}, "translucency": trans}
    print("baked %s to vertex colours on %d meshes" % (name, len(objs)))

# ------------------------------------------------------------------ 5. emitters: sky dome and moon
for name, size in (("sky", (6144, 3072)), ("moon", (1024, 512))):
    m = mat(name)
    o = objs_with(m)[0]
    em = output_node(m).inputs["Surface"].links[0].from_node
    strength = float(em.inputs["Strength"].default_value)
    path = save(bake([o], [m], size[0], size[1], "EMIT", lambda mm: value_of(em.inputs["Color"])), name + "_emission", "srgb")
    nt = m.node_tree; out = output_node(m)
    for n in list(nt.nodes):
        if n != out:
            nt.nodes.remove(n)
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = load(path, "sRGB")
    e = nt.nodes.new("ShaderNodeEmission"); e.inputs["Strength"].default_value = strength
    nt.links.new(t.outputs["Color"], e.inputs["Color"]); nt.links.new(e.outputs[0], out.inputs["Surface"])
    manifest["materials"][name] = {"kind": "emissive", "maps": {"emission": rel(path)}, "constants": {"intensity": strength}}
    print("baked %s emission" % name)
manifest["notes"].append("Moon limb darkening (view-dependent) is not in the baked map.")

# ------------------------------------------------------------------ 6. terrain: world-planar UVs from the GN modifier, then bake
terr = bpy.data.objects["terrain_gn"]
ng = terr.modifiers["GN_TerrainGround"].node_group
hti = next(n for n in ng.nodes if n.bl_idname == "GeometryNodeImageTexture" and n.inputs["Image"].default_value and n.inputs["Image"].default_value.name.startswith("terrain_height"))
uv_src = hti.inputs["Vector"].links[0].from_socket
smooth = next(n for n in ng.nodes if n.bl_idname == "GeometryNodeSetShadeSmooth")
setmat = next(n for n in ng.nodes if n.bl_idname == "GeometryNodeSetMaterial")
st = ng.nodes.new("GeometryNodeStoreNamedAttribute"); st.data_type = "FLOAT2"; st.domain = "CORNER"
st.inputs["Name"].default_value = "UVMap"
ng.links.new(smooth.outputs[0], st.inputs["Geometry"]); ng.links.new(uv_src, st.inputs["Value"])
ng.links.new(st.outputs[0], setmat.inputs["Geometry"])
if not terr.data.uv_layers:
    terr.data.uv_layers.new(name="UVMap")    # names the active UV map, which RenderMan for Blender looks up on the generated mesh
tm = mat("terrain_mud")
p = surface_principled(tm)
detail_img = next(n.image for n in tm.node_tree.nodes if n.bl_idname == "ShaderNodeTexImage" and n.image and n.image.name.startswith("mud_detail"))
tmaps = {"baseColor": save(bake([terr], [tm], 4096, 4096, "EMIT", lambda m: value_of(p.inputs["Base Color"])), "terrain_basecolor", "srgb"),
         "roughness": save(bake([terr], [tm], 4096, 4096, "EMIT", lambda m: value_of(p.inputs["Roughness"])), "terrain_roughness", "gray"),
         "normal": save(bake([terr], [tm], 4096, 4096, "NORMAL"), "terrain_normal", "normal")}
detail_path = os.path.join(TEX_DIR, "terrain_detail_height.png")
dw, dh = detail_img.size
dbuf = np.empty(dw * dh * 4, np.float32); detail_img.pixels.foreach_get(dbuf)
Image.fromarray(np.flipud((np.clip(dbuf.reshape(dh, dw, 4)[..., 0], 0, 1) * 255 + 0.5).astype(np.uint8)), "L").save(detail_path, optimize=True)
tile_repeat = gm.S / 1.6
pp = rebuild(tm, tmaps, {"roughness": 0.8, "ior": 1.4, "metallic": 0.0})
nt = tm.node_tree
tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (tile_repeat, tile_repeat, 1)
dt = nt.nodes.new("ShaderNodeTexImage"); dt.image = load(detail_path, "Non-Color")
nt.links.new(tc.outputs["UV"], mp.inputs["Vector"]); nt.links.new(mp.outputs[0], dt.inputs["Vector"])
bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Distance"].default_value = 0.012; bp.inputs["Strength"].default_value = 0.8
nt.links.new(dt.outputs["Color"], bp.inputs["Height"])
nm = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeNormalMap")
nt.links.new(nm.outputs["Normal"], bp.inputs["Normal"]); nt.links.new(bp.outputs["Normal"], pp.inputs["Normal"])
manifest["materials"]["terrain_mud"] = {"kind": "surface", "maps": {k: rel(v) for k, v in tmaps.items()},
                                        "detail": {"height": rel(detail_path), "repeat": tile_repeat, "bumpScale": 0.8, "distance": 0.012},
                                        "constants": {"roughness": 0.8, "ior": 1.4, "metallic": 0.0}, "translucency": 0.0}
manifest["notes"].append("Terrain: baked at 4096^2 over the 64 m map (1.6 cm per texel) with the mud micro-height tile repeated %.0fx on top as bump." % tile_repeat)
print("baked terrain")

# ------------------------------------------------------------------ 7. constants, volumes, lights
for name in ("bark", "darkwin", "iron", "soffit_wood", "interior_plaster", "interior_plaster_dim", "floor_boards", "ground", "window2"):
    if name in bpy.data.materials and name not in manifest["materials"]:
        constant_entry(mat(name), "emissive_constant" if name == "window2" else "surface")
manifest["materials"]["window2"]["constants"]["intensity"] = 7.0
manifest["materials"]["puddle_water"] = {"kind": "surface", "maps": {}, "constants": {"baseColor": [0.016, 0.013, 0.01], "roughness": 0.035, "ior": 1.333, "metallic": 0.0}}
manifest["materials"]["halo"] = {"kind": "skip", "reason": "camera-facing glow card; in RenderMan the moon light scattering in the volumes gives the glow"}
manifest["volumes"] = {
    "mist": {"object": "Cube", "density": 0.045, "color": [0.6, 0.7, 0.9], "note": "noise-modulated in Cycles (0-0.09); constant mean density here"},
    "smoke": {"object": "Cone", "density": 1.5, "color": [0.75, 0.8, 0.9], "note": "noise and height falloff in Cycles; constant density here"},
    "world": {"density": 0.0008, "color": [0.55, 0.65, 0.85], "note": "Cycles world volume; add a large PxrVolume box in RenderMan"},
}
for o in scene.objects:
    if o.type == "LIGHT":
        manifest["lights"].append({"name": o.name, "type": o.data.type, "energy": o.data.energy, "color": list(o.data.color),
                                   "radius": getattr(o.data, "shadow_soft_size", 0.0), "size": getattr(o.data, "size", 0.0)})

finish()
