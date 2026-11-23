---
name: concept-to-3d
description: Turn a 2D concept into a 3D model locally - MOSS concept (art-forge-loop), TRELLIS.2 image-to-3D in ComfyUI, optional Hi3D refine to a detailed sculpt, then measure it against your Blender model or clean it into a game mesh, rig and verify with blender-anim. Use when asked to make a 3D creature, prop or character from a concept, to get a sculpt to model against, or to check a model's proportions against its concept art.
metadata:
  category: gamedev
  tools: comfyui, blender, python
---

# Concept → 3D: MOSS concept → TRELLIS.2 → (Hi3D) → Blender

```
art-forge-loop (illustration mode)     ComfyUI, GPU                      Blender / CPU
  side concept  ──────────────►  TRELLIS.2 coarse mesh  ──►  Hi3D 512→1024 sculpt  ──►  measure, or clean + zone + rig
     (and a 3/4)                   (~3.5 min at 6 GB)          (9-11 min at 6 GB)           (blender-anim verifies)
```

Two ways to use the sculpt:
1. **Sculpt donor (safest).** The sculpt is a measuring stick: compare your hand-built or procedural Blender model to it and move proportions toward it. The sculpt never ships.
2. **Sculpt as the model.** Clean, decimate and colour-zone the sculpt itself, then rig it. Faster, but generated sculpts are mushy in small parts (faces, claws, plate edges); rebuilding those parts as clean geometry on the sculpt's body (a hybrid) reads best.

## GPU safety (read before any GPU job)
Generation is heavy and long. On small or laptop GPUs, stacked GPU work can hang or reboot the machine.
- **One GPU job machine-wide.** Check `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv`, plus running ComfyUI, Blender renders, browsers running WebGL and other agents. Wait for them; never start a second job alongside.
- **Cool down** about 60-90 s between heavy jobs. **Stop ComfyUI** when you finish.
- If `gpu_lock_dir` is set in `~/.asset-kicking-skills/config.json`, take the lock (create a file in it named after your job) before a GPU job and delete it after.
- Everything after generation (measuring, clay renders, cleanup) runs on the CPU.

## Needs
- ComfyUI 0.42 or newer (TRELLIS.2 is a core node from about 0.45; `Hi3D` needs the `ComfyUI-Hi3D` custom node).
- Model bundles `trellis2` (and `hi3d` for the refine) from `setup/models.py`.
- Blender 4.4+ on PATH (or `BLENDER_PATH`), Python with numpy and Pillow for the CPU tools.
- The tier's ComfyUI launcher from `setup/launcher.py` (6 GB: `--lowvram --reserve-vram 0.7 --vram-headroom 0.5 --disable-smart-memory --cache-none`).

## 1. Make the concept
Use `art-forge-loop` in illustration mode. Ask for a **side view** on a plain background, full body, nothing cropped, and a 3/4 view as a second opinion. Pick one per view at 9+ on your bar.

**Use the side concept for 3D.** A 3/4 painting foreshortens the near limbs and TRELLIS.2 builds them literally: in one test the 3/4 sculpt came out 60% wider than the side sculpt of the same creature.

## 2. Generate (GPU)
1. Pad the concept to a square and copy it to `ComfyUI/input/<name>.png`. BiRefNet cuts it out inside the graph.
2. Start ComfyUI with the general launcher, then build the graphs (they adapt to the installed ComfyUI by reading `/object_info`):
   ```bash
   python <skill>/bin/build_graphs.py work/graphs --image <name>.png --name <tag>
   ```
   Options: `--seed` (Hi3D), `--tseed` (TRELLIS.2 structure), `--stages 512,1024` (add `,1536` on 8 GB+), `--no-remesh`, `--dino <file>` if your TRELLIS.2 image encoder has another name.
3. Coarse mesh (TRELLIS.2, ~3.5 min at 6 GB):
   ```bash
   python <skill>/bin/run_prompt.py work/graphs/<tag>_coarse.api.json
   ```
4. Copy `ComfyUI/output/hi3d/<tag>_coarse_*.glb` to `ComfyUI/input/3d/<tag>_coarse.glb`, then refine (Hi3D, 9-11 min for 512→1024 at 6 GB, peaks near 5 GB):
   ```bash
   python <skill>/bin/run_prompt.py work/graphs/<tag>_refine.api.json
   ```
   Stop here if you only need a coarse shape: the TRELLIS.2 mesh alone is often enough as a proportion guide.
5. Stop ComfyUI.

