# Review before “done”

Adapted from Pebbly’s `pixel-critic` / `rules/07-review-checklist.md`, using this repo’s batch MCP tools.

## 1. Cold read (no excuses)

Before mechanical checks, write one sentence: **what does this look like to someone who was not told the prompt?** If that sentence does not match the brief, fix silhouette or composition first.

## 2. Mechanical

Run on the current frame or full tag range:

- `get_color_stats` — off-palette or runaway colour count
- `lint_sprite` — lone pixels, detached parts
- For animation: `audit_animation`, varied `set_frame_duration`, tags present

## 3. By eye

- `view_sprite` at 1× with grid; `region=` for face/hands/feet
- Exported GIF (`export_tag` or `pixelart.py build`) for timing — stills lie about motion

## 4. Report like a critic, not a cheerleader

Deliver:

- What you checked (tools + GIF)
- Blockers vs compromises (“helmet reads as hood at 1×; kept for pixel budget”)
- Do **not** claim success until GIF/view confirms

Optional hardening (Pebbly 0.8+): after a fix, compare old vs new with `view_sprite` side by side; keep the change only if the cold read improves.

## 5. Knowledge

If something “looks generated”, see `knowledge/rules/00-core-principles.md` § “What makes generated pixel art look generated” and the matching module in `knowledge/README.md`.
