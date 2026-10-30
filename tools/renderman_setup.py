"""Give the haunted village RenderMan materials built from the baked textures (run on the RenderMan machine).

Requirements: Blender 5.x with RenderMan for Blender 27.x enabled (RenderMan installed and licensed).

    1. Open renders/haunted_village_v5.blend (keep renders/textures_rman next to it).
    2. Scripting workspace > Open > tools/renderman_setup.py > Run Script
       (or headless: blender -b renders/haunted_village_v5.blend --python tools/renderman_setup.py)
    3. Save the file, then render with RenderMan.

For every material in textures_rman/manifest.json this adds a RenderMan node tree (RendermanOutputNode +
PxrSurface / PxrMeshLight / PxrVolume, fed by PxrTexture, PxrNormalMap, PxrBump, PxrPrimvar) beside the
existing Cycles nodes, so the same file still renders in Cycles. The PNG maps are handed to RenderMan's
texture manager, which converts them to mipmapped .tex files in the background (first render may wait for it).

This could not be run where it was written (no RenderMan there). Node and parameter names come from the
RenderMan for Blender 27.3 source and RenderMan's shader documentation; anything your install does not
recognise is listed at the end and in renderman_setup_log.txt instead of failing silently. Running it again
replaces the RenderMan nodes it made before.
"""
import bpy, json, os, sys, importlib

FLIP_NORMAL_Y = False     # set True if bumps read inverted (normal maps are baked OpenGL-style, +Y up)
SET_RENDER_ENGINE = True  # switch the scene to RenderMan when done

warnings, built = [], []


def warn(msg):
    warnings.append(msg)
    print("[renderman_setup] WARNING:", msg)


# ------------------------------------------------------------------ locate RenderMan for Blender
def find_rfb_package():
    for name in list(sys.modules):
        if name.endswith(".rman_bl_nodes"):
            return name[: -len(".rman_bl_nodes")]
    import addon_utils
    for mod in addon_utils.modules():
        if "renderman" in mod.__name__.lower():
            addon_utils.enable(mod.__name__, default_set=True)
            return mod.__name__
    raise RuntimeError("RenderMan for Blender is not enabled. Enable it in Preferences > Add-ons and run this again.")


PKG = find_rfb_package()
texture_utils = importlib.import_module(PKG + ".rfb_utils.texture_utils")
BLEND_DIR = bpy.path.abspath("//")
# a manifest named after the open .blend (e.g. manifest_haunted_village_v6.json) wins over the shared one
_specific = os.path.join(BLEND_DIR, "textures_rman", "manifest_%s.json" % os.path.splitext(os.path.basename(bpy.data.filepath))[0])
manifest_path = _specific if os.path.exists(_specific) else os.path.join(BLEND_DIR, "textures_rman", "manifest.json")
with open(manifest_path) as fh:
    MANIFEST = json.load(fh)


# ------------------------------------------------------------------ node helpers
def new(nt, name, kind):
    """kind: 'Bxdf' | 'Pattern' | 'Light' -> e.g. PxrSurfaceBxdfNode."""
    try:
        n = nt.nodes.new("%s%sNode" % (name, kind))
        n["rman_setup"] = True
        return n
    except RuntimeError:
        warn("node type %s%sNode is not available in this RenderMan install" % (name, kind))
        return None


def setp(node, name, value):
    if node is None:
        return False
    if not hasattr(node, name):
        warn("%s has no parameter '%s'" % (node.bl_idname, name))
        return False
    try:
        setattr(node, name, value)
        return True
    except Exception as e:  # wrong type or enum
        warn("could not set %s.%s = %r (%s)" % (node.bl_idname, name, value, e))
        return False


def link(a, out, b, inp):
    if a is None or b is None:
        return False
    so = a.outputs.get(out) if isinstance(out, str) else a.outputs[out]
    si = b.inputs.get(inp)
    if so is None or si is None:
        warn("cannot link %s.%s -> %s.%s (socket missing)" % (a.bl_idname, out, b.bl_idname, inp))
        return False
    a.id_data.links.new(so, si)
    return True


def texture(nt, rel_path, srgb):
    t = new(nt, "PxrTexture", "Pattern")
    path = os.path.normpath(os.path.join(BLEND_DIR, rel_path))
    if not os.path.exists(path):
        warn("missing texture %s" % path)
    setp(t, "filename", path)
    setp(t, "linearize", 1 if srgb else 0)
    return t


def reset_rman_nodes(m):
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.get("rman_setup") or n.bl_idname == "RendermanOutputNode":
            nt.nodes.remove(n)
    out = nt.nodes.new("RendermanOutputNode")
    out["rman_setup"] = True
    out.location = (400, -600)
    return nt, out


def f0(ior):
    return ((ior - 1.0) / (ior + 1.0)) ** 2