## 3a. Use it as a sculpt donor (CPU)
```bash
blender -b --factory-startup -P <skill>/bin/hi3d_export_mesh.py -- model.glb model.npz
blender -b --factory-startup -P <skill>/bin/hi3d_export_mesh.py -- sculpt.glb sculpt.npz --max-faces 300000
python <skill>/bin/hi3d_compare.py model.npz sculpt.npz out/cmp        # IoU per view + overlay PNG + align json
python <skill>/bin/hi3d_measure.py model.npz sculpt.npz out/cmp.json   # head, limbs, shoulder, haunch, tail sizes
blender -b --factory-startup -P <skill>/bin/hi3d_render.py -- sculpt.glb out/cmp.json out/clay   # CPU clay renders
python <skill>/bin/hi3d_sheet.py out/sheet.webp --title "My creature" --row "side" concept=c.png before=b.png sculpt=out/clay-side.png after=a.png
```
- Game axes: +Y up, +Z forward. The compare picks the yaw, scales the sculpt to the model's length and puts it on the model's floor (Hi3D output is normalised to unit radius and has no floor).
- Move your build's proportions where **both** sculpts (side and 3/4) agree; where they disagree, trust the side one or go halfway. Re-run until IoU stops improving.
- `hi3d_measure.py` regions are fractions of the bounding box tuned for quadrupeds; edit `REGIONS` for other body plans.
- What it gave on its first use: silhouette IoU up in every view, stance width, haunches and hump settled with numbers. What it did not give: a better face. It fixes **proportions and masses**, not detail.

## 3b. Use the sculpt as the model (CPU, Blender)
1. **Clean:** import in game axes, scale to the intended size, voxel remesh (about 0.02 of the body length) to close holes, delete floating islands, symmetrize from the better side, put the lowest point on the floor. Use the 1024 sculpt; 1536 detail does not survive a game budget.
2. **Colour zones on the full-res mesh:** register the concept to the side silhouette (an affine fit is enough) and take big regions from it; take small parts from geometry (claws and teeth by thin ray thickness, mouth by openness, eyes by raycast).
3. **Decimate** (Collapse, X symmetry) with the zone borders protected by a vertex group. Give each low-poly face the zone most of its nearest hi-res faces have, then merge tiny islands.
4. **Rig and animate** with `blender-anim` (SkinTokens or capsule-distance weights for simple quadrupeds), then gate with its `verify.py`.

Toon-shading rules learned the hard way:
- One solid colour per face per region; nothing finer than the face size (it reads as splotches).
- Smooth the **shading normals**, not the colours: a Taubin-smoothed copy written as custom normals; otherwise sculpt micro-detail breaks a toon ramp into mottle.
- Keep neighbouring tones close so a wandering border does not show.
- Emissive lines only on long connected edge chains (24+ vertices); short ones read as smudges.

**Hybrid (best read so far):** keep the cleaned sculpt's body for its mass and rebuild the parts that carry the read as clean geometry: the head from ellipsoids in a head-local frame, armour plates as Voronoi slabs with bevels over a glowing under-layer, claws and crystals as faceted tubes. Copy skin weights from the nearest body vertex, keep hard parts rigid on their bone, and drop loose vertices after decimating.

## Licences (outputs)
- **TRELLIS.2:** MIT. **BiRefNet:** MIT. **DINOv3** (TRELLIS.2's image encoder): Meta's DINOv3 License, commercial use allowed; used locally, never redistributed.
- **Hi3D:** Hi3D Open License 1.0. Commercial use is allowed. Meshes you generate are yours to sell with **no** "Powered by Hi3D" notice and no scale licence, as long as you ship meshes and not Hi3D weights or code. If you build Hi3D itself into a product or service, its branding rule and the 200k MAU / USD 1M per month threshold apply. Read the full text before shipping.
- Do not use UltraTex or FLUX.1-dev texturing (non-commercial), or Hunyuan3D 2.x (its licence excludes the EU, UK and South Korea).

## Traps
1. **Two Hi3D node packs conflict.** Install only `Aero-Ex/ComfyUI-Hi3D`; forks register the same node IDs.
2. **Hi3D sculpts have no scale and no floor**, and a raw 1024 sculpt is 2-4M faces: decimate on import (`--max-faces`) before anything else touches it.
3. **A 3/4 concept makes fat limbs** (see step 1).
4. **Separate parts by material name**, not slot: separate-by-material compacts slots.
5. **Check Blender's exit code** (`--python-exit-code 1`) before spending a GPU run on renders.

## Files

| path | what it is |
|---|---|
| `bin/build_graphs.py` | writes the coarse (TRELLIS.2) and refine (Hi3D) API graphs from `pa_wf01.json` |
| `bin/run_prompt.py` | queues one API graph, waits, prints per-node timing and saved files |
| `bin/pa_wf01.json` | the source workflow (PixelArtistry, MIT; see THIRD_PARTY_NOTICES.md) |
| `bin/hi3d_export_mesh.py` | Blender: dump a GLB's triangles in game axes to .npz |
| `bin/hi3d_compare.py` | CPU: align sculpt to model, IoU per view, overlay, profiles |
| `bin/hi3d_measure.py` | CPU: named mass sizes, model vs sculpt |
| `bin/hi3d_render.py` | Blender Cycles on the CPU: clay renders in the model's frame |
| `bin/hi3d_sheet.py` | Pillow: concept / before / sculpt / after sheet |
