# Haunted village v4 — polish pass

Source: `renders/haunted_village_v3.blend`, opened as saved (v3 is unchanged). `tools/polish_v4.py`
applies the pass and saves v4. The camera, layout, GN terrain, puddles and scattered litter carry over from v3.

## Main house
- **Siding:** the 25 thin strips with dark gaps are replaced by 29 lapped boards on the front and 29 on the right side.
  - 21 cm boards, 18 cm exposure, bottom edge kicked out 5.5°.
  - Random butt joints, grain along each board, weather streaks and splash dirt near the ground.
  - Corner boards and a stone plinth.
- **Windows:** the 8 opaque window boxes are replaced by real openings cut through the wall and siding (exact Boolean).
  - Thin glass: IOR 1.52, Thin Wall, smudged roughness, grime toward the edges.
  - New sash frames and sills.
  - The glazing bars floated 14 cm in front of where the glass now is; they now sit on it. The casings floated 1 cm off the wall; they now sit on the siding.
- **Interiors:** two room cavities 3 m deep behind the glass, with dim plaster, floors, ceiling beams and partitions. Four windows have curtains.
- **Lit window:** the emissive panel is replaced by a lit room.
  - Light plaster, amber curtains, a picture and a wardrobe.
  - A 5000 W warm point lamp beside the window, hidden behind the jamb from the camera.
  - Only this pane passes direct light, so the lamp also reaches the yard. The other panes block it, so the unlit rooms stay dark and show reflections instead of the fill light.
- **Roofs:** the shared roof material is rebuilt as weathered shingles, which updates all 9 roofs. The main roof's gable ends are boarded and its underside is soffit wood.
- **Trim:** darker weathered paint with grime (casings, sashes, sills, corner boards, portico).
- **Door:** wood planks instead of glossy black.

## Grounds
- **Stone wall:** the 140 box stones are replaced by faceted fieldstones (10 shared meshes) at the same positions, yaw and size. Four bottom-course stones that floated were lowered onto the terrain; none now float more than 3 mm.
- **Foreground rocks:** subdivision and displacement removed. They now use the same fieldstone meshes, in the same positions.
- **Fieldstone material:** grey-brown with fine grain, sparse lichen and soil grime at the base.
- **Fence:** 58 posts and rails get 12 mm bevels and weathered wood whose grain follows each piece.

## Lighting, sky and exposure
- **Outside lights:**
  - The light outside the lit window drops from 900 W to 150 W.
  - The yard light drops from 1500 W to 1000 W, with its radius raised from 0.25 to 1.2 m to remove the hot spot in the weeds.
  - Both are hidden from glossy rays, so they leave no lamp-like blobs in the glass.
- **Fill light:** 3500 W → 2600 W, so the facade sits back and the lit window leads.
- **Exposure:** 0.60 → 0.85, to give back the shadow detail the lower fill took away.
- **Moon:** emission 7 → 3.6, with broad darker maria and limb darkening, so the disc shows surface detail.

## Performance
Cycles on CPU (4-core container), denoising on. Cycles memory is the largest "Mem" value in Cycles' render stats. There is no GPU here, so there is no VRAM figure.

| Render | Time | Cycles memory | Process peak RSS |
|---|---|---|---|
| v3, 1280 × 720, 32 spp | 132.9 s | 212 MB | 1742 MB |
| v4, 1280 × 720, 32 spp | 179.6 s | 212 MB | 1585 MB |
| v4 final, 1920 × 1080, 64 spp | 789.7 s | 339 MB | 2593 MB |

- **Time:** v4 renders about 35% slower at matched settings. The likely causes are the glass, interior bounce light and the extra light inside the house.
- **Memory:** Cycles memory is unchanged. The 10 shared stone meshes replace 140 unique boxes, and the rocks lost their subdivision.
- **RSS:** varies by about ±150 MB between runs, so treat it as approximate.

## Review images (`v4_review/`)
- `compare_v3_v4_facade.png`, `compare_v3_v4_wall.png`: 2560 px crops of the same regions, both at the v3 exposure (0.6). They were rendered before the final exposure lift and the four-stone seating fix.
- `compare_v3_v4_full.png`: the v3 final against the v4 final.
- `compare_reference_v4.png`: the reference against the v4 final. The composition matches: moon upper left, house right with the lit upstairs window, village street left, fence and barrel in front. The reference still has far denser surface detail and brush, darker timber and a visible wagon.

## Remaining limitations
- **Interiors:** simple boxes. They hold up through the glass at this distance, not in a close-up.
- **Lamp strength:** the lamp is strong (5000 W) because its light must read through glass and curtains from 20 m away. A closer camera would need it rebalanced.
- **Siding coverage:** siding is modelled on the two sides in shot only.
- **Other buildings:** the village houses, the right-hand house and the wagon still use the v2 box construction, softened by mist and distance.
- **Leaves:** fallen leaves are still small flecks even at 1920 px.
- **Rocks:** the foreground rocks share the wall's stone meshes, so two of them can repeat a shape. That's not noticeable at this distance.
