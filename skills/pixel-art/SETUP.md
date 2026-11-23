# Set up the pixel-art pipeline

This skill is the agent-facing half of a local Aseprite pipeline. It needs two
things on the machine: a compiled `aseprite.exe` and the `aseprite` MCP server
(`diivi/aseprite-mcp`). The skill itself is portable; the paths below are the
known-good Windows setup.

Finished layout:

```text
<ROOT>/
  aseprite/                  Aseprite source + build
  deps/skia/                 prebuilt Skia
  aseprite-mcp/              MCP server + .venv
  .agents/skills/pixel-art/  this skill
  art/                       .aseprite sources
  dist/                      exported PNG/JSON/GIF/manifest
  build-aseprite.cmd
```

`<ROOT>` is a repo or a workspace with no spaces in its path. For a global skill
install, the scripts resolve Aseprite from `ASEPRITE_PATH` or the current project's
`aseprite/build/bin/aseprite.exe`.

## 0. Quick check

If you already have a working install:

```powershell
$env:ASEPRITE_PATH = "<ROOT>\aseprite\build\bin\aseprite.exe"
py -3 .agents\skills\pixel-art\bin\verify.py
```

It creates a temp 32x32 sprite, tags it, builds the sheet/GIF/manifest, and checks
the metadata. If it passes, you are done. If not, continue.

## 1. Add Aseprite

Preferred: build the known-good version, v1.3.18.6, with MSVC and the matching
Skia m124 prebuilt.

Prerequisites: Visual Studio 2022 Build Tools with "Desktop development with C++",
CMake, Ninja, Git, and about 10 GB free.

```powershell
winget install --id Git.Git -e --source winget
winget install --id Kitware.CMake -e --source winget
winget install --id Ninja-build.Ninja -e --source winget
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

```powershell
cd <ROOT>
git clone https://github.com/aseprite/aseprite.git
cd aseprite
git checkout v1.3.18.6
git submodule update --init --recursive
```

Download Skia m124 for Windows x64:

```powershell
mkdir <ROOT>\deps -Force
Invoke-WebRequest `
  -Uri https://github.com/aseprite/skia/releases/download/m124-08a5439a6b/Skia-Windows-Release-x64.zip `
  -OutFile <ROOT>\deps\Skia-Windows-Release-x64.zip
Expand-Archive <ROOT>\deps\Skia-Windows-Release-x64.zip -DestinationPath <ROOT>\deps\skia -Force
Test-Path <ROOT>\deps\skia\out\Release-x64\skia.lib
```

The last command must print `True`. If the archive nested a `skia\skia` folder, move
it so `deps\skia\out\Release-x64\skia.lib` is exact.

Copy `assets/build-aseprite.cmd` to `<ROOT>\build-aseprite.cmd`, then:

```powershell
cmd /c <ROOT>\build-aseprite.cmd
<ROOT>\aseprite\build\bin\aseprite.exe --version
```

The build takes 20-45 minutes. `--version` must print 1.3.18.6.

Shortcut: a recent Aseprite from Steam or an installer also works. Point
`ASEPRITE_PATH` at its `aseprite.exe`; it must support `--sheet`, `--data`,
`--format json-hash`, `--sheet-type`, `--shape-padding`, and `--list-tags`.

## 2. Add the MCP server

The MCP server is what gives the agent `draw_rows`, `read_rows`, `view_sprite`,
`lint_sprite`, animation tools, and exports. It requires Python 3.13+.

```powershell
cd <ROOT>
git clone https://github.com/diivi/aseprite-mcp.git
cd aseprite-mcp
git checkout a89b205
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -c "import aseprite_mcp; print('ok')"
```

If the pinned commit is gone, use current `main` and confirm the grid-loop tool
names still exist.

## 3. Register the server

OpenCode V2 (`opencode.json`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "aseprite": {
        "type": "local",
        "command": [
          "<ROOT>/aseprite-mcp/.venv/Scripts/python.exe",
          "-m",
          "aseprite_mcp"
        ],
        "environment": {
          "PYTHONPATH": "<ROOT>/aseprite-mcp",
          "ASEPRITE_PATH": "<ROOT>/aseprite/build/bin/aseprite.exe"
        }
      }
    }
  }
}
```

Claude Desktop / Claude Code (`mcp.json`):

