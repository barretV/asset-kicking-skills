# Examples

Small outputs from the pipelines on the 6 GB reference machine (RTX 3060 Laptop). All images are recompressed with metadata stripped.

| File | Skill | How it was made |
|---|---|---|
| `pixel-sprite/axolotl_knight_native.png` | pixel-art | MOSS-Image Turbo + moss-pixelart LoRA, 512×512 txt2img (8 steps, CFG 1, seed 777, ~35 s), then `moss_snap.py --factor 8`: a 55×64 native sprite. No hand edits. |
| `pixel-sprite/axolotl_knight_x6.png` | pixel-art | The same sprite at 6× nearest-neighbour, for viewing. |
| `concept/crystal_beast_concept_side.webp` | art-forge-loop | MOSS-Image illustration mode, a side-view creature concept picked from the graded loop. This is the input to the 3D route. |
| `3d-render/crystal_beast_hi3d_sculpt_clay_3q.webp` | concept-to-3d | That concept through TRELLIS.2 (coarse, ~3.5 min) and Hi3D 512→1024 (~10 min), rendered as CPU clay by `hi3d_render.py`. The raw sculpt, before any cleanup. |
| `sound/*.ogg` | game-sfx | `sfx_synth.py coin laser explosion powerup --seed 2026`, then `finish_sfx.py --format ogg`. No GPU, no samples. |

Regenerate the sounds yourself:

```bash
python skills/game-sfx/bin/sfx_synth.py coin laser explosion powerup --seed 2026 --out work/raw
python skills/game-sfx/bin/finish_sfx.py work/raw work/ready --format ogg
```

Licence: these example files are covered by the repo's MIT licence.
