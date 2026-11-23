# AGENTS.md: set up asset-kicking-skills on this machine

You are a coding agent (Claude Code, Codex, Cursor or similar) and the user has pointed you at this repo. Your job: get local AI game-asset tools working on **their** machine, safely, then install the skills so they can use them. Follow these steps in order. Do not skip the confirmation steps.

**Ground rules**
- **Ask before every download or install.** Show what, from where, how big and under what licence, and wait for a clear yes. A yes covers only the list you showed.
- **Official sources only:** github.com repos and huggingface.co repos named in `setup/models.json` and below. Never mirrors, re-uploads or random installers.
- **Weights are never committed** to this repo or the user's projects. They live in the ComfyUI folder.
- **One GPU job at a time**, machine-wide (see "GPU safety" below). Small GPUs can hang or reboot under stacked load.
- Never put the user's name, email, paths or tokens into anything you publish, commit to this repo, or send to a web service.
- If something fails, stop and report the exact error. Do not "fix" it by switching to a different model, a cloud service, or `pip install`-ing over the ComfyUI venv's torch/numpy.
- Run long commands (installs, downloads, generation) in the background and keep the user posted.

---

## Step 1: system check (read-only)

Needs Python 3.8+ to run (ComfyUI itself needs 3.10+; 3.12 recommended). If there is no Python, ask the user to install it from python.org (Windows: tick "Add to PATH") and stop until they have.

```bash
python setup/detect.py --dry-run
```

It prints the OS, GPU and VRAM (from `nvidia-smi`), RAM, free disk, Python, Blender, git, FFmpeg, Aseprite, any ComfyUI it can see, and a line like:

```
TIER: 6gb  -  6 GB VRAM (tested baseline, e.g. RTX 3060 Laptop)
```

Show the user the summary and the tier. Explain any `WARNING` lines in plain words. Tiers are in [TIERS.md](TIERS.md); only `6gb` is tested, the others are extrapolated.
- No NVIDIA GPU (tier `cpu`): only the CPU skills work (pixel-art grid loop, Blender clips and verification, sound). Say so and offer to set up just those.
- macOS / AMD: same as `cpu` for now.

## Step 2: decide with the user

Ask (one message, with defaults):
1. **Which skills?** Default: all. `art-forge-loop` + `pixel-art` need the `moss` bundle; `concept-to-3d` needs `moss`, `trellis2` and optionally `hi3d`; `blender-anim` needs `skintokens` (only for rigging bare meshes) and Blender; `game-sfx` needs nothing (FFmpeg) and optionally `sfx-ai`.
2. **Where should ComfyUI live?** Default: an existing ComfyUI if detect found one, else `~/ComfyUI` (Windows: `%USERPROFILE%\ComfyUI`). A path with no spaces, on a disk with room (see the model total in step 1).
3. **Where should the skills go?** Default: global (`~/.claude/skills` and `~/.agents/skills`), or into one game project.

Then write the config:

```bash
python setup/detect.py --comfyui <ComfyUI folder>
```

This writes `~/.asset-kicking-skills/config.json` (tier, ComfyUI folder, launch flags, tool paths). The skills read it. If the user has a GPU lock folder shared between agents, add `"gpu_lock_dir": "<folder>"` to that file.

## Step 3: confirm the download list (required)

```bash
python setup/models.py plan --bundles <comma list> --comfyui <ComfyUI folder>
```

(`--all` instead of `--bundles` lists every optional bundle that fits the tier.) It prints a table: every file, its destination folder, its source repo, size, licence, whether commercial use is allowed, and whether it is already on disk; then custom nodes, notes and the total. **Paste that table to the user**, add the software from step 4 that is not installed yet (ComfyUI ~1 GB with its venv, PyTorch ~3 GB, Blender ~1 GB, Aseprite, FFmpeg), and point out:
- anything that is not plain "yes" for commercial use (see [LICENSES.md](LICENSES.md));
- gated files (Stable Audio needs the user to accept a licence on Hugging Face and log in);
- the total download and free disk.

Wait for a yes. If they drop bundles, re-run `plan` with the new list and confirm again.

## Step 4: install the software (after the yes)

Skip anything already present. Use each tool's official installer or repo.

**Blender 4.4+** (blender-anim, concept-to-3d): https://www.blender.org/download/ (Windows: `winget install BlenderFoundation.Blender`; Linux: the official tarball or your distro's package if it is 4.4+). Put it on PATH or set `BLENDER_PATH`.

