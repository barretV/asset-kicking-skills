---
name: "pixel-art"
description: "PIXEL ART PIPELINE — grid-loop draw, knowledge-backed craft, animate, export, review"
metadata:
  category: gamedev
  tools: aseprite, python
---
PIXEL ART PIPELINE — draw, animate, export, verify

Use this for any 2D sprite work: a new character or prop from a prompt, an idle/walk/attack
cycle, editing an existing sprite sheet, or shipping art into a game build.

FIRST, FIND THE SCRIPTS
This skill lives in `.agents/skills/pixel-art/` (or `~/.agents/skills/pixel-art/`).
`bin/pixelart.py` (+ `bin/pixelart.cmd` on Windows) is the build/export tool.
It needs a compiled Aseprite binary: set `ASEPRITE_PATH` to the `.exe`, or put it at
`aseprite/build/bin/aseprite.exe` under the project root, or have `aseprite` on PATH.

For AI-driven drawing, the `aseprite` MCP server (diivi/aseprite-mcp, 123 tools) is registered
via the project's MCP config. It is the better tool while drawing; this CLI is the better
tool for building.

Fresh machine? Read `SETUP.md`, install Aseprite and the MCP server, then run
`bin/verify.py` before drawing anything. To copy this skill into another repo, run
`python install.py --into <repo>` (or `--into ~/.agents` for a global install).

Companion docs in this skill (read when relevant):
- `SETUP.md` — Aseprite build, MCP install/registration, `install.py`, `verify.py`
- `MOSS.md` — **the AI source stage, and the only one** (MOSS-Image Turbo + moss-pixelart LoRA, 6 GB, 8:1 snap)
- `grid-loop.md` — text-grid draw / read / patch (Pebbly-style loop on batch MCP)
- `knowledge/README.md` + `knowledge/rules/*.md` — 60+ craft modules (MIT, from Pebbly)
- `review.md` — cold read + mechanical checks before calling work finished
- `optional-pebbly-live.md` — live Aseprite extension if you want undo-in-GUI instead of batch

TWO FACTS THAT DECIDE EVERYTHING

1. ASEPRITE HAS NO NETWORK API. There is no HTTP or WebSocket canvas control in upstream
   Aseprite, whatever a prompt claims. Both the MCP server and this CLI are wrappers over
   `aseprite.exe --batch <file> --script <tmp.lua>`. Consequences: nothing listens on a port,
   no token exists, `--batch` never opens a window, and every edit is a full process spawn
   that reads and rewrites the file. Do not hold the same .aseprite open in the GUI while an
   agent writes to it — you will lose one side's changes.

2. THE LUA API IS NOT THE CLI's UNIT SYSTEM. `Frame.duration` is float SECONDS, so
   `= 120` means 120 seconds (silently clamped to 65.535) and the exported metadata reads
   65535 ms. Milliseconds must be divided by 1000. Same class of trap: `Color("#FFEC27")`
   parses to BLACK; build components with `Color(r,g,b)` or `app.pixelColor.rgba(...)`.

ORDER OF WORK

0. Brief (open-ended prompts only). Lock canvas size, palette preset, view, light direction,
   outline style. Skim `knowledge/rules/00-core-principles.md`. For characters, read the
   matching `30-*` / `31-*` module for the target size before spending pixels.
   AI source means **MOSS, always**. Read `MOSS.md` before generating anything:
   MOSS-Image Turbo + the moss-pixelart LoRA is the default and only AI source path
   for this pipeline — a real 8:1 logical grid at ~35 s per 512. Do not reach for SD1.5,
   Flux, or any other generator unless MOSS physically cannot run on the machine; if it
   is a judgement call, route it back to the user instead of switching models.
   `bin/moss_snap.py` cuts the flat background and downsamples to the native sprite.
   Generated art is a starting point, not a finished sprite — it still goes through
   steps 3-7 below.
1. Plan the palette before the pixels. Pick a preset (`pico8`, `gameboy`, `dawnbringer16`,
   `c64`, `cga`) or generate a ramp per material. A 32x32 sprite with 40 colours reads worse
   than the same sprite with 8.
2. **Grid loop for characters and props ≤ ~48×48** (full detail in `grid-loop.md`):
   silhouette as `draw_rows` text, `view_sprite`, then `read_rows` → edit characters →
   `draw_rows` to patch. Use filled shapes only for large terrain/tiles (e.g. `art/desert/`).
3. Look after every pass. `view_sprite` returns the frames as an image with a pixel grid and
   coordinate rulers — that is the loop's eyes. `region="x,y,w,h"` zooms in. `read_rows` on
   stubborn spots. `lint_sprite` finds detached/lone pixels, `get_color_stats` catches palette drift.
4. Outline and shade deliberately: `outline_cel` for a 1px readable edge, `adjust_hsl` on a
   shadow layer, `apply_dither_gradient` for blends. One light direction, always. Follow
   `knowledge/rules/02-shading-and-light.md` (hue-shifted ramps, not flat luminance).