```json
{
  "mcpServers": {
    "aseprite": {
      "command": "<ROOT>/aseprite-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "aseprite_mcp"],
      "env": {
        "PYTHONPATH": "<ROOT>/aseprite-mcp",
        "ASEPRITE_PATH": "<ROOT>/aseprite/build/bin/aseprite.exe"
      }
    }
  }
}
```

Templates are in `assets/mcp.json.template` and
`assets/opencode.mcp.json.template`. Use forward slashes or doubled backslashes in
JSON. Reload the agent and confirm the `aseprite` server connects with about 123
tools. Then call `create_canvas`, `draw_rows`, and `view_sprite` once to prove image
results are visible to the model.

## 4. Install the skill

From this skill directory:

```powershell
python install.py --into <ROOT>
```

That writes `<ROOT>/.agents/skills/pixel-art`. Use `--claude` for
`.claude/skills/pixel-art`, or `--into ~/.agents` for a global install. `--force`
replaces an existing copy.

The skill is self-contained apart from the two external pieces above. Copying it does
not build Aseprite or install the MCP server.

## 5. Verify

```powershell
$env:ASEPRITE_PATH = "<ROOT>\aseprite\build\bin\aseprite.exe"
py -3 <ROOT>\.agents\skills\pixel-art\bin\verify.py
```

Add `--mcp-python <ROOT>\aseprite-mcp\.venv\Scripts\python.exe` if the venv is not
found automatically. The check is a measurement, not an opinion:

| check | what it proves |
| --- | --- |
| files/rules | the skill and 60+ craft modules are present |
| aseprite | the binary resolves and reports 1.3.x |
| sprite | `pixelart.py new` writes a 32x32, 4-frame sprite |
| pixels/tag | Lua can paint frames and tag 0-3 |
| info | durations are 120 ms, not 65535 |
| png/gif | both exports are non-empty |
| json | 4 frames, tag 0-3, sourceSize 32x32 |
| manifest | 0-based tag, 4 frames, 8.33 fps |
| mcp | the MCP package imports (optional) |

## Troubleshooting

- **`cl.exe` not found** — call `vcvars64.bat` in the same shell as CMake/Ninja, or
  run `build-aseprite.cmd` which does it for you.
- **Skia link errors** — the Skia build must match the Aseprite tag (m124 for
  v1.3.18.6). Check `deps\skia\out\Release-x64\skia.lib` exists.
- **`durations [65535, ...]`** — Lua `Frame.duration` is seconds. Use `ms / 1000.0`.
- **Tag starts one frame late** — Lua `spr:newTag(from, to)` is 1-based; JSON tags are
  0-based. `newTag(1, 4)` is the 0-3 tag.
- **`Color("#RRGGBB")` is black** — build `Color(r, g, b)` or
  `app.pixelColor.rgba(...)` instead.
- **Sheet frames overlap** — use `--sheet-type rows --sheet-columns N`; do not use
  `packed` without an explicit extent.
- **MCP reports 0 tools** — check the command path, `PYTHONPATH`, and
  `ASEPRITE_PATH`; run the venv Python with `-c "import aseprite_mcp"`.
- **The same file is open in the Aseprite GUI** — close it. Batch writes and GUI
  edits will overwrite each other.

## 7. MOSS-Image AI source (default)

**Every AI-generated pixel-art source in this pipeline comes from MOSS.** The
`moss-pixelart-v0.3` LoRA renders at a real 8:1 logical grid: a 512×512 generation is
a 64×64 sprite. It needs ComfyUI (2026-10-16+),
~14 GB of weights and a 6 GB GPU. Full pipeline, sampler settings and traps are in
`MOSS.md`; the short version:

```powershell
C:\path\to\ComfyUI\venv\Scripts\python.exe bin\moss_setup.py
python bin\moss_generate.py --preset idle --count 4 --size 512 --out raw
python bin\moss_snap.py raw native --factor 8 --palette 32
```

This is independent of Aseprite and the MCP server. Install it on any machine that
will produce sprites; it is not an optional extra, it is the source stage.

## Licensing

Aseprite's source is source-available under its own EULA. Building for your own use
is fine; redistributing the binaries is not. The craft rules under
`knowledge/rules/` are MIT, vendored from
[with-pebbly/aseprite-ai-artist](https://github.com/with-pebbly/aseprite-ai-artist).
Refresh them with `bin/sync-pebbly-rules.cmd`.
