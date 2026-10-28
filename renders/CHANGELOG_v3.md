# Haunted village v3 — ground pass

Source: `renders/haunted_village_v2.blend`, opened as saved (v2 is unchanged). The scene-generation
script was not rerun; `tools/ground_detail.py` applies this pass to the v2 file and saves v3.

## Preserved from v2
Buildings, fences, stone wall, barrel, wagon, weeds, trees, sky, moon, mist, smoke, lighting,
camera and render settings.

## Replaced
- Road strip mesh and 6 flat disc puddles → Geometry Nodes terrain (`terrain_gn`) and one water surface (`puddle_water`).
- Ground plane → `ground_backdrop`: subdivision and displacement removed, lowered 0.3 m under the new terrain.
- 16 foreground rocks, same positions: smooth shading, lumpy displacement, `fieldstone` material with soil grime at the base, buried 15% of their height deeper.
- Wall stone `st.128` lowered 4.7 cm onto the new terrain (it floated 3.7 cm).

## Road alignment
Beyond about 20 m the centreline bends up to 1.3 m further left. The v2 road strip ran about 1.8 m into
the footprint of the house at (-1, 30). Checked on the 2048² map: no building, wall, post or prop
footprint falls inside the 3.5 m traveled way (`v3_review/overhead_v3_road_clearance.png`).

## Height maps (`textures/`, packed into the .blend)
- `terrain_height_2048.png`: 16-bit world height, 64 × 64 m at 3.1 cm per pixel. It holds:
  - a sunken compacted track with soft shoulders and raised, uneven verges
  - two shallow wandering wheel ruts with pushed-up lips
  - churned mud lumps and hoofprints along the centre
  - noise-warped puddle depressions
  - soil mounded against wall footings, posts and house sills
- `terrain_masks_1024.png`: R road surface, G sheltered zones (from the scene's real object footprints), B wheel tracks, A obstacle footprints.
- `mud_detail_tile_1024.png`: tileable 16-bit micro-height (grit, embedded pebbles, pits) for shader bump. It is sampled at two scales and rotations and blended, to hide tiling.

## Geometry Nodes (`GN_TerrainGround` modifier on `terrain_gn`)
- **Terrain grid:** follows the camera. Columns are spaced by angle and rows evenly in 1/distance, so vertex spacing tracks on-screen size: about 2 cm at the bottom of the frame, metres at 180 m. The grid is displaced by the height map with cubic sampling. 640 × 480 = 307k vertices.
- **Scattered instances (not realized):** 6 leaf shapes (6.6k), 5 pebble shapes randomly sunk up to 35% of their size (0.8k), 3 twigs (67), and 3 detailed plus 1 low-poly dry-grass tuft (7.2k).
- **Masks:** keep wheel tracks, water and footprints clear. Litter collects in sheltered zones. Leaves near water are darker and flatter. Detail fades with distance. The seed is stable.
- **Controls:** Angular/Radial Resolution, Near/Far Distance, Half Angle, Water Level, Seed, Leaf/Pebble/Twig/Grass Density, Litter Range, Grass Detail Range.

## Water and ground materials
- `puddle_water`: one flat surface at z = −0.05 m over the road band. It uses turbid water (IOR 1.333, roughness 0.025–0.055, faint ripple bump) with no emission, and only shows where the terrain dips below it: 30 m² in total, none outside the road.
- `terrain_mud`: world-space material.
  - Road and verge blend through the mask with an irregular edge.
  - Wetness comes from height above the water level: darker and slicker near water, and slicker in micro-hollows than on grit, never mirror-like.
  - It has two bump layers: clods and micro-height.

## Performance
1280 × 720, Cycles on CPU (4-core container), 32 samples, denoising on, same camera and exposure.

| Scene | Render time | Cycles memory | Process peak RSS |
|---|---|---|---|
| v2 baseline | 122.1 s | 116 MB | 1275 MB |
| v3 final | 132.9 s | 212 MB | 1742 MB |
| v3, terrain 448 × 336 (previous iteration) | 136.1 s | 183 MB | 1505 MB |

- **Cycles memory:** the largest "Mem" value in Cycles' render stats. This build reported no separate peak figure.
- **VRAM:** there is no GPU here, so there is no VRAM figure.
- **Process RSS:** varied between runs. Two near-identical v3 states measured 1570 and 1742 MB while Cycles memory moved only 1 MB, so treat RSS as approximate.
- **Terrain resolution:** 448 × 336 saves 28 MB of Cycles memory and no time, but softens the mid-road relief (`v3_review/terrain_res_compare.png`, top 640 × 480, bottom 448 × 336). 640 × 480 is kept.

## Remaining limitations
- **Leaves:** they are 7–12 cm across at 9–15 m, so at 1280 px they read as small flecks, not leaf shapes.
- **Wall and rocks:** the stone wall is still stacked boxes, and the rocks read slightly blue under the moonlight.
- **Mist:** the existing mist volume brightens the middle and far road.
- **Camera-tied terrain:** moving the camera re-tessellates the terrain. That's fine for a locked-off ambience shot; for camera moves, raise Half Angle and the resolutions.
- **Rock shapes:** the lump displacement uses global coordinates, so moving a rock changes its shape.
- **Map coverage:** the height map covers 64 × 64 m. Beyond it the edge values repeat, which only shows far away in the mist.
