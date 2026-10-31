"""Render the passes the ambience video is composited from (linear EXR, same seed, same camera).

  nolamp      full scene without the room lamp (and its outside spill)
  lamp        the room lamp and its spill alone (everything else dark, fog kept)
  nodomecam   as nolamp, but the sky dome is black to camera rays (it still lights the scene, and camera
              rays still stop at it, so the fog in front of the sky is the same as in nolamp)
  nolocalvol  as nolamp, without the street mist and chimney smoke
  skymask     alpha = 1 where something covers the sky dome (cheap, no volumes)

Light adds linearly, so nolamp + f(t) * lamp re-lights the window exactly; nolamp - nodomecam isolates
the visible sky (through the fog), which lets the compositor drift the clouds; nolamp - nolocalvol
isolates the mist and smoke for gentle motion.

Usage: python3 video_passes.py <scene.blend> <out_dir> [width] [samples]
"""
import bpy, os, sys, time

BLEND, OUT = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1920
SPP = int(sys.argv[4]) if len(sys.argv) > 4 else 64
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=BLEND)
sc = bpy.context.scene
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, W * 9 // 16, 100
sc.cycles.samples = SPP
sc.cycles.seed = 7
sc.cycles.use_animated_seed = False
sc.render.image_settings.file_format = "OPEN_EXR"
sc.render.image_settings.color_depth = "16"
sc.render.image_settings.exr_codec = "ZIP"


def mat_obj(name):
    return next(o for o in sc.objects if o.type == "MESH" and o.material_slots and o.material_slots[0].material
                and o.material_slots[0].material.name == name)


dome, moon = mat_obj("sky"), mat_obj("moon")
mist, smoke = bpy.data.objects["Cube"], bpy.data.objects["Cone"]
halo = next((o for o in sc.objects if o.material_slots and o.material_slots[0].material and o.material_slots[0].material.name == "halo"), None)
LAMP = {"room_lamp", "winlight"}
lights = {o.name: o for o in sc.objects if o.type == "LIGHT"}
energy = {n: o.data.energy for n, o in lights.items()}


def emitters(scale):
    """Scale every emissive material: sky dome, moon, halo card, lit village windows."""
    for name in ("sky", "moon"):
        for n in bpy.data.materials[name].node_tree.nodes:
            if n.bl_idname == "ShaderNodeEmission":
                n["base_strength"] = n.get("base_strength", n.inputs["Strength"].default_value)
                n.inputs["Strength"].default_value = n["base_strength"] * scale
    if halo:
        for n in halo.material_slots[0].material.node_tree.nodes:
            if n.bl_idname == "ShaderNodeMath" and n.operation == "MULTIPLY" and n.inputs[0].is_linked and not n.inputs[1].is_linked:
                n["base"] = n.get("base", n.inputs[1].default_value)
                n.inputs[1].default_value = n["base"] * scale
    for n in bpy.data.materials["window2"].node_tree.nodes:
        if n.bl_idname == "ShaderNodeBsdfPrincipled":
            n["base_em"] = n.get("base_em", n.inputs["Emission Strength"].default_value)
            n.inputs["Emission Strength"].default_value = n["base_em"] * scale


sky_nt = bpy.data.materials["sky"].node_tree
sky_em = next(n for n in sky_nt.nodes if n.bl_idname == "ShaderNodeEmission")
lp = sky_nt.nodes.new("ShaderNodeLightPath")
not_cam = sky_nt.nodes.new("ShaderNodeMath"); not_cam.operation = "SUBTRACT"; not_cam.inputs[0].default_value = 1.0
sky_nt.links.new(lp.outputs["Is Camera Ray"], not_cam.inputs[1])
cam_gate = sky_nt.nodes.new("ShaderNodeMath"); cam_gate.operation = "MULTIPLY"


def dome_black_to_camera(on):
    """Hiding the dome would let camera rays run on through the infinite world fog; instead keep it as a
    surface that stops them, but with no emission towards the camera."""
    if on:
        cam_gate.inputs[1].default_value = sky_em.inputs["Strength"].default_value
        sky_nt.links.new(not_cam.outputs[0], cam_gate.inputs[0])
        sky_nt.links.new(cam_gate.outputs[0], sky_em.inputs["Strength"])
    else:
        for l in list(sky_em.inputs["Strength"].links):
            sky_nt.links.remove(l)


def setup(lamp_on, others_on, dome_cam=True, local_vol=True):
    for n, o in lights.items():
        on = lamp_on if n in LAMP else others_on
        o.data.energy = energy[n] if on else 0.0
    emitters(1.0 if others_on else 0.0)
    dome_black_to_camera(not dome_cam)
    mist.hide_render = not local_vol
    smoke.hide_render = not local_vol


def render(name):
    t = time.time()
    sc.render.filepath = os.path.join(OUT, name + ".exr")
    bpy.ops.render.render(write_still=True)
    print("pass %-11s %6.1fs" % (name, time.time() - t), flush=True)


setup(False, True); render("nolamp")
setup(True, False); render("lamp")
setup(False, True, dome_cam=False); render("nodomecam")
setup(False, True, local_vol=False); render("nolocalvol")

# sky coverage: transparent film, dome hidden from the camera, no volumes, flat shading, few samples
setup(False, True, local_vol=False)
dome.visible_camera = False
if halo:
    halo.hide_render = True
world_vol = sc.world.node_tree.nodes["World Output"].inputs["Volume"]
for l in list(world_vol.links):
    sc.world.node_tree.links.remove(l)
sc.render.film_transparent = True
sc.cycles.samples = 16
sc.cycles.use_denoising = False
flat = bpy.data.materials.new("mask_flat")
bpy.context.view_layer.material_override = flat
sc.render.image_settings.color_mode = "RGBA"
render("skymask")
