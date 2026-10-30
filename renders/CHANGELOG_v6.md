# Haunted village v6: refine pass

Source: `renders/haunted_village_v5.blend`, opened as saved (v5 is unchanged). `tools/refine_v6.py` applies the pass
and saves `haunted_village_v6.blend`. The camera, layout, buildings, terrain and baked textures carry over.
Every new or changed material stays RenderMan-ready: it is image-based, vertex-coloured or constant, and is listed
in `textures_rman/manifest_haunted_village_v6.json`. `renderman_setup.py` picks that manifest up automatically when v6 is open.

## Sky and moon
- **Moon:**
  - The radius drops from 9 to 6.5 m.
  - A generated lunar albedo map (`moon_albedo_v6.png`) replaces the blotchy noise. It has 7 maria placed on the side facing the camera, 320 craters and one rayed crater.
  - Emission drops from 3.6 to 1.9, so the maria and craters read instead of clipping to white.
- **Clouds:** clouds within about 30° of the moon are lit from behind, with silver edges and a soft glow. The sky away from the moon is up to 20% darker, for a deeper blue. This is a new map, `sky_emission_v6.png`; its values are scaled into 8-bit headroom and the emission strength is raised to match.
- **Halo card (Cycles only):** glow 1.6 → 2.3.

## Fog and light
- **Fog colour:** the mist and world fog are cooler, (0.5, 0.62, 0.92) and (0.5, 0.6, 0.9).
- **Village lamp (`vlight`):** 500 → 1200 W with a 1 m radius, and it no longer scatters in the fog. The street fog stays blue instead of turning pinkish-grey, and the lamp now reaches the road and wall.
- **`yard_spill`:** a new 450 W warm, 2 m disc light just outside the frame on the right. It rakes across the barrel, wall and brush, as the warm foreground light does in the reference. It's hidden from glossy rays.

## Foreground and village
- **Brush:**
  - 5 twiggy dead-shrub meshes (tapered twigs) carry dry leaves that reuse the 6 baked leaf materials and UVs. The twigs take their colour from a vertex attribute (`bake_col`, which RenderMan reads as `Cs`).
  - 35 placements along the road and yard sides of the stone wall, the front fence line, around the barrel, in the foreground right and on the village verge.
  - Each sits on the terrain height map, and none is closer than 2.1 m to the road centreline (the traveled way is ±1.75 m).
- **Road gravel:** pebble density ×3, so there's more gravel on the road and shoulders. The wheel tracks stay mostly clear.
- **Village windows:** frames and sills on 39 windows of the village houses and the right-hand house, in a constant dark weathered trim material.

## Checks
- **RenderMan dry run:** against stand-in node types it built 47 networks (45 materials and 2 volumes), with 0 warnings and all 45 textures found.
- **Renders:** see `v6_review/` for the final frame, the comparison with v4 and with the reference, and close-ups of the moon and the foreground.

## Remaining limitations
- **Village houses:** apart from the new frames, they're still simple boxes softened by the fog.
- **Brush:** it reads mostly as silhouettes on the shaded left side. The warm light only reaches the right half of the foreground.
- **Moonlit clouds:** the glow is painted into the sky map, so it won't follow the moon if the moon is moved.
- **RenderMan:** still not run against a real RenderMan install. Lights, including the new `yard_spill`, use RenderMan for Blender's own translation and will need balancing.