# ------------------------------------------------------------------ material builders
def build_surface(m, e):
    nt, out = reset_rman_nodes(m)
    c, maps = e.get("constants", {}), e.get("maps", {})
    bx = new(nt, "PxrSurface", "Bxdf")
    link(bx, "bxdf_out", out, "bxdf_in")
    setp(bx, "enableDiffuse", True); setp(bx, "diffuseGain", 1.0)
    setp(bx, "enablePrimarySpecular", True)
    metal = float(c.get("metallic", 0.0)) > 0.5
    if "baseColor" in maps:
        tex = texture(nt, maps["baseColor"], True)
        link(tex, "resultRGB", bx, "diffuseColor")
        if metal:
            link(tex, "resultRGB", bx, "specularFaceColor")
    else:
        col = tuple(c.get("baseColor", [0.5, 0.5, 0.5]))[:3]
        setp(bx, "diffuseColor", col)
        if metal:
            setp(bx, "specularFaceColor", col)
    if metal:
        setp(bx, "diffuseGain", 0.0)
    else:
        s = f0(float(c.get("ior", 1.5)))
        setp(bx, "specularFaceColor", (s, s, s))
    setp(bx, "specularEdgeColor", (1.0, 1.0, 1.0))
    if "roughness" in maps:
        link(texture(nt, maps["roughness"], False), "resultR", bx, "specularRoughness")
    else:
        setp(bx, "specularRoughness", float(c.get("roughness", 0.5)))
    normal_src = None
    if "normal" in maps:
        nm = new(nt, "PxrNormalMap", "Pattern")
        link(texture(nt, maps["normal"], False), "resultRGB", nm, "inputRGB")
        setp(nm, "bumpScale", 1.0)
        if FLIP_NORMAL_Y:
            setp(nm, "flipY", 1)
        normal_src = (nm, "resultN")
    d = e.get("detail")
    if d:   # terrain: tiled micro-height on top of the baked normal map
        mf = new(nt, "PxrManifold2D", "Pattern")
        setp(mf, "scaleS", float(d["repeat"])); setp(mf, "scaleT", float(d["repeat"]))
        dt = texture(nt, d["height"], False)
        link(mf, "result", dt, "manifold")
        bp = new(nt, "PxrBump", "Pattern")
        link(dt, "resultR", bp, "inputBump")
        setp(bp, "scale", float(d["distance"]) * float(d["bumpScale"]))
        if normal_src:
            link(normal_src[0], normal_src[1], bp, "inputN")
        normal_src = (bp, "resultN")
    if normal_src:
        link(normal_src[0], normal_src[1], bx, "bumpNormal")
    t = float(e.get("translucency", 0.0))
    if t > 0:   # thin translucent sheets: curtains, leaves, grass
        setp(bx, "diffuseDoubleSided", 1)
        setp(bx, "diffuseTransmitGain", t)
        if "baseColor" in maps:
            link(texture(nt, maps["baseColor"], True), "resultRGB", bx, "diffuseTransmitColor")
    return out


def build_vertex_color(m, e):
    nt, out = reset_rman_nodes(m)
    bx = new(nt, "PxrSurface", "Bxdf")
    link(bx, "bxdf_out", out, "bxdf_in")
    setp(bx, "enableDiffuse", True); setp(bx, "enablePrimarySpecular", True)
    pv = new(nt, "PxrPrimvar", "Pattern")
    setp(pv, "varname", e.get("primvar", "Cs")); setp(pv, "type", "color")
    link(pv, "resultRGB", bx, "diffuseColor")
    setp(bx, "specularFaceColor", (0.04, 0.04, 0.04)); setp(bx, "specularEdgeColor", (1.0, 1.0, 1.0))
    setp(bx, "specularRoughness", float(e["constants"].get("roughness", 0.7)))
    t = float(e.get("translucency", 0.0))
    if t > 0:
        setp(bx, "diffuseDoubleSided", 1); setp(bx, "diffuseTransmitGain", t)
        link(pv, "resultRGB", bx, "diffuseTransmitColor")
    return out


def build_glass(m, e):
    nt, out = reset_rman_nodes(m)
    c, maps = e["constants"], e["maps"]
    bx = new(nt, "PxrSurface", "Bxdf")
    link(bx, "bxdf_out", out, "bxdf_in")
    setp(bx, "enableGlass", True)
    setp(bx, "refractionGain", 1.0); setp(bx, "reflectionGain", 1.0)
    setp(bx, "glassIor", float(c["ior"])); setp(bx, "thinGlass", 1 if c.get("thin") else 0)
    setp(bx, "refractionColor", tuple(c["transmitColor"]))
    if "roughness" in maps:
        link(texture(nt, maps["roughness"], False), "resultR", bx, "glassRoughness")
    if "grime" in maps:    # dirt film toward the frames: a diffuse layer driven by the grime mask
        setp(bx, "enableDiffuse", True)
        setp(bx, "diffuseColor", tuple(c["dirtColor"]))
        link(texture(nt, maps["grime"], False), "resultR", bx, "diffuseGain")
    return out


