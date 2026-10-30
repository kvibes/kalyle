# Haunted village v5: baked textures for RenderMan

Source: `renders/haunted_village_v4.blend`, opened as saved (v4 is unchanged). `tools/bake_rman_textures.py`
bakes it in two stages and saves `haunted_village_v5.blend`. The layout, lighting, camera and render settings are unchanged.

## Why
RenderMan can't evaluate Blender's procedural shader nodes:
- **No RenderMan node tree:** RenderMan for Blender 27.3 renders the material as a flat viewport colour.
- **Built-in converter:** it handles only image textures, bump/normal maps, ramps, math and attributes. Its Principled path reads Blender 3.x socket names, which raise errors in Blender 4+/5.

The procedural materials are therefore baked to image maps. `tools/renderman_setup.py` builds RenderMan networks from them (see `RENDERMAN.md`).

## Baked (`textures_rman/`, 63 maps, 71 MB, plus `manifest.json`)
| Group | Method | Size | Texel |
|---|---|---|---|
| siding (58 boards) | per-face boxes at real scale, shelf-packed; hidden back and top faces at 1/8 density | 2048² | 6.4 mm |
| fence (58 posts and rails) | per-face boxes at real scale | 2048² | 3.8 mm |
| trim (108 pieces) | per-face boxes at real scale | 1024² | 10.8 mm |
| plinth | per-face boxes at real scale | 1024² | 13.4 mm |
| fieldstones (156 stones and rocks) | 10 shared meshes unwrapped once and baked on the lowest instance | 2048² | about 2 mm |
| roofs (9, with gable and soffit) | smart project at real scale | 2048² | |
| terrain | world-planar UVs written by the GN modifier; 64 m map, plus the mud micro-height tile repeated 40× as bump | 4096² | 1.6 cm |
| sky dome, moon | emission maps on the UV spheres | 6144×3072, 1024×512 | |
| village/v2 boxes, brick, chimney cap, beams, door, picture | one bake per shared mesh | 256–1024² | |
| glass | roughness and edge-grime mask on the shared pane | 512² | |
| barrel, shrubs, curtains, pebbles, twigs | smart project atlases | 256–512² | |
| leaves (6 shapes) | one material copy and texture per shape | 256² | |
| grass tufts, weeds | baked vertex colours (`bake_col`, exported as `Cs`) | | |

Each baked material is now an image-driven Principled BSDF: base colour, roughness, and a normal map through a Normal Map node. Translucency mixes, glass and emission are kept.

## Check in Cycles (1280 × 720, 32 spp, same camera and exposure)
| | Time | Cycles memory | Process peak RSS |
|---|---|---|---|
| v4 (procedural) | 190.5 s | 212 MB | 1600 MB |
| v5 (baked) | 185.2 s | 625 MB | 2027 MB |

- **Difference:** mean absolute difference 0.95/255; 95th percentile 4/255; 99th percentile 10/255. Mean brightness is 36.6 against 36.8.
- **Largest local difference:** the road and wall, at 2.3/255. There the 1.6 cm terrain bake replaces full procedural detail, and the wetness-dependent bump strength becomes a constant.
- **Memory:** Cycles holds the 63 maps in memory, about 400 MB more. RenderMan streams mipmapped `.tex` tiles instead.
- **Images:** see `v5_review/compare_v4_v5.png`.

## Bake run
- **Stages:** stage 1 (atlases) took 793 s and stage 2 took 250 s, on a 4-core CPU at 1 bake sample.
- **Isolated bake scene:** each bake runs in a scene holding only its objects. In the full scene every bake call re-synced the GN terrain, instances and volumes; a small test took 113 s there against 0.4 s isolated.

## RenderMan setup (not run against RenderMan)
- **Script:** `tools/renderman_setup.py` adds RenderMan output networks beside the Cycles nodes: PxrSurface, PxrTexture, PxrNormalMap, PxrBump, PxrManifold2D, PxrPrimvar, PxrMeshLight and PxrVolume.
- **Dry run:** against stand-in node types (`tools/test_renderman_setup_stub.py`) it built 45 networks with 0 warnings, and all 43 textures were found.
- **Untested:** RenderMan itself wasn't available here, so the real node and parameter names are only checked when you run it.

## Lost or simplified in the bake
- **Leaves:** the per-instance damp darkening of leaves near water is gone. There's one colour variant per leaf shape instead.
- **Moon:** limb darkening is view-dependent, so it isn't in the map.
- **World-position variation:** variation that depended on an object's world position is fixed at bake time. Moving a baked object now carries its texture with it.
- **RenderMan only:** volumes have constant density, the chimney smoke and the moon halo card are hidden, and lights use RenderMan for Blender's own translation and will need balancing.
