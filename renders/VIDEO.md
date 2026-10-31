# Haunted village ambience video

`haunted_village_ambience.mp4` runs 3:12.65, the full length of the supplied track "the sea remembers the ocean…".
- **Video:** 1920 × 1080, 24 fps, H.264 (CRF 18), 4,624 frames.
- **Audio:** the supplied WAV (mono, 24 kHz), encoded as AAC 192 kb/s at 48 kHz stereo and otherwise unchanged.
- **Fades:** the picture fades in over 2 s and out over 3 s.

## What moves
- **Window:** the upstairs window flickers like an oil lamp, between about 80% and 115% brightness.
- **Clouds:** they drift slowly past the moon, about 17° of sky over the video. The moon and the moonlit glow around it stay in place.
- **Mist and smoke:** the street mist and the chimney smoke shift and churn.
- **Camera:** a slow push-in toward the house, 4% over the whole video.

Nothing else moves: the camera position, the buildings, the trees and the grass are locked off.

## How it was made
A Cycles frame of this scene takes about 13 minutes at 1080p on the 4-core machine used, so rendering 4,624 frames was not an option.

`tools/video_passes.py` renders five linear EXR passes of `haunted_village_v6.blend` once, from the same camera and seed:
- `nolamp`: the scene without the room lamp.
- `lamp`: the room lamp alone.
- `nodomecam`: the scene with the sky dome black to camera rays.
- `nolocalvol`: the scene without the street mist and chimney smoke.
- `skymask`: a mask of where the sky dome is visible.

The five passes took 43 minutes in total.

`tools/video_composite.py` then builds every frame in linear light and writes it through the scene's own view transform (AgX Punchy, exposure 0.85), so it matches the stills. Each frame is made like this:
- **Lamp:** `nolamp + flicker(t) × lamp`. Light adds linearly, so this re-lights the window exactly.
- **Clouds:** the sky dome is re-projected from its texture with the clouds shifted, and multiplied by the fog transmittance measured as `(nolamp − nodomecam) / sky`. The moonlight around the clouds is recomputed with the fixed moon.
- **Mist and smoke:** `(nolamp − nolocalvol)`, modulated by slowly drifting noise.
- **Push-in:** a 2D zoom.

Three workers composited the frames in about 2 hours of CPU time in total. `ffmpeg` then joined the frames and the audio.

To make it again:

```bash
python3 tools/video_passes.py renders/haunted_village_v6.blend <passes_dir> 1920 64
python3 tools/video_composite.py renders/haunted_village_v6.blend <passes_dir> <frames_dir> 0 4623 192.65
ffmpeg -framerate 24 -i <frames_dir>/%05d.png -i <audio.wav> \
  -vf "fade=t=in:st=0:d=2,fade=t=out:st=189.65:d=3,format=yuv420p" \
  -c:v libx264 -crf 18 -tune film -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest haunted_village_ambience.mp4
```

## Limits of this approach
- **Real 3D motion:** none. Trees, grass and brush are frozen, and the clouds are one drifting layer that always stays behind the moon.
- **Transmittance:** fog transmittance in front of the sky is smoothed, so the first frame differs slightly from a direct render (about 2.4/255 on average).
- **Push-in:** it's a 2D zoom, so the image softens by up to 4% by the end.
- **Renderer:** made with Cycles from the v6 scene; RenderMan wasn't used for the video.
