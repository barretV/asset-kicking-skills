# MOSS-Image Turbo → 8:1 pixel-art source

MOSS-Image is a ~5B single-stream flow-matching DiT (FLUX.2 small VAE, Qwen3.5-9B
text encoder). The community LoRA **moss-pixelart-v0.3** renders every logical
pixel as an **8×8 block**, so a 512×512 generation *is* a 64×64 sprite. That is
the difference from the older SD1.5 route: the low resolution is baked into the
weights, not guessed at downscale time.

Use this page for **every AI-sourced sprite**. This is the project's only AI source
stage: nothing else (SD1.5, Flux, SDXL, web image generators) is used unless MOSS
cannot run at all, and that exception goes back to the user rather than being chosen
silently. It is not a replacement for the grid loop or Aseprite: generated art still
needs a cold read, palette discipline and animation work.

**Decision (2026-11-10):** MOSS is the default. It reads as real pixel art because the
8:1 grid is baked into the LoRA, not approximated by a downscale, and it runs in ~35 s
at 512 on a 6 GB card. The measured A/B is summarised at the bottom of this page.

Two facts decide the workflow:

1. **The 8×8 grid must be verified, not assumed.** Diffusion decoding can drift
   by a fraction of a block. Always downscale with `BOX` from the detected
   factor and inspect the native frame; a wrong factor (7, 9) reads as soft or
   doubled edges.
2. **Turbo is CFG 1.** The negative prompt is ignored at CFG 1, so do not spend
   tokens on it. Turbo is 8 steps; the non-distilled SFT model is 25–50 steps at
   CFG 2.5–3. Mixing the two recipes gives either mush (8 steps at CFG 3) or
   banding.

## Prerequisites

| need | why | check |
| --- | --- | --- |
| ComfyUI from **2026-10-16 or later** | native MOSS-Image + INT8 ConvRot, no custom nodes | `git -C ComfyUI log -1 --date=short` |
| GPU ~6 GB VRAM | INT8 DiT 5.4 GB + 4-bit text encoder, offloaded after encode | `nvidia-smi` |
| ~14 GB disk | 4 model files, see below | — |
| `huggingface_hub` | only for the download step | `python -c "import huggingface_hub"` |

Model files (all public, all ComfyUI-native):

| folder | file | size |
| --- | --- | --- |
| `models/diffusion_models` | `moss_image_sft_turbo_int8_convrot.safetensors` | 5.41 GB |
| `models/text_encoders` | `qwen3.5_9b_w4a8_gptq.safetensors` | 7.34 GB |
| `models/vae` | `flux2-vae_small.safetensors` | 0.25 GB |
| `models/loras` | `moss-pixelart-v.0.3.safetensors` | 0.15 GB |

## Setup

```powershell
# 1. core update (must include the native moss_image CLIP type)
git -C C:\path\to\ComfyUI pull --ff-only

# 2. weights + verification (run with ComfyUI's venv python)
C:\path\to\ComfyUI\venv\Scripts\python.exe bin\moss_setup.py --check
C:\path\to\ComfyUI\venv\Scripts\python.exe bin\moss_setup.py
```

Start ComfyUI with the launcher `setup/launcher.py` writes for your tier
(`run_asset_kit.bat` / `.sh`). The 6 GB profile is:

```bat
venv\Scripts\python.exe -s main.py --lowvram --reserve-vram 0.7 ^
  --vram-headroom 0.5 --disable-smart-memory --cache-none
```

`--lowvram` is accepted but is **a no-op while DynamicVRAM is enabled** — that is
in ComfyUI's own `--help` text. The flags that actually keep a 6 GB card alive are
`--reserve-vram`, `--vram-headroom` (DynamicVRAM headroom) and disabling smart
memory/cache. If DynamicVRAM misbehaves, use
`--disable-dynamic-vram --lowvram` instead.

## Graph

Eleven core nodes, no custom nodes:

| node | setting |
| --- | --- |
| `UNETLoader` | `moss_image_sft_turbo_int8_convrot`, `weight_dtype=default` |
| `LoraLoaderModelOnly` | `moss-pixelart-v.0.3`, strength **1.0** |
| `CLIPLoader` | `qwen3.5_9b_w4a8_gptq`, type **`moss_image`**, device default |
| `CLIPTextEncode` ×2 | prompt / empty negative |
| `EmptyFlux2LatentImage` | 512 or 768 or 1024, multiple of 64 |
| `KSampler` | **8 steps, CFG 1.0, euler, simple**, denoise 1.0 |
| `VAELoader` / `VAEDecode` | `flux2-vae_small` |
| `SaveImage` | any prefix |

For the **non-turbo SFT** checkpoint use 25–50 steps, CFG 2.5–3.0, and insert
`SkipLayerGuidanceDiTSimple` (layer `22`, start `0.01`, end `1.0`). Skip SLG for
turbo. Do not use `EmptyLatentImage` — FLUX.2 latents have 128 channels and need
`EmptyFlux2LatentImage`.

The same graph is in `assets/moss_pixelart_api.json` for `POST /prompt`.

## Workflow

