# asset-kicking-skills

Local AI game-asset tools, packaged as skills your coding agent can set up and drive. Pixel sprites, concept art, image-to-3D, auto-rigging and animation, and sound effects, all on your own GPU. **Built and tested on a 6 GB laptop GPU.**

## The one-line setup

Open your coding agent (Claude Code, Codex, Cursor, ...) and say:

> Set up https://github.com/<you>/asset-kicking-skills on this machine. Follow its AGENTS.md.

The agent checks your hardware, picks a settings tier, **shows you every file it wants to download (source, size, licence) and waits for your OK**, installs ComfyUI and the models from their official sources, writes launch scripts tuned to your GPU, runs a smoke test and installs the skills. Nothing is downloaded without your yes, and no model weights live in this repo.

Prefer to look first? `python setup/detect.py --dry-run` prints what you have and which tier you'd get, and changes nothing.

## What you get

| Skill | What it does | GPU? |
|---|---|---|
| **art-forge-loop** | Generate → judge → refine loop with MOSS-Image in ComfyUI. Your agent grades every candidate against a score bar and keeps refining the best until it passes. Pixel art or painted illustration; masks for "fix only this spot"; SVG export. | yes |
| **pixel-art** | Real 8:1 pixel art from MOSS + a pixel LoRA, snapped to the grid, then a text-grid draw/read/patch loop in Aseprite, animation, sprite-sheet export with a JSON manifest, and 60+ craft rule modules. | for generation |
| **concept-to-3d** | Concept → TRELLIS.2 mesh → optional Hi3D detailed sculpt, then measure your Blender model against it, or clean the sculpt into a game mesh. | yes |
| **blender-anim** | SkinTokens auto-rigging of bare meshes, clip authoring in Blender with posing helpers, retargeting clips onto a resculpted body, and a verify gate that measures loop seams, left/right symmetry and foot contact. GLB export. | rigging only |
| **game-sfx** | Procedural retro SFX (no GPU), CC0 library workflow, optional Stable Audio 3 drafts, and an FFmpeg finishing pass (mono, trim, fades, loudness) with a manifest. | optional |

See [examples/](examples/) for sample outputs.

## Hardware

| Tier | GPU | Status |
|---|---|---|
| `cpu` | no NVIDIA GPU | CPU skills only (pixel-art editing, Blender, sound) |
| `6gb` | 6 GB NVIDIA (e.g. RTX 3060 Laptop) | **tested baseline** |
| `8gb`, `12gb`, `24gb` | more VRAM | extrapolated: bigger images, batches, precision |

Full settings in [TIERS.md](TIERS.md). Windows is the tested OS; Linux should work (the scripts are cross-platform); macOS is CPU-only for now. 16 GB RAM and ~40 GB of free disk recommended.

**One GPU job at a time.** Small GPUs can hang or reboot when jobs stack up; the skills and AGENTS.md enforce this.

## Licences

Repo code and docs: MIT. Every tool and model keeps its own licence; all defaults allow commercial use, some with conditions (Hi3D branding if you embed Hi3D itself, Stable Audio's USD 1M revenue cap). Non-commercial and territory-restricted options (Hunyuan3D, FLUX.1-dev, Qwen Image, ...) are excluded. Full table: [LICENSES.md](LICENSES.md). Not legal advice.

## Manual use (no agent)

```bash
python setup/detect.py --comfyui ~/ComfyUI            # system check + config
python setup/models.py plan                            # what would be downloaded
# install ComfyUI (AGENTS.md step 4), then with ComfyUI's venv python:
python setup/models.py fetch --bundles moss --yes
python setup/launcher.py --check-flags                 # tier-tuned launch scripts
python install_skills.py --global
```

## Credits

Built on ComfyUI, MOSS-Image and the moss-pixelart LoRA, TRELLIS.2, Hi3D and the Aero-Ex ComfyUI nodes, SkinTokens, Blender, Aseprite and aseprite-mcp, the Pebbly pixel-art rules, and FFmpeg. Thanks to all of them.
