---
name: game-sfx
description: Make game sound effects without a sound designer - procedural retro synthesis (no GPU), CC0 library recordings, optional Stable Audio 3 Small-SFX drafts in ComfyUI, then layering and an FFmpeg finishing pass (mono, trim, fades, loudness) with a manifest of where every file came from. Use when asked for SFX, UI sounds, hits, pickups, explosions, ambience, or to clean up and level a folder of sound takes.
metadata:
  category: gamedev
  tools: python, ffmpeg, comfyui (optional)
---

# Game sound effects: source → layer → finish → log

Three sources, one finishing pass. Pick the source by the sound, not by habit.

| Sound | Best source | Why |
|---|---|---|
| UI ticks, confirms, retro pickups, lasers, jumps, power-ups | `bin/sfx_synth.py` (procedural) | Exact, tiny, repeatable, and the output is yours outright |
| Real-world impacts, debris, mechanical loops, creatures | CC0 recordings (Kenney packs, freesound.org filtered to CC0, BigSoundBank) | Recorded detail no synth or small model matches |
| Ambience, whooshes, odd textures, quick drafts of anything | Stable Audio 3 Small-SFX (optional, GPU) | Fast first drafts; layer and edit them, never ship blind |

Most good game sounds are **layers**: a body (recording or AI draft) plus a short transient (a procedural thump or noise burst) plus maybe a tail.

## GPU safety
Only the Stable Audio route uses the GPU. Run it as the only GPU job on the machine: check `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv` first, wait for other jobs (ComfyUI, Blender renders, browsers running WebGL, other agents) to finish, and stop ComfyUI when you are done. Leave about a minute between heavy GPU jobs.

## 1. Procedural (no GPU, no downloads)

```bash
python <skill>/bin/sfx_synth.py --list
python <skill>/bin/sfx_synth.py coin blip --count 6 --seed 1 --out sfx/raw
python <skill>/bin/sfx_synth.py explosion hit --count 4 --out sfx/raw
```

Presets: coin, laser, explosion, hit, jump, blip, powerup. Each has random ranges, so `--count` gives variations; `--seed` makes a batch repeatable. To add a preset, copy one in `PRESETS` and change the ranges: `f0` start pitch (Hz), `slide` octaves per second, `sustain`/`decay` seconds, `lowpass` 0..1, `punch` extra level at the start.

Other free procedural tools whose authors say the output is yours: ChipTone (CC0), Jfxr. jsfxr, Bfxr2 and rFXGen are fine in practice but do not state a licence for sounds; note which tool made each file.

## 2. CC0 recordings
- Prefer packs that state **CC0** for every file: Kenney audio packs, BigSoundBank, and freesound.org with the licence filter set to Creative Commons 0.
- Never use CC-BY-NC or "free for personal use" sounds in a game you might sell.
- Keep the source URL, author and licence of every recording in `CREDITS.md` next to the sounds, even when credit is not required.
- Ask the user before downloading anything; list the files and sources first.

## 3. Stable Audio 3 Small-SFX (optional, AI drafts)
**Tested on the 6 GB reference machine (RTX 3060 Laptop), normal 6 GB launch flags:** peak about 1.9 GB on the card (about 1.2 GB above the desktop), about 6 s for the first take, then 1.5-3 s per 1.5-4 s clip (30 takes in 69 s). Making takes is cheap; picking them is the work, so generate 3+ seeds per sound.

**Licence:** Stability AI Community License. Free for commercial use only while you (and affiliates) stay under **USD 1M annual revenue**; commercial users must register with Stability; show "Powered by Stability AI" in your credits to be safe. The text encoder (T5Gemma) is under the Gemma Terms of Use. Keep prompts, seeds and a manifest for every shipped AI sound, so you can replace them if you ever cross the threshold.

