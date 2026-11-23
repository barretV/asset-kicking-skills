---
name: art-forge-loop
description: Graded art iteration loop - generate pixel art, 2D illustration or painted game UI parts with local MOSS/ComfyUI, judge every candidate against a score bar (default 9.5/10), refine the best with a specific note, and repeat until each target passes or runs out of rounds. Use when asked to make, upgrade, re-imagine or "iterate until it's good" on sprites, skins, enemies, items, props or world art, or to run the forge/grading loop (optionally under /ralph-loop).
---

# Art forge loop

A generate → judge → refine loop. The GPU makes candidates. You are the grader: you look at every candidate, score it honestly, keep the best, and write the one fix that would raise it. Repeat until every target clears the bar.

Keep its discipline: honest scores, specific notes, the best version always kept. That is what makes it converge on art people call beautiful instead of drifting.

## GPU safety (read before any GPU job)
Small and laptop GPUs can hang or hard-reboot when GPU work stacks up (the 6 GB reference laptop did), which kills every running session. GPU jobs include MOSS/ComfyUI generation, Blender renders and bakes, headed or headless browser runs (Playwright tests, playchecks, captures), benchmarks, and Unreal/Godot editor or PIE.
- **One GPU job machine-wide.** Before starting one, check that nothing else is using the GPU: `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv`, plus running ComfyUI (`main.py`), Blender, Playwright/Chrome and other agents' sessions. If something is running, wait for it to finish. Never start a second job alongside it.
- **Cool down.** Leave about 60 s between heavy GPU jobs. Split long runs into chunks (one batch or one level at a time), not back to back.
- **Clean up.** Stop whatever you started (ComfyUI, dev servers, browsers) as soon as you are done with it.
- **Pass it on.** When you brief a subagent or a parallel session that will use the GPU, include this rule.

## Rules
- `<skill>` below means this skill's folder, e.g. `~/.claude/skills/art-forge-loop` or `<project>/.claude/skills/art-forge-loop`.
- Works in any project. Run the script from the project root; job paths are relative to it.
- Generation uses MOSS-Image Turbo + the moss-pixelart LoRA on local ComfyUI (port 8188). Check it with `curl -s localhost:8188/system_stats`. If it isn't up, start it in the background with the launcher `setup/launcher.py` wrote for this machine's tier: `<ComfyUI>/run_asset_kit.bat` (Windows) or `run_asset_kit.sh`. The 6 GB profile is `main.py --lowvram --reserve-vram 0.7 --vram-headroom 0.5 --disable-smart-memory --cache-none`.
- The ComfyUI folder comes from `$COMFYUI_DIR` or `comfyui_dir` in `~/.asset-kicking-skills/config.json` (written by `setup/detect.py`).
- The MOSS tools (generate, snap to the 8:1 pixel grid, hygiene) are bundled in `scripts/moss/`. A project's own `art/pipeline/bin/` copy wins if it has one; `FORGE_MOSS_BIN` overrides both. Needs Python with Pillow and numpy.
- The GPU runs **one gen at a time** (on every tier: batch size grows with VRAM, parallel jobs do not). Always `wait` before starting a `gen`.
- Run `gen` in the background. Judge while it runs; never sit idle waiting for it.
- Keep job folders in a scratch or gitignored folder (e.g. `work/forge/<job>`). Never commit, deploy or wire art into the game unless the user asks.
- Never delete candidates. `picks.json` points at the best one, and nothing is lost.

## 1. Set up a job
Create `work/forge/<job>/job.json`. All paths are relative to the project root.

```json
{
  "bar": 9.5,
  "max_rounds": 10,
  "bar_text": "what a 9.5 means for THIS job (see below)",
  "targets": {
    "ember_lord|frog": {
      "prompt": "cute chibi green frog hero with two big round shiny eyes ..., wearing legendary EMBER LORD armour: ...",
      "init": "work/forge/skins/init/frog-base.png",
      "ref": "work/forge/skins/init/frog-base.png",
      "note": "optional first-round extra"
    }
  }
}
```

**Required for each target:**
- `prompt` is the subject: species plus theme.
- `init` is the image img2img starts from. Use the approved or current art, cropped to its content.

**Optional for each target:**
- `ref` is shown as the first column when judging. It defaults to `init`.
- `note` is an extra for the first round.

