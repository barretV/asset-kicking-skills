# Pixel-art knowledge base (local)

Structured craft rules vendored from [with-pebbly/aseprite-ai-artist](https://github.com/with-pebbly/aseprite-ai-artist) (`rules/`, MIT). Refresh with `bin/sync-pebbly-rules.cmd`.

Browse online (same content, searchable): https://pixeli.pebbly.space/knowledge

## When to read what

| Task | Start here |
|------|------------|
| Any new sprite | `rules/00-core-principles.md`, then size-specific file under `30-*` |
| Palette / muddy colours | `rules/01-palette-and-color.md`, `21-limited-and-platform-palettes.md` |
| Shading looks flat | `rules/02-shading-and-light.md`, `20-color-for-pixel-art.md` |
| Silhouette weak | `rules/03-silhouette-and-form.md`, `14-readability-and-scale.md` |
| Outlines wrong | `rules/04-outlines-and-edges.md` |
| Animation | `rules/05-animation.md`, `40-*` … `45-*` by cycle type |
| Tilesets / terrain | `rules/60-*`, `61-*`, `62-*` |
| Before calling it done | `rules/07-review-checklist.md` |

Files are numbered: `0x` core craft, `1x` technique, `2x` colour, `3x` characters, `4x` animation, `5x` creatures, `6x` environments, `7x` objects, `8x` effects, `9x` style.

## Pebbly tool names → the project’s MCP

Pebbly’s plugin uses fewer tools with different names. The project’s MCP config points at **diivi/aseprite-mcp** (batch). Map like this:

| Pebbly (live plugin) | Here (batch MCP) |
|----------------------|-------------------|
| `look` preview | `view_sprite` (use `region=` to zoom) |
| `look` ascii / grid | `read_rows` → edit JSON → `draw_rows` |
| `validate` | `lint_sprite`, `get_color_stats`, `audit_animation` |
| `draw` text grid | `draw_rows` |
| rules `rules://…` | read `knowledge/rules/<file>.md` in this skill |

Do not install Pebbly’s MCP on top of batch editing the same open file — pick one mode per session (see `optional-pebbly-live.md`).