Setup (the agent does this only after the user approves the download list from `setup/models.py plan --bundles sfx-ai`):
1. The user accepts the licence on the `stabilityai/stable-audio-3-small-sfx` Hugging Face page and logs in (`hf auth login` in ComfyUI's venv).
2. `python setup/models.py fetch --bundles sfx-ai --yes` puts `stable_audio_3_small_sfx.safetensors` in `models/checkpoints` and `t5gemma_b_b_ul2.safetensors` in `models/text_encoders`. Needs ComfyUI v0.22 or newer; no custom node and no pip change.
3. **Never** `pip install` Stability's own `stable-audio-3` package into the ComfyUI venv: it pins an older torch. Give it its own venv if you ever need it.

Generate (ComfyUI running with the tier's flags):

```bash
# one sound, 3 seeds
python <skill>/bin/sa3_generate.py --prompt "heavy wooden door slam, small stone room, short tail" --seconds 2 --count 3 --out work/sa3
# a list: [{"name": "door", "prompt": "...", "seconds": 3}, ...]
python <skill>/bin/sa3_generate.py --batch prompts.json --seed 100 --count 3 --out work/sa3
python <skill>/bin/finish_sfx.py work/sa3 work/sa3_ready --format ogg
```

The graph is `assets/sa3_small_sfx_api.json` (Small-SFX checkpoint, T5Gemma via CLIPLoader type `stable_audio`, **8 steps, CFG 1, lcm, simple**). `sa3_generate.py` writes `sa3_manifest.json` with prompt, seed and timing for every take: keep it for anything you ship.

Prompting, from the first test batch (`examples/sound/ai/manifest.json` has the exact prompts):
- Write it like a sound-library entry: source, action, material, space, tail ("glass crystal shattering into many pieces, bright tinkling shards falling on stone floor, short tail").
- Impacts, shatters, whooshes, roars, creature and insect swarms, stone grinding, footsteps and explosions came out usable on the first seeds.
- The model puts the sound at the start and leaves silence after; ask for a little more length than you need and let `finish_sfx.py` trim it. A 4 s request gave about 2-2.5 s of sound.
- Bright tonal UI sounds (coin chimes, blips) came out as noisy washes. Use `sfx_synth.py` for those.
- The agent cannot hear the takes: compare spectrograms (`ffmpeg -i take.flac -lavfi showspectrumpic=s=400x160 take.png`) to drop broken or empty takes, then let the user pick by ear.

## 4. Finish (always)

```bash
python <skill>/bin/finish_sfx.py sfx/raw sfx/ready                # WAV, mono, 44.1 kHz
python <skill>/bin/finish_sfx.py sfx/raw sfx/ready --format ogg    # smaller files for the web
python <skill>/bin/finish_sfx.py sfx/raw sfx/ready --stereo        # ambience and stings
```

Per file it high-passes at 20 Hz, trims silence at both ends, fades (3 ms in, up to 50 ms out) and levels: two-pass loudnorm to -20 LUFS for clips of 1 s or more, peak -1 dBFS for shorter ones (LUFS does not work on very short sounds). It writes `manifest.json`. Mono suits 3D-positioned sounds; let the engine pan.

## 5. Layering (FFmpeg, no editor needed)

```bash
ffmpeg -i body.wav -i transient.wav -filter_complex "[1]adelay=0|0,volume=0.8[t];[0][t]amix=inputs=2:normalize=0" layered.wav
```

Line up transients by eye in any waveform view or with `adelay` in milliseconds. Then run the finish step on the layered file.

## 6. Ship checklist
- Every file has a source line in `CREDITS.md` (tool + seed, or URL + author + licence, or model + prompt + seed).
- Short repeated sounds have 3-6 variants; play them with a no-repeat shuffle and ±2 semitones of random detune in the game.
- Listen to the batch at game volume, back to back, before calling it done. A sound that is fine alone can be harsh the twentieth time.

## Files

| path | what it is |
|---|---|
| `bin/sfx_synth.py` | procedural retro SFX, standard library only |
| `bin/finish_sfx.py` | FFmpeg finishing pass and manifest |
| `bin/sa3_generate.py` | queue Stable Audio 3 Small-SFX takes on a running ComfyUI, standard library only |
| `assets/sa3_small_sfx_api.json` | the Small-SFX API graph it rewrites |
