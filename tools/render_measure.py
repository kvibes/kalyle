"""Render a .blend from its scene camera and report time and memory.

Usage: python3 render_measure.py scene.blend out.png [width] [samples] [border xmin xmax ymin ymax]
Prints wall-clock render time, Cycles' own peak memory (from the render stats
callback) and the process peak RSS. No GPU is used here, so there is no VRAM figure.
"""
import bpy, sys, time, resource, re

blend, out = sys.argv[1], sys.argv[2]
width = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
samples = int(sys.argv[4]) if len(sys.argv) > 4 else 32
border = [float(v) for v in sys.argv[5:9]] if len(sys.argv) > 8 else None

bpy.ops.wm.open_mainfile(filepath=blend)
scene = bpy.context.scene
scene.render.resolution_x = width
scene.render.resolution_y = int(width * 9 / 16)
scene.render.resolution_percentage = 100
scene.cycles.samples = samples
scene.cycles.device = "CPU"
if border:
    scene.render.use_border = True
    scene.render.use_crop_to_border = True
    (scene.render.border_min_x, scene.render.border_max_x,
     scene.render.border_min_y, scene.render.border_max_y) = border
scene.render.filepath = out
scene.render.image_settings.file_format = "PNG"

stats = []
bpy.app.handlers.render_stats.append(lambda s: stats.append(s))
t0 = time.time()
bpy.ops.render.render(write_still=True)
dt = time.time() - t0
print("RESULT engine=%s device=%s res=%dx%d samples=%d border=%s" % (
    scene.render.engine, scene.cycles.device, scene.render.resolution_x, scene.render.resolution_y, samples, border))
print("RESULT render_seconds=%.1f" % dt)
mems = [float(m) for s_ in stats for m in re.findall(r"Mem:\s*([\d.]+)M", s_)]
peaks = [float(m) for s_ in stats for m in re.findall(r"Peak:?\s*([\d.]+)M", s_)]
print("RESULT cycles_mem_max_MB=%s" % (max(mems) if mems else "unavailable"))
print("RESULT cycles_peak_MB=%s" % (max(peaks) if peaks else "not reported by this build"))
print("RESULT process_peak_rss_MB=%.0f" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
