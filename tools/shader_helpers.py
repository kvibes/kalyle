"""Small helpers for building Cycles materials from Python."""
import bpy


def new_mat(name):
    """Empty node material; returns (material, node_tree, output_node)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    return m, nt, nt.nodes["Material Output"]


def reset_mat(m):
    """Clear an existing material's nodes but keep the datablock (and every user of it)."""
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    return nt, nt.nodes["Material Output"]


class SG:
    """Tiny shader-graph builder: numbers become default values, sockets become links."""
    def __init__(self, nt):
        self.nt = nt; self.n = nt.nodes; self.l = nt.links

    def node(self, t, **kw):
        nd = self.n.new(t)
        for k, v in kw.items():
            setattr(nd, k, v)
        return nd

    def put(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.l.new(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.put(nd.inputs[0], a)
        if b is not None:
            self.put(nd.inputs[1], b)
        return nd.outputs[0]

    def mul(self, *vals):
        acc = vals[0]
        for v in vals[1:]:
            acc = self.math("MULTIPLY", acc, v)
        return acc

    def add(self, *vals):
        acc = vals[0]
        for v in vals[1:]:
            acc = self.math("ADD", acc, v)
        return acc

    def mix(self, fac, a, b, kind="RGBA"):
        nd = self.node("ShaderNodeMix", data_type=kind)
        self.put(nd.inputs["Factor"], fac)
        if kind == "RGBA":
            self.put(nd.inputs[6], a); self.put(nd.inputs[7], b)
            return nd.outputs[2]
        self.put(nd.inputs[2], a); self.put(nd.inputs[3], b)
        return nd.outputs[0]

    def tint(self, color, value):
        """Multiply a colour by a scalar factor."""
        nd = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        nd.inputs["Factor"].default_value = 1.0
        self.put(nd.inputs[6], color)
        self.put(nd.inputs[7], self.comb(value, value, value))
        return nd.outputs[2]

    def maprange(self, v, a, b, c, d):
        nd = self.node("ShaderNodeMapRange", clamp=True)
        self.put(nd.inputs["Value"], v)
        for k, x in zip(("From Min", "From Max", "To Min", "To Max"), (a, b, c, d)):
            self.put(nd.inputs[k], x)
        return nd.outputs["Result"]

    def sep(self, v):
        nd = self.node("ShaderNodeSeparateXYZ"); self.put(nd.inputs[0], v)
        return nd.outputs

    def comb(self, x, y, z=0.0):
        nd = self.node("ShaderNodeCombineXYZ")
        self.put(nd.inputs[0], x); self.put(nd.inputs[1], y); self.put(nd.inputs[2], z)
        return nd.outputs[0]

    def mapping(self, vec, scale=(1, 1, 1), loc=(0, 0, 0), rot=(0, 0, 0)):
        nd = self.node("ShaderNodeMapping")
        self.put(nd.inputs["Vector"], vec)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Location"].default_value = loc
        nd.inputs["Rotation"].default_value = rot
        return nd.outputs[0]

    def noise(self, vec, scale, detail=4.0, rough=0.55):
        nd = self.node("ShaderNodeTexNoise")
        self.put(nd.inputs["Vector"], vec)
        self.put(nd.inputs["Scale"], scale)
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        return nd.outputs[0]

    def ramp(self, fac, stops):
        nd = self.node("ShaderNodeValToRGB")
        self.put(nd.inputs["Fac"], fac)
        els = nd.color_ramp.elements
        while len(els) < len(stops):
            els.new(0.5)
        for e, (p, c) in zip(els, stops):
            e.position = p; e.color = (*c, 1.0)
        return nd.outputs["Color"]

    def bump(self, height, strength, distance, normal=None):
        nd = self.node("ShaderNodeBump")
        self.put(nd.inputs["Height"], height)
        self.put(nd.inputs["Strength"], strength)
        nd.inputs["Distance"].default_value = distance
        if normal is not None:
            self.put(nd.inputs["Normal"], normal)
        return nd.outputs["Normal"]

    def coords(self, kind):
        return self.node("ShaderNodeTexCoord").outputs[kind]

    def position(self):
        return self.node("ShaderNodeNewGeometry").outputs["Position"]


def principled(g, out, color, rough, normal=None, translucent=0.0, **inputs):
    """Principled BSDF wired to the output; optional translucency mix for thin materials."""
    b = g.node("ShaderNodeBsdfPrincipled")
    g.put(b.inputs["Base Color"], color)
    g.put(b.inputs["Roughness"], rough)
    if normal is not None:
        g.put(b.inputs["Normal"], normal)
    for k, v in inputs.items():
        g.put(b.inputs[k], v)
    shader = b.outputs[0]
    if translucent > 0:
        tr = g.node("ShaderNodeBsdfTranslucent")
        g.put(tr.inputs["Color"], color)
        if normal is not None:
            g.put(tr.inputs["Normal"], normal)
        mx = g.node("ShaderNodeMixShader")
        mx.inputs[0].default_value = translucent
        g.l.new(shader, mx.inputs[1]); g.l.new(tr.outputs[0], mx.inputs[2])
        shader = mx.outputs[0]
    g.l.new(shader, out.inputs["Surface"])
    return b