**Optional settings, with their defaults:**

| Setting | Default |
|---|---|
| `seeds` | 2 |
| `size` | 768 |
| `init_scale` | 8 |
| `first_denoise` | 0.66 |
| `polish_denoise` | 0.45 |
| `fine_denoise` | 0.38 |
| `fine_at` | 9.3 |
| `speck` | 60 px |

`style` wraps every prompt; `{prompt}` marks where the target's prompt goes. The default style is 16-bit SNES pixel art on a lavender background.

**Writing a good prompt:**
- Name the identity features that must survive, such as "huge glossy black eyes with white sparkle highlights exactly like the original" or "soft pale lavender feathers with a cream face disc".
- Then add the theme in concrete nouns: crown, cape, materials, a 3-colour palette.
- Never ask for things you don't want. "Visor" draws goggles over the eyes, and "floating leaves" fights a "no leaves" note.
- For several variants of one subject, write the species text once and the theme text once, then combine them.

## 1b. Pixel or illustration
`"mode": "pixel"` (default) uses the moss-pixelart LoRA, snaps to the 8:1 grid and 32 colours, and removes specks.

`"mode": "illustration"` is for regular 2D art: painted or cel-shaded sprites, portraits, card art and icons.
- The same MOSS turbo model with the pixel LoRA off (`lora` 0).
- A smooth upscale of the init, then a background cutout to transparency, downscaled to `out_px` (384).
- Illustration defaults: `size` 1024, an illustration `style` and `bg_tol` 38. Set `"lora"` above 0 only to blend in some pixel look.
- A pixel-art init needs `first_denoise` of about 0.7–0.8 to become painted. A painted init can polish at 0.35–0.45, as in pixel mode.
- Grade line quality, readable silhouette, consistent lighting and staying on-model, instead of grid cleanliness.
- If `rembg` is installed (`pip install "rembg[cpu]"`, which downloads the 176 MB isnet-anime model on first use), its AI character matte is combined with the colour cutout: a pixel stays only if both call it character. This catches shaded background pockets that colour rules miss. It runs on the CPU.
- A pocket the model painted with its own outline (a cape or scarf) is a design fault, not background. Fix it in the note, for example "no cape".
- The cutout also removes enclosed background pockets (between a tail and a body, under an arm) within `hole_tol` (32) of the background colour. Lower it if a character's own colour is close to the lavender background.

## 1b-ui. Game UI art (frames, ribbons, medallions, icons)
For menus and HUDs, read `UI.md` in this skill first: painted parts from rough code-made inits, one material language, no baked text, glow and states added in the engine, and a mechanical layout check. `examples/ui/` in the asset-kicking-skills repo shows the result.

## 1c. SVG export
`python <skill>/scripts/forge_loop.py <job> svg` writes `<job>/svg/<target>.svg` for every pick.
- **Pixel mode:** an exact vector copy, one rect per colour run with crisp edges. It is identical to the PNG at 1:1 and sharp at any size, with no dependencies.
- **Illustration mode:** a vector trace through `vtracer` (`pip install vtracer`, ask before installing). Cel-shaded art traces well. Soft gradients become colour bands, so check the result.

## 1d. Fixing only the marked spots (masks)
When the owner has drawn over the bad areas of an image, repaint only those areas and keep everything else.
- **Where masks come from:** a review page with a "Mark bad spots" pen (any small local page that saves a PNG per image works), whose `reviews.json` entries gain `"marks": {"<image path>": "masks/<id>.png"}`. A mask is a PNG at the image's own pixel size. Any non-transparent pixel is marked.
- **Set the target:** set `init` to the image the marks were drawn on, `mask` to the mask path, and `note` from the owner's comment plus what the marks show. Optionally set `mask_grow` (default 1 px for pixel art, 4 for illustration).
- **What happens:** after each generation, `apply_mask` aligns the new image onto the init by its unmarked area. It takes the new pixels only inside the grown mask and keeps the init's pixels everywhere else. Transparent new pixels erase, so marked specks and leftover background are removed. The result stays on the init's canvas, so the same mask still lines up in later rounds.
- **Denoise:** use a higher value than a polish, 0.5–0.66. Only the marked area is kept, so the model may change it freely. Judge only the marked area, plus whether the seam blends.
- **Before judging:** read the mask over the image (or the review page overlay) so you know exactly what the owner meant. Their comment says why; the mask says where.
- **Building a review page:** a tiny local server with a `/mask` endpoint that saves the PNG, and a draw dialog over each image with strokes, Undo, Clear all and Save, is enough.