5. Animate on separate layers: call MCP `animation_workflow_guide` first. Key poses redrawn
   per frame; copy prior frame's grid for consistency (`read_rows` / `draw_rows`). Use
   `propagate_cels`, `tween_cel_positions_eased` / `oscillate_cel_positions` only for secondary
   motion. Check with `render_onion_skin`, `compare_frames`, `get_bounds`.
6. **Review** (`review.md` + `knowledge/rules/07-review-checklist.md`) — cold read, lint/stats,
   watch the exported GIF, report compromises.
7. Tag every clip (`idle`, `walk`, `spin`) with a direction, then export through the CLI.

EXPORT CONTRACT (what a game build consumes)

`pixelart.py build --input art --out dist` writes, per sprite:

- `<name>.png`   uniform grid sprite sheet (near-square), 1px shape padding, nearest-neighbour scale
- `<name>.json`  Aseprite JSON hash (Phaser, PixiJS, and most 2D importers read this directly;
                 `meta.frameTags` needs `--list-tags`, which the tool passes)
- `<name>_<tag>.gif` one per animation tag, for docs and quick review
- `manifest.json` engine-agnostic index: sprite size, scale, frame durations, and tags with
                 0-BASED from/to indices and an fps derived from frame durations

Frame indices in the JSON are 0-based; frame numbers in the Aseprite GUI are 1-based. Off-by-one
here is the classic "animation starts one frame late" bug.

VERIFY, THEN REPORT

- On a new machine, or after changing the Aseprite/MCP version, run `bin/verify.py`.
  It creates and builds a temp sprite and gates the install with the same checks as a
  real export.
- `pixelart.py info <file>` prints size, frame count, durations and tags. If durations are
  65535, the seconds/ms trap bit you.
- A build requires non-zero PNG bytes and parseable JSON per sprite; the tool exits non-zero if
  any sprite failed, so it can gate a rebuild.
- View the exported GIF before saying the animation works. A still answers "is the pose right";
  only the loop answers "does it play".
- `--scale 4` resizes the sprite itself (so the sheet and manifest report 64x64 for a 16x16
  coin). That is intended for asset drops, not for source editing.

TRAPS THAT EACH COST A PASS

- Lua `spr:newTag(from, to)` takes 1-BASED frame numbers (Aseprite subtracts 1 internally).
  `newTag(1, 4)` creates the 0-3 tag; `newTag(0, 4)` silently drops frame 1. JSON
  `frameTags` are 0-based.
- `--list-layers` / `--list-tags` must come BEFORE the filename, and print bare names with no
  types (layers and tags are indistinguishable). Prefer the exported JSON for metadata.
- `meta.size` in the JSON is the packed SHEET size, not the sprite size. Sprite dimensions are
  on each frame's `sourceSize`.
- `--sheet-type packed` with no explicit extent silently crams every frame into a box the size
  of the sprite, producing metadata whose rects overlap. `--sheet-columns N` with `--sheet-type
  rows` is the only layout that is deterministic without a max sheet size; the CLI uses
  `ceil(sqrt(frames))` columns and refuses to export if any two rects overlap.
- Aseprite source is source-available under its own EULA, not OSI open source: compiling for
  your own use is free and supported, redistributing the binaries is not. LibreSprite is the
  OSI-licensed fork, and the MCP tools do not target it.
- `run_lua_script` executes unrestricted Lua on the host. Treat any third-party script as
  arbitrary code, and never paste one from a sprite file you did not author.
- Batch mode reports in-script failures on stdout as `ERROR:` lines; a zero exit is not proof
  an operation worked. Verify the artifact on disk.
- Quantising a sprite whose colours already match the palette reports "Quantized 0 pixels" —
  that is success, not a skipped step.
- Palette presets only SET the palette; existing pixels keep their colours until you quantise.
- Keep generated sources in `art/`, build output in `dist/`, and never write exports over the
  `.aseprite` sources — the sheet exporter will happily overwrite a same-named file.

## GPU safety (read before any GPU job)
Small and laptop GPUs can hang or hard-reboot when GPU work stacks up (the 6 GB reference laptop did), which kills every running session. GPU jobs include MOSS/ComfyUI generation, Blender renders and bakes, headed or headless browser runs (Playwright tests, playchecks, captures), benchmarks, and Unreal/Godot editor or PIE.
- **One GPU job machine-wide.** Before starting one, check that nothing else is using the GPU: `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv`, plus running ComfyUI (`main.py`), Blender, Playwright/Chrome and other agents' sessions. If something is running, wait for it to finish. Never start a second job alongside it.
- **Cool down.** Leave about 60 s between heavy GPU jobs. Split long runs into chunks (one batch or one level at a time), not back to back.
- **Clean up.** Stop whatever you started (ComfyUI, dev servers, browsers) as soon as you are done with it.
- **Pass it on.** When you brief a subagent or a parallel session that will use the GPU, include this rule.