**FFmpeg** (game-sfx): Windows `winget install Gyan.FFmpeg`; macOS `brew install ffmpeg`; Linux `sudo apt install ffmpeg` (or your distro's equivalent).

**git**: Windows `winget install Git.Git`; Linux/macOS from the package manager.

**Aseprite** (pixel-art export and grid loop): bought (Steam / aseprite.org) or compiled from source for personal use; see `skills/pixel-art/SETUP.md`. Its source licence does not allow redistributing builds. LibreSprite (GPL) is a free fork but the pixel-art MCP tools target Aseprite.

**ComfyUI** (everything that generates). Use the official repo and the official PyTorch index:

```bash
git clone https://github.com/Comfy-Org/ComfyUI <ComfyUI folder>
cd <ComfyUI folder>
python -m venv venv
# Windows: venv\Scripts\python.exe   Linux: venv/bin/python   (call it VPY below)
VPY -m pip install --upgrade pip
# PyTorch with CUDA. Pick the CUDA build your driver supports: nvidia-smi shows "CUDA Version: X.Y".
# 12.8 or newer -> cu128 ; 12.6 -> cu126. See https://pytorch.org/get-started/locally/
VPY -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
VPY -m pip install -r requirements.txt
```

ComfyUI must be **0.42 or newer** for Hi3D, about **0.45** for native TRELLIS.2 and MOSS-Image (it already was on the reference machine), and **0.22 or newer** for Stable Audio 3. With an older existing install, ask before `git pull`: an update can break the user's other custom nodes.

**Custom nodes** (only for the bundles chosen; commits are the tested pins from `setup/models.json`):

```bash
cd <ComfyUI folder>/custom_nodes
# skintokens bundle
git clone https://github.com/Aero-Ex/ComfyUI-SkinTokens && git -C ComfyUI-SkinTokens checkout 92d844d
VPY ComfyUI-SkinTokens/install.py      # pip-installs its deps into the venv and into Blender's bundled Python
# hi3d bundle (install only this Hi3D pack; forks clash)
git clone https://github.com/Aero-Ex/ComfyUI-Hi3D && git -C ComfyUI-Hi3D checkout 227d18f
```

Do **not** `pip install -r ComfyUI-SkinTokens/requirements.txt`: it pins `numpy<2.0` and would downgrade the venv. Its `install.py` installs the same packages without the numpy pin. It also tries `pip install bpy`, which may fail; that is fine (it falls back to the system Blender).

**Python packages for the skills' own scripts** (outside ComfyUI): `pip install pillow numpy` for whichever Python runs the skills. Optional: `pip install "rembg[cpu]"` for art-forge-loop's illustration cutout (downloads a 176 MB model on first use; ask first), `pip install vtracer` for SVG traces.

## Step 5: download the weights (after the yes)

```bash
<VPY> setup/models.py fetch --bundles <the approved list> --comfyui <ComfyUI folder> --yes
<VPY> setup/models.py check --bundles <the approved list> --comfyui <ComfyUI folder>
```

Use ComfyUI's venv Python (it has `huggingface_hub`). Files go to `<ComfyUI>/models/<folder>/`; sizes are checked, and sha256 where known. For `sfx-ai`, the user first accepts the licence at https://huggingface.co/stabilityai/stable-audio-3-small-sfx and runs `<venv>/Scripts/hf auth login` (or `venv/bin/hf`) themselves; never handle their token.

If `fetch` stops with "could not find exactly one ...", the upstream repo moved a file. Show the user what it found and ask.

## Step 6: launchers and a smoke test

```bash
python setup/launcher.py --check-flags
```

Writes `<ComfyUI>/run_asset_kit.(bat|sh)` (general) and `run_asset_kit_rigging.(bat|sh)` (SkinTokens) with the tier's flags, dropping any flag this ComfyUI build does not know. Then, **as the only GPU job**:
1. Start `run_asset_kit` in the background; wait until `curl -s http://127.0.0.1:8188/system_stats` answers.
2. `python skills/pixel-art/bin/moss_generate.py --check` (models present), then one image: `python skills/pixel-art/bin/moss_generate.py --preset idle --count 1 --size 512 --out work/smoke`.
3. Stop ComfyUI. Show the user the image.
4. If Blender was installed: `blender -b --python-exit-code 1 --python-expr "import bpy; print('blender ok')"`.
5. If Aseprite is set up: `python skills/pixel-art/bin/verify.py`.
6. `python skills/game-sfx/bin/sfx_synth.py coin --out work/smoke` (no GPU).

Out of memory? Re-run `setup/detect.py --tier <one lower>` and `setup/launcher.py`, or try the tier's `comfyui_args_fallback` from `setup/tiers.json`.

## Step 7: install the skills

```bash
python install_skills.py --global                 # or: --project <path to their game repo>
```

Tell the user to start a new agent session so the skills load, and give them a one-line example per skill:
- "Use art-forge-loop to make a 64x64 pixel sprite of a moss golem, bar 9.0."
- "Use concept-to-3d to turn work/forge/golem/picks into a 3D sculpt."
- "Use blender-anim to rig this GLB and add idle and walk clips."
- "Use game-sfx to make 5 coin pickups and a door slam."

## Step 8: report

Summarise: tier, what was installed and where, total disk used, what was skipped and why, anything untested on their tier, and the licence points they must remember (from LICENSES.md, the "conditions" column).

---

## GPU safety (pass this to any sub-agent that uses the GPU)

- **One GPU job machine-wide.** GPU jobs: ComfyUI generation (images, 3D, audio, rigging), Blender GPU renders and bakes, browsers running WebGL/WebGPU (tests, captures), game engines, benchmarks. Before starting one, check `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv` and running processes; wait if anything else is on the GPU.
- If `gpu_lock_dir` is set in the config, create a lock file there named after your job before starting and delete it when done.
- **Cool down** about 60 s between heavy jobs; split long runs into chunks.
- **Clean up:** stop ComfyUI, Blender and browsers you started as soon as you are done.

## Repo map

| Path | What |
|---|---|
| `setup/detect.py` | read-only system check, tier pick, writes the config |
| `setup/tiers.json` | per-tier ComfyUI flags and model settings ([TIERS.md](TIERS.md) is the readable version) |
| `setup/models.json` | every model file: source, size, licence, sha256 |
| `setup/models.py` | `plan` (confirm list), `check`, `fetch --yes` |
| `setup/launcher.py` | writes the tier's ComfyUI launch scripts |
| `install_skills.py` | copies `skills/*` to where agents load them |
| `skills/` | `art-forge-loop`, `pixel-art`, `concept-to-3d`, `blender-anim`, `game-sfx` |
| `examples/` | small sample outputs |
| [LICENSES.md](LICENSES.md) | every tool and model, commercial-use flags |