def build_emissive(m, e, constant=False):
    nt, out = reset_rman_nodes(m)
    c = e.get("constants", {})
    lt = new(nt, "PxrMeshLight", "Light")
    link(lt, 0, out, "light_in")
    if constant:
        setp(lt, "intensity", float(c.get("intensity", c.get("emissionStrength", 1.0))))
        setp(lt, "lightColor", tuple(c.get("emission", [1, 1, 1]))[:3])
    else:
        setp(lt, "intensity", float(c.get("intensity", 1.0)))
        link(texture(nt, e["maps"]["emission"], True), "resultRGB", lt, "textureColor")
    bk = new(nt, "PxrBlack", "Bxdf")
    link(bk, 0, out, "bxdf_in")
    return out


def build_volume(m, density, color):
    nt, out = reset_rman_nodes(m)
    v = new(nt, "PxrVolume", "Bxdf")
    link(v, 0, out, "bxdf_in")
    setp(v, "densityFloat", float(density))
    setp(v, "diffuseColor", tuple(color))
    return out


def hide_in_renderman(ob):
    rm = ob.renderman
    for p in ("rman_visibilityCamera", "rman_visibilityIndirect", "rman_visibilityTransmission"):
        if hasattr(rm, p):
            setattr(rm, p, "0")
        else:
            warn("object property renderman.%s not found; %s may still render" % (p, ob.name))


# ------------------------------------------------------------------ run
for name, e in MANIFEST["materials"].items():
    m = bpy.data.materials.get(name)
    if m is None:
        warn("material %s from the manifest is not in this file" % name)
        continue
    kind = e["kind"]
    if kind == "surface":
        build_surface(m, e)
    elif kind == "vertex_color":
        build_vertex_color(m, e)
    elif kind == "glass":
        build_glass(m, e)
    elif kind == "emissive":
        build_emissive(m, e)
    elif kind == "emissive_constant":
        build_emissive(m, e, constant=True)
    elif kind == "skip":
        for ob in bpy.data.objects:
            if any(s.material == m for s in ob.material_slots):
                hide_in_renderman(ob)
        continue
    else:
        warn("unknown manifest kind %s for %s" % (kind, name))
        continue
    built.append(name)
    try:
        texture_utils.get_textures(m)      # register every PxrTexture filename with the texture manager
    except Exception as ex:
        warn("texture manager registration failed for %s (%s); RenderMan converts textures on first render instead" % (name, ex))

# volumes: the mist box becomes a RenderMan box volume; the smoke plume is hidden (a box would read wrong);
# the Cycles world fog becomes a large volume box that Cycles does not see
vols = MANIFEST.get("volumes", {})
mist = vols.get("mist")
if mist and mist["object"] in bpy.data.objects:
    ob = bpy.data.objects[mist["object"]]
    ob.renderman.primitive = "RI_VOLUME"
    build_volume(ob.material_slots[0].material, mist["density"], mist["color"])
    built.append("mist (RI_VOLUME box)")
smoke = vols.get("smoke")
if smoke and smoke["object"] in bpy.data.objects:
    hide_in_renderman(bpy.data.objects[smoke["object"]])
world = vols.get("world")
if world:
    atm = bpy.data.objects.get("rman_atmosphere")
    if atm is None:
        me = bpy.data.meshes.new("rman_atmosphere")
        import bmesh
        bm = bmesh.new(); bmesh.ops.create_cube(bm, size=2.0); bm.to_mesh(me); bm.free()
        atm = bpy.data.objects.new("rman_atmosphere", me)
        bpy.context.scene.collection.objects.link(atm)
    atm.location = (0.0, 40.0, 25.0); atm.scale = (160.0, 160.0, 25.0)
    for p in ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter", "visible_shadow"):
        setattr(atm, p, False)                  # Cycles keeps using its own world volume
    am = bpy.data.materials.get("rman_atmosphere") or bpy.data.materials.new("rman_atmosphere")
    am.use_nodes = True
    atm.data.materials.clear(); atm.data.materials.append(am)
    atm.renderman.primitive = "RI_VOLUME"
    build_volume(am, world["density"], world["color"])
    built.append("atmosphere (RI_VOLUME box)")

if SET_RENDER_ENGINE:
    bpy.context.scene.render.engine = "PRMAN_RENDER"

lights = ", ".join("%s %s %.0f W" % (l["name"], l["type"], l["energy"]) for l in MANIFEST.get("lights", []))
summary = [
    "RenderMan node trees built for %d materials/volumes." % len(built),
    "Lights are left as Blender lights; RenderMan for Blender translates them itself (point/area: intensity = watts,"
    " sun: intensity 1). Expect to rebalance exposure or light intensities after the first RenderMan render: " + lights,
]
summary += MANIFEST.get("notes", [])
summary += ["%d warnings:" % len(warnings)] + ["  - " + w for w in warnings]
with open(os.path.join(BLEND_DIR, "renderman_setup_log.txt"), "w") as fh:
    fh.write("\n".join(summary) + "\n")
print("\n".join(summary))
