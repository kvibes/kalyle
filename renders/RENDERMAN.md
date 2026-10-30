# Rendering the haunted village in RenderMan

The scene's materials were procedural Blender node graphs. RenderMan can't evaluate those:
- **No RenderMan node tree:** RenderMan for Blender renders the material as a flat viewport colour.
- **Built-in converter:** it doesn't read noise, Voronoi, brick, Map Range or the newer Mix node. It also fails on Blender 4+/5 Principled sockets, because it still uses the old names (Subsurface, Specular, Clearcoat…).

So the textures were baked to image maps (`textures_rman/`), and a script builds RenderMan materials from them.

## What you need
- Blender 5.x with RenderMan for Blender 27.x enabled (RenderMan 27 installed and licensed).
- `haunted_village_v6.blend` (latest) or `haunted_village_v5.blend`, with the `textures_rman/` folder next to it, as in this repo.
  - The script reads `textures_rman/manifest_<file name>.json` when it exists, so v6 uses `manifest_haunted_village_v6.json`.
  - Otherwise it falls back to the shared `manifest.json`, which is v5's.

## Steps
1. **Open the scene:** open `renders/haunted_village_v6.blend` (or v5) in Blender.
2. **Run the setup script:** in the Scripting workspace, Open `tools/renderman_setup.py` and Run Script. From a terminal, the equivalent is:
   `blender -b renders/haunted_village_v6.blend --python tools/renderman_setup.py`
3. **Read the summary:** the script prints a summary and writes `renders/renderman_setup_log.txt`. A clean run reports 0 warnings. Any warning names the node or parameter your RenderMan version didn't accept.
4. **Save the file** (it now has both Cycles and RenderMan materials) and render with RenderMan.
   - The first render can wait while RenderMan's texture manager converts the PNGs to `.tex`. The Texture Manager window shows progress.

## What the script builds
| Manifest kind | RenderMan network |
|---|---|
| surface (37) | PxrSurface. Diffuse colour comes from PxrTexture (sRGB, linearized), specular roughness from PxrTexture, and bumpNormal from PxrNormalMap. Translucent sheets (curtains, leaves) use diffuseTransmit. |
| terrain | As surface, plus the mud micro-height tile: PxrManifold2D repeats it 40× into PxrTexture, then PxrBump on top of the normal map. |
| glass | PxrSurface glass lobe: thin glass, IOR 1.52, roughness map, and a diffuse dirt layer driven by the grime mask. |
| vertex_color (grass, weeds) | PxrPrimvar `Cs` (the baked colour attribute) into diffuse colour. |
| emissive (sky dome, moon) | PxrMeshLight with the baked emission map as textureColor, plus PxrBlack. |
| emissive_constant (village windows) | PxrMeshLight with a constant colour. |
| mist | PxrVolume on the mist box, with the object set to a RenderMan box volume. |
| atmosphere | A new `rman_atmosphere` volume box, hidden from Cycles, standing in for the Cycles world fog. |
| halo, chimney smoke | Hidden in RenderMan. In Cycles the halo is a camera-facing glow card; in RenderMan the moon's light scattering in the volumes should give the glow instead. The smoke would read as a box. |

Re-running the script replaces the RenderMan nodes it made. The Cycles nodes are never touched, so the file still renders in Cycles.

## Expect to adjust
- **Lights:** these are left as Blender lights. RenderMan for Blender translates them itself: point and area intensity equal Blender's watts, and the sun gets intensity 1, ignoring its Blender strength. The balance will differ from Cycles, so tune exposure or individual light intensities after the first render.
- **Bumps:** if bumps look inverted, set `FLIP_NORMAL_Y = True` at the top of the script and run it again. The maps are baked OpenGL-style.
- **Terrain bump:** the micro-height tile's `PxrBump` scale (0.0096) is converted from Blender's bump settings and may need tuning.
- **Volumes:** constant density. The Cycles mist was noise-modulated.

## What was verified, and what wasn't
- **Verified in Cycles:** the baked v5 file renders in Cycles next to v4 at the same settings. The comparison is in `v5_review/`.
- **Dry-run:** the RenderMan script ran end to end against stand-in RenderMan node types (`tools/test_renderman_setup_stub.py`). It built 45 material and volume networks with 0 warnings and found all 43 texture files.
- **Not run against real RenderMan:** there was no RenderMan in the environment where this was made. Node and parameter names come from the RenderMan for Blender 27.3 source (`rfb_api`, its Cycles converter and property tables) and RenderMan's shader documentation. Anything that doesn't match your install is reported, not silently skipped.
