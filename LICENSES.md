# Licences of every tool and model

This repo's own code and docs are MIT ([LICENSE](LICENSE)). Everything below is third-party and keeps its own licence. None of it is redistributed here: the setup scripts download it from the official source on the user's machine, after the user approves the list.

**This is a summary, not legal advice.** Read each licence before you ship a commercial game. Checked November 2026; licences change.

Legend: ✅ commercial use OK · ⚠️ commercial use OK **with conditions** · ⛔ non-commercial or otherwise excluded.

## Software

| Tool | Used for | Licence | Commercial | Notes |
|---|---|---|---|---|
| ComfyUI | runs every model | GPL-3.0 | ✅ | GPL covers ComfyUI's code, not the images or meshes you make with it. |
| PyTorch | ComfyUI backend | BSD-3-Clause | ✅ | |
| Blender | modelling, rigging, renders | GPL-2.0-or-later | ✅ | Your .blend/.glb outputs are yours. |
| Aseprite | pixel-art editing and export | Aseprite EULA (source-available) | ✅ | Compile for your own use or buy it; you may not redistribute builds. |
| LibreSprite | optional free Aseprite fork | GPL-2.0 | ✅ | The pixel-art MCP tools target Aseprite, not LibreSprite. |
| aseprite-mcp (diivi) | agent drawing tools for Aseprite | MIT | ✅ | |
| FFmpeg | sound finishing | LGPL-2.1+ (GPL in some builds) | ✅ | Licence covers FFmpeg, not your audio. |
| huggingface_hub | downloads | Apache-2.0 | ✅ | |
| rembg (optional) | illustration cutout | MIT | ✅ | Downloads its own segmentation model on first use; check that model's card. |
| vtracer (optional) | SVG trace | MIT | ✅ | |
| ComfyUI-SkinTokens (Aero-Ex) | rigging node | MIT | ✅ | |
| ComfyUI-Hi3D (Aero-Ex) | Hi3D node | Hi3D Open License 1.0 | ⚠️ | Same terms as the Hi3D weights below. |
| StableGen (optional, not installed by setup) | projection texturing in Blender | GPL-3.0 | ✅ code / ⚠️ models | Its SDXL route is fine (see SDXL below). Its Qwen Image and Bria FIBO routes are non-commercial. Unproven on 6 GB. |

## Models (downloaded by `setup/models.py`)

| Model | Bundle | Licence | Commercial | Conditions / notes |
|---|---|---|---|---|
| MOSS-Image SFT Turbo, INT8 ConvRot repack | `moss` | Apache-2.0 | ✅ | Repack of OpenMOSS MOSS-Image (Apache-2.0). |
| Qwen3.5-9B w4a8 text encoder (Comfy-Org repack) | `moss` | Apache-2.0 | ✅ | |
| FLUX.2 small VAE (Comfy-Org MOSS-Image repo) | `moss` | Apache-2.0 (repo tag) | ✅ | Only the small VAE; no FLUX.1-dev weights are used anywhere. |
| moss-pixelart v0.3 LoRA | `moss` | Apache-2.0 | ✅ | Trigger word `pxl8x`. |
| TRELLIS.2 (int8 + shape VAE, Comfy-Org) | `trellis2` | MIT | ✅ | |
| DINOv3 ViT-L (TRELLIS.2 image encoder) | `trellis2` | DINOv3 License (Meta) | ⚠️ | Commercial use allowed; redistribution terms, indemnity and a sanctions clause apply. Used locally, never shipped. |
| BiRefNet | `trellis2` | MIT | ✅ | |
| Hi3D v1 (int8 / fp16, Aero-Ex repack) | `hi3d`, `hi3d-fp16` | Hi3D Open License 1.0 | ⚠️ | Commercial use allowed. **Generated meshes are yours** with no branding or scale licence if you ship meshes, not Hi3D itself (§9). If you integrate Hi3D weights or code into a product or service: "Powered by Hi3D 1.0" display (§7) and a separate licence above 200k MAU or USD 1M monthly revenue (§5). Acceptable Use Policy and an indemnity apply. No territory exclusions. |
| DINOv2-large | `hi3d` | Apache-2.0 | ✅ | |
| CLIP ViT-L/14 | `hi3d` | MIT | ✅ | |
| SkinTokens checkpoints (VAST-AI) | `skintokens` | MIT | ✅ | `.ckpt` files are pickles: only load them from the official repo. |
| Qwen3-0.6B config/tokenizer | `skintokens` | Apache-2.0 | ✅ | Config files only, no weights. |
| Stable Audio 3 Small-SFX | `sfx-ai` (optional) | Stability AI Community License | ⚠️ | Free commercial use **only under USD 1M annual revenue** (you and affiliates, all sources). Commercial users must register with Stability. Show "Powered by Stability AI" in credits to be safe. Gated on Hugging Face. Do not train other foundation models on outputs. Whether outputs made before crossing USD 1M stay licensed is unclear: keep a manifest so AI sounds can be replaced. |
| T5Gemma (Stable Audio text encoder) | `sfx-ai` | Gemma Terms of Use | ⚠️ | Use restrictions per Google's Gemma terms. |
| SDXL base 1.0 (only if you add StableGen) | n/a | CreativeML Open RAIL++-M | ⚠️ | Commercial use allowed with use-based restrictions. |

## Ruled out (not used, and why)

| Model / tool | Why |
|---|---|
| Hunyuan3D 2.x / Hunyuan3D-Paint | ⛔ Tencent Hunyuan Community License **does not apply in the EU, UK or South Korea**, plus extra terms at scale. Paint also needs far more than 6 GB. |
| HunyuanVideo-Foley | ⛔ Same Tencent territory exclusion. |
| MV-Adapter | Linux-only; does not run on the Windows reference machine. |
| UltraTex / FLUX.1-dev texturing | ⛔ FLUX.1-dev licence is non-commercial. |
| Qwen Image 2.1 / 2.1 Turbo (StableGen option) | ⛔ Qwen Research License, non-commercial. |
| Bria FIBO 2.0 (StableGen option) | ⛔ CC BY-NC 4.0. |
| TangoFlux, Tango 2, AudioLDM 2 | ⛔ Non-commercial (research / CC-BY-NC-SA). |
| MMAudio weights, Sony Woosh weights | ⛔ CC-BY-NC. |

## Sound sources (non-AI)

| Source | Licence | Notes |
|---|---|---|
| `skills/game-sfx/bin/sfx_synth.py` output | yours | Generated by this repo's code; no samples. |
| Kenney audio packs, BigSoundBank | CC0 | Credit not required; give it anyway. |
| freesound.org | per file | Filter to CC0. Avoid CC-BY-NC. Record author and URL per file. |
| ChipTone | CC0 output (author's statement) | |
| Jfxr | output is yours (author's statement) | |
| jsfxr, Bfxr2, rFXGen | code MIT / Unlicense / zlib; no statement on sounds | Usually treated as yours; note the tool per file. |

## Vendored in this repo

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md): pixel-art craft rules (MIT, with-pebbly/aseprite-ai-artist) and the Hi3D source workflow `pa_wf01.json` (MIT, PixelArtistry).

## Example files that are not MIT

`examples/sound/ai/*.ogg` are Stable Audio 3 Small-SFX outputs, made under the Stability AI Community License. Powered by Stability AI. Their prompts and seeds are in `examples/sound/ai/manifest.json`. Everything else in `examples/` and `docs/showcase/` falls under the repo's MIT licence.
