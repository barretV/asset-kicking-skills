# Optional: Pebbly live Aseprite (second pipeline)

The default setup in this skill is **batch** `aseprite-mcp` + `pixelart.py` — good for CI, tile scripts, and hands-off builds.

[Pebbly’s `@pebbly/aseprite-ai-artist`](https://github.com/with-pebbly/aseprite-ai-artist) adds a **live** path: an Aseprite extension, undo per step, and ~18 MCP tools. Same grid loop and the same `rules/` we vendored under `knowledge/rules/`.

## When it helps

- You want to **watch** the agent paint in an open Aseprite window and Ctrl+Z.
- You want their gallery submit flow (`/aseprite:submit`) or bundled Claude Code skills.

## When to stay on batch (this repo)

- Desert/tile Lua generators, `pixelart.py build`, Godot drops in `dist/`
- Headless or agent-only runs with no GUI
- Already editing the same `.aseprite` in batch — **never** mix live extension + batch on one file

## Install (does not replace project `mcp.json` until you choose)

```powershell
npx @pebbly/aseprite-ai-artist install-extension
npx @pebbly/aseprite-ai-artist install cursor --dry-run   # inspect first
npx @pebbly/aseprite-ai-artist doctor
```

Pebbly’s installer merges into `%USERPROFILE%\.cursor\mcp.json` as `aseprite-ai-artist`. This project’s `mcp.json` keeps the local `aseprite` server for batch work. Enable only one Aseprite MCP per task.

Benchmark prompts for regression: https://pixeli.pebbly.space