## 2. The loop, one pass
```bash
python <skill>/scripts/forge_loop.py work/forge/<job> wait      # IDLE or BUSY (blocks up to 9 min)
python <skill>/scripts/forge_loop.py work/forge/<job> sheets    # sheets/sheet-NN.png, 7 targets each
python <skill>/scripts/forge_loop.py work/forge/<job> status
```
1. **Start the GPU.** If `wait` says IDLE and `status` shows `to_generate > 0`, run `gen` in the background:
   `PYTHONUNBUFFERED=1 python -W ignore <skill>/scripts/forge_loop.py work/forge/<job> gen`
   - Round 1 covers targets with no pick.
   - Round N+1 covers every pick that is not final, starting from its `path`.
2. **Judge.** Read every sheet. Each row shows the ref, the best so far, and the new candidates.
3. **Write verdicts** into `picks.json`, one entry per target:
   ```json
   "ember_lord|frog": {"path": ".../r4-s4041.png", "score": 9.2, "round": 4,
                       "note": "one specific fix", "denoise": 0.45, "final": false}
   ```
   - `round` is the newest round you judged. It must be set, or the target never advances.
   - `path` is the best image so far. If every new candidate is worse, keep the old path.
   - Set `final: true` when the score reaches the bar, or when round `max_rounds` has been judged. In that case keep the best.
4. **Report.** After each pass, run `report` and give the user its first lines: N of M good, how many left, the lowest scores and their notes.
5. **Repeat** until `status` prints `ALL FINAL`.

## 3. Grading (the part that matters)
Score against the job's `bar_text`. For characters, cosmetics and skins, a 9.5 means **all** of these hold:
- **Instantly the original character:** same colours, face, eye style, and signature features (hat, shell, ears, gills).
- **The theme reads in one glance, and it looks premium,** like something people would pay for. Not a shirt recolour.
- **Clean clusters and one outline,** with no stray specks, mud or noise.
- **It fits the size budget,** with nothing clipped.
- **Clean cutout (illustration mode): an automatic fail.** Sheets are drawn on vivid magenta so leftovers stand out. Before scoring, scan every gap (between tail and body, under arms, between legs, around scarves and capes) and the outline for:
  - leftover background or pale pockets;
  - ghost outlines where a pocket was removed;
  - white or lavender halos;
  - semi-transparent (faded) parts.

  Any one of these caps the score below the bar, however good the art is. Note it ("background pocket between tail and body", or "no cape, no scarf" when it is a painted shape) and re-roll. Cleanup can't remove a painted shape, and it can miss small enclosed slivers.

Calibration:

| Score | Meaning |
|---|---|
| 7.8 | Plain recolour |
| 8.5 | Good theme, but weak identity or plain |
| 9.0 | Strong, with one clear flaw |
| 9.3 | Polish-only issues |
| 9.5 | You'd ship it as a paid item |

Be honest. Never round up to escape the loop.

## 4. Steering with `note` and `denoise`
- **Polish (score ≥ 9.3):** denoise 0.38, and the note names the last flaw.
- **Fix one thing (8.5–9.2):** denoise 0.45, and the note names that thing.
- **Faces drift** (squinting eyes, squashed faces): drop to 0.32 and add "big wide-open eyes exactly like the original".
- **Stuck feature** (a hat that won't swap, goggles that keep coming back, a colour that won't change): polishing can't fix it. Redesign:
  - set `best` to the current best path;
  - set `path` to a fresh init (the base art, or a rough code-made mock of the change);
  - set `denoise` to 0.66.

  The sheet keeps showing `best`. If the redesign loses, set `path` back to `best`.
- **Same failure on every target:** the fault is in the prompt, not the image. Fix `prompt` or `style` in job.json. It applies from the next round.

## 5. Running it unattended
Under `/ralph-loop`, make each iteration one pass of section 2. Use `wait` instead of sleeping. Use a completion promise that is only true when `status` prints `ALL FINAL`.

The finished picks are the deliverable. Put them on the review page or in a sheet for the owner's final call.
