"""Dry-run renderman_setup.py without RenderMan, against stand-in node types.

This checks the script's control flow, its use of the manifest and the v5 file, and that every material
ends up with a wired RenderMan output. It cannot check RenderMan's real parameter names: the stand-ins
accept exactly the names the script uses.

Usage: python3 test_renderman_setup_stub.py <v5.blend>
"""
import bpy, sys, types, os

BLEND = sys.argv[1]
SETUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "renderman_setup.py")

# fake package layout that renderman_setup.find_rfb_package() and its imports expect
for name in ("RenderManForBlender", "RenderManForBlender.rman_bl_nodes", "RenderManForBlender.rfb_utils"):
    mod = types.ModuleType(name); mod.__path__ = []
    sys.modules[name] = mod
registered = []
tu = types.ModuleType("RenderManForBlender.rfb_utils.texture_utils")
tu.get_textures = lambda m, **kw: registered.append(m.name)
sys.modules["RenderManForBlender.rfb_utils.texture_utils"] = tu

P = {"F": bpy.props.FloatProperty, "I": bpy.props.IntProperty, "B": bpy.props.BoolProperty, "S": bpy.props.StringProperty}
C3 = lambda: bpy.props.FloatVectorProperty(size=3)
SOCK = {"sh": "NodeSocketShader", "c": "NodeSocketColor", "f": "NodeSocketFloat", "v": "NodeSocketVector"}
SPEC = {   # bl_idname: (inputs, outputs, params)
    "RendermanOutputNode": ([("bxdf_in", "sh"), ("light_in", "sh"), ("displace_in", "sh")], [], {}),
    "PxrSurfaceBxdfNode": ([("diffuseColor", "c"), ("diffuseTransmitColor", "c"), ("specularFaceColor", "c"), ("specularRoughness", "f"),
                            ("bumpNormal", "v"), ("glassRoughness", "f"), ("diffuseGain", "f")], [("bxdf_out", "sh")],
                           {"enableDiffuse": "B", "diffuseGain": "F", "enablePrimarySpecular": "B", "diffuseColor": "C", "specularFaceColor": "C",
                            "specularEdgeColor": "C", "specularRoughness": "F", "diffuseDoubleSided": "I", "diffuseTransmitGain": "F",
                            "enableGlass": "B", "refractionGain": "F", "reflectionGain": "F", "glassIor": "F", "thinGlass": "I", "refractionColor": "C"}),
    "PxrTexturePatternNode": ([("manifold", "v")], [("resultRGB", "c"), ("resultR", "f")], {"filename": "S", "linearize": "I"}),
    "PxrNormalMapPatternNode": ([("inputRGB", "c")], [("resultN", "v")], {"bumpScale": "F", "flipY": "I"}),
    "PxrManifold2DPatternNode": ([], [("result", "v")], {"scaleS": "F", "scaleT": "F"}),
    "PxrBumpPatternNode": ([("inputBump", "f"), ("inputN", "v")], [("resultN", "v")], {"scale": "F"}),
    "PxrPrimvarPatternNode": ([], [("resultRGB", "c")], {"varname": "S", "type": "S"}),
    "PxrMeshLightLightNode": ([("textureColor", "c")], [("light_out", "sh")], {"intensity": "F", "lightColor": "C"}),
    "PxrBlackBxdfNode": ([], [("bxdf_out", "sh")], {}),
    "PxrVolumeBxdfNode": ([], [("bxdf_out", "sh")], {"densityFloat": "F", "diffuseColor": "C"}),
}


def make(bl_idname, inputs, outputs, params):
    ann = {k: (C3() if t == "C" else P[t]()) for k, t in params.items()}

    def init(self, context):
        for n, t in inputs:
            self.inputs.new(SOCK[t], n)
        for n, t in outputs:
            self.outputs.new(SOCK[t], n)
    cls = type(bl_idname, (bpy.types.Node,), {"bl_idname": bl_idname, "bl_label": bl_idname, "__annotations__": ann,
                                               "init": init, "poll": classmethod(lambda c, nt: True)})
    bpy.utils.register_class(cls)


for k, v in SPEC.items():
    make(k, *v)


class RmObject(bpy.types.PropertyGroup):
    rman_visibilityCamera: bpy.props.StringProperty(default="1")
    rman_visibilityIndirect: bpy.props.StringProperty(default="1")
    rman_visibilityTransmission: bpy.props.StringProperty(default="1")
    primitive: bpy.props.StringProperty(default="AUTO")


bpy.utils.register_class(RmObject)
bpy.types.Object.renderman = bpy.props.PointerProperty(type=RmObject)

bpy.ops.wm.open_mainfile(filepath=BLEND)
src = open(SETUP).read().replace("SET_RENDER_ENGINE = True", "SET_RENDER_ENGINE = False")
ns = {"__name__": "__main__", "__file__": SETUP}
exec(compile(src, SETUP, "exec"), ns)

# verify: each manifest material has an output with something wired into it
problems = []
for name, e in ns["MANIFEST"]["materials"].items():
    m = bpy.data.materials.get(name)
    if m is None or e["kind"] == "skip":
        continue
    outs = [n for n in m.node_tree.nodes if n.bl_idname == "RendermanOutputNode"]
    if len(outs) != 1:
        problems.append("%s: %d RenderMan outputs" % (name, len(outs)))
        continue
    if not any(s.is_linked for s in outs[0].inputs):
        problems.append("%s: output not connected" % name)
    for n in m.node_tree.nodes:
        if n.bl_idname == "PxrTexturePatternNode" and not os.path.exists(n.filename):
            problems.append("%s: texture missing %s" % (name, n.filename))
print("STUB RESULT: materials built=%d, setup warnings=%d, texture registrations=%d, problems=%d"
      % (len(ns["built"]), len(ns["warnings"]), len(registered), len(problems)))
for p in problems + ns["warnings"]:
    print("  -", p)
