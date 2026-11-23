# Hardware tiers

`setup/detect.py` reads the GPU's VRAM with `nvidia-smi` and picks the highest tier that fits. The machine-readable version is [setup/tiers.json](setup/tiers.json); `setup/launcher.py` turns it into ComfyUI launch scripts.

**Only the 6 GB tier is tested.** Reference machine: RTX 3060 Laptop (6 GB), 16 GB RAM, Windows 11, ComfyUI 0.45, Blender 5.3. The other tiers are extrapolated from it and from each tool's own documentation. If a job runs out of memory, step down one tier (`python setup/detect.py --tier <id>`), and please report what worked.

**Every tier runs one GPU job at a time.** More VRAM buys bigger images, bigger batches and higher precision, not parallel jobs.

## ComfyUI launch flags

| Tier | VRAM | General profile (`run_asset_kit`) | Rigging profile (SkinTokens) |
|---|---|---|---|
| `cpu` | none / <5.5 GB | `--cpu` (generation not supported; CPU skills only) | n/a |
| **`6gb`** (tested) | 5.5-7.5 GB | `--lowvram --reserve-vram 0.7 --vram-headroom 0.5 --disable-smart-memory --cache-none` | `--novram` |
| `8gb` | 7.5-11 GB | `--reserve-vram 0.6 --disable-smart-memory --cache-none` | `--lowvram` |
| `12gb` | 11-20 GB | `--reserve-vram 0.5` | `--lowvram` |
| `24gb` | 20 GB+ | `--highvram` | default |

6 GB notes:
- Environment: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,garbage_collection_threshold:0.6`.
- In recent ComfyUI builds `--lowvram` does nothing while DynamicVRAM is on (ComfyUI's own `--help` says so); `--reserve-vram`, `--vram-headroom` and turning off smart memory and caching are what keep a 6 GB card alive. Fallback if DynamicVRAM misbehaves: `--disable-dynamic-vram --lowvram --reserve-vram 0.7 --disable-smart-memory`.
- `--cache-none` also keeps host RAM down; keep it whenever RAM is 16 GB or less, on any tier.
- SDXL-class models (StableGen texturing) at 6 GB would need an fp8 UNet: `--fp8_e4m3fn-unet`. Untested.

## Model settings per tier

| | `6gb` (tested) | `8gb` | `12gb` | `24gb` |
|---|---|---|---|---|
| **MOSS-Image** UNet | int8 ConvRot (5.4 GB) | int8 ConvRot | int8 (bf16 10.2 GB optional) | bf16 or int8 |
| MOSS text encoder | w4a8 GPTQ (7.3 GB, offloaded after encode) | w4a8 | w4a8 | int8 (9.75 GB) or w4a8 |
| Pixel source size | 512 default, up to 1024 | 768, up to 1024 | 1024 | 1024 |
| Illustration size | 1024 | 1024 | 1024 | 1024 |
| Batch (images per job) | 1 | 2 | 4 | 8 |
| Speed | ~35 s at 512, ~65 s at 1024 | | | |
| **TRELLIS.2** | int8, 512 structure / 1024 upsample, ~3.5 min | same | same | same (bf16 if offered) |
| **Hi3D** weights | int8 (4.3 GB) | int8 | fp16 (7.7 GB) or int8 | fp16 |
| Hi3D stages | 512, 1024 (9-11 min; 1536 tight, ~5 GB peak) | 512, 1024, 1536 | 512, 1024, 1536 | 512, 1024, 1536 |
| **SkinTokens** | ComfyUI `--novram`, ~70 s / 120k verts | `--lowvram` | `--lowvram` (upstream wants 14 GB unoffloaded) | default |
| **Stable Audio 3** | Small-SFX (untested; ~2-2.5 GB expected) | Small-SFX | Small-SFX, Medium possible (~6.5 GB) | Medium or Small-SFX |
| **StableGen** texturing | unproven; SDXL fp8 UNet if tried | SDXL fp8 (its docs: ~8 GB) | SDXL fp16 | SDXL fp16 |

Moving up a tier changes **resolution, batch size, precision and flags**; the model files stay the same unless the table names an optional higher-precision file (`hi3d-fp16` bundle, MOSS bf16).

## RAM and disk

| | Minimum tested | Notes |
|---|---|---|
| RAM | 16 GB | Below that the MOSS text encoder swaps; keep `--cache-none`. 32 GB lets you drop it on 8 GB+ tiers. |
| Disk, default models | ~21 GB | `moss` + `trellis2` + `skintokens` |
| Disk, every bundle | ~33 GB (+7.7 GB for `hi3d-fp16`) | |
| Disk, software | ~15 GB | ComfyUI + venv + PyTorch, Blender, Aseprite build tools if compiling |

## Not GPU: CPU-only parts (every tier)
Pixel-art grid loop and export (Aseprite), Blender clip authoring, retargeting and `verify.py`, the sculpt measuring tools and clay renders (Cycles on CPU), procedural sound and the FFmpeg finishing pass.
