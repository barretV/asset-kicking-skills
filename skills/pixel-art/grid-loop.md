# The grid loop

This is the workflow [Pebbly’s Aseprite AI Artist](https://pixeli.pebbly.space/plugin#-the-grid-loop) popularised: represent the canvas as **text**, draw it in one MCP call, **read it back**, patch only wrong characters, look again. It beats stacking primitives for anything under ~48×48 where silhouette and frame-to-frame consistency matter.

## Format

- One string per row; one character per pixel.
- `.` = transparent.
- `legend` maps each character to `#RRGGBB` or `#RRGGBBAA`.
- Same legend characters mean the same palette entry on every `read_rows` / `draw_rows` call (stable across partial reads).

Tools: MCP `draw_rows`, `read_rows` (see `aseprite-mcp/aseprite_mcp/tools/drawing.py` and `pixel_read.py`).

## Draw pass

1. Write the **full silhouette** as rows at the target size (often one flat material colour).
2. `draw_rows(filename, layer, frame, x, y, rows, legend)`.
3. `view_sprite` on the whole frame — if the shape does not read, change the **grid**, not shading.
4. Add flats, then ramps (see `knowledge/rules/02-shading-and-light.md`), then outline — each time prefer editing via `read_rows` for regions ≤128×128.

Use shape tools (`fill_area_at`, `draw_ellipse_at`) only for large terrain, tiles, or backgrounds where a text grid is unwieldy (see desert Lua builders in `art/desert/`).

## Fix pass

1. `read_rows(filename, x, y, width, height, frame_index, layer_name)` → JSON with `rows` + `legend`.
2. Edit characters in place (move an arm by changing letters on two rows, not by drawing over with shapes).
3. `draw_rows` with the **same** `x`, `y`, and legend (add keys only if new colours appear).
4. `view_sprite` with `region=` on the edited area; `lint_sprite` if something still looks detached.

## Animation pass

1. Call MCP `animation_workflow_guide` with the right `use_case` (`character`, `idle`, `environment`).
2. `read_rows` on frame N; copy `rows`/`legend` to frame N+1 via `copy_frame` then `draw_rows` for moved parts only.
3. `compare_frames`, `get_bounds`, `render_onion_skin` — feet and head height must match the guide.
4. Keep `get_color_stats` identical across frames; quantise if a frame drifted.

## Chunking

`read_rows` caps at 128×128 pixels per call. For larger canvases, read/write in tiles with overlapping 1px if needed, keeping legend keys consistent.