```powershell
# 1. generate 4 idle sources at 64x64 logical (512 raw)
python bin\moss_generate.py --preset idle --count 4 --size 512 --out raw

# 2. optional: 128x128 logical (1024 raw) for more detail
python bin\moss_generate.py --preset idle --count 2 --size 1024 --out raw

# 3. background + 8:1 snap + optional shared 32-colour palette
python bin\moss_snap.py raw native --factor 8 --palette 32 ^
  --compare ..\current\frame_00.png
```

`moss_snap.py` flood-fills the flat background, despills the fringe, crops to the
sprite, `BOX`-downsamples by the factor, fills 1 px pinholes and drops lone
specks. `--palette` runs one k-means over **all** frames, so an animation stays on
a single palette instead of drifting per frame.

Resolution map:

| generate | native sprite | use |
| --- | --- | --- |
| 512×512 | 64×64 | props, icons, tiny sprites |
| 768×768 | 96×96 | standard character |
| 1024×1024 | 128×128 | hero / detailed character |

## Prompting

- Start with **`pxl8x`**. Without it the LoRA behaves like a style hint.
- Ask for **one sprite, centered, flat background, limited palette**. Scenery
  prompts produce full scenes; the background cutout then has to eat sky/ground
  and can bite into the character.
- Say the view: `front three-quarter`, `side view`, `top-down`. The LoRA was
  trained on 64×64 character sprites, not turnarounds.
- Keep in-image text to 1–2 block-font words; below 1024 it is unreadable.
- Do not describe anti-aliasing or gradients. They fight the grid.
- Same seed + changed prompt is a cheap variant; different seeds change the
  silhouette, so generate 4–6 and pick.

## Traps

1. **`--lowvram` is a no-op with DynamicVRAM.** Use the reserve/headroom flags;
   the word in a guide is not the same as the behaviour in this build.
2. **CFG 1 ignores the negative prompt.** For turbo, leave it empty; for SFT,
   keep `nsfw, worst quality, bad anatomy, watermark, jpeg artifact`.
3. **`moss_image` is the CLIP type, not `flux2`** — the text encoder is a stock
   Qwen3.5-9B read with MOSS's own tokenizer and hidden-state layer.
4. **The DMD/Turbo checkpoint is 8 steps.** 25 steps at CFG 1 does not add detail,
   it just costs time; CFG 3 at 8 steps blows out.
5. **Wrong latent node** (`EmptyLatentImage`) fails at decode; the FLUX.2 VAE is
   128-channel.
6. **8:1 only holds on multiples of 64.** At 1000 px the last block is partial and
   the snap leaves a soft edge column.
7. **Don't ship the raw output.** Even at 8:1 the decode has grid drift; the
   `BOX` downsample (not nearest) is what removes the sub-pixel bleed.
8. **Palette drift across frames.** Quantise the whole clip in one k-means pass,
   or frame 3 will invent a new pink. (`--palette`.)
9. **Transparency is ours, not the model's.** The model paints a background; a
   flat bg + hard flood fill is cleaner than asking for "transparent".
10. **INT8 ConvRot is experimental.** Check the output before relying on it; the
    bf16 file is the fallback at 10.2 GB (does not fit alongside the text encoder
    in 6 GB, so it streams from RAM).
11. **The model paints a ground shadow.** A soft shadow / floor line under the
    feet survives the flat-bg flood fill as an opaque bar across the bottom of
    the sprite. Crop it in Aseprite, or add a shadow pass to `moss_snap.py`,
    before shipping.

## A/B: Axolotl Knight

The comparison run on the reference machine: the older
pipeline (SD1.5 source → `bg_clean.py` → BOX downscale → shared 32-colour
k-means → `sprite_hygiene.py`) versus MOSS turbo + LoRA → `moss_snap.py`.

Result:

- The 8:1 grid **is real** — every seed's best block phase was (0,0), so a plain
  `BOX /8` of the full canvas snaps correctly.
- 512 → ~55×64 native, ~35 s; 1024 → ~105×125 native, ~65 s; both fit 6 GB.
- **Design drift is the blocker**: each seed is a *different* character. MOSS is
  a source generator for new sprites, not a way to regenerate a signed-off one.
- Native detail ceiling is ~128 px. Above that MOSS has to be upscaled, which
  defeats the point. For ≤128 px sprites MOSS is the cleanest source we have.

Rule of thumb: **new sprite at ≤128 px → MOSS txt2img; an existing design → MOSS
img2img (`moss_generate.py --init`, see art-forge-loop); a larger hero sprite →
illustration mode, then pixel by hand.**

## Files

| path | what it is |
| --- | --- |
| `bin/moss_setup.py` | download + verify the 4 model files (or use the repo's `setup/models.py` with bundle `moss`) |
| `bin/moss_generate.py` | queue the turbo graph via the ComfyUI API; `--check`, `--preset`, `--count` |
| `bin/moss_snap.py` | flat-bg cutout, 8:1 BOX snap, 1 px edge clean, shared palette, A/B sheet |
| `assets/moss_pixelart_api.json` | the same graph in API format |
