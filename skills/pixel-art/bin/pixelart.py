#!/usr/bin/env python3
"""pixelart - a small, scriptable front end for a locally compiled Aseprite.

Turns .aseprite sources into game-ready assets: packed sprite sheets, Aseprite
JSON hash metadata (Phaser / PixiJS / engine-agnostic), per-tag GIFs, and a
manifest a build step can consume.

Aseprite has no network API: every operation here is a batch-mode CLI call.

Usage:
  pixelart.py new  art/chest.aseprite --size 32x32 --palette pico8 --frames 4
  pixelart.py build --input art --out dist --scale 1
  pixelart.py info art/slime.aseprite
  pixelart.py gif  art/slime.aseprite --out art/slime.gif --tag idle --scale 8

Set ASEPRITE_PATH to override binary discovery.
Requires only the Python standard library (3.8+).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

def default_aseprite_candidates() -> list[Path]:
    """Likely local builds, relative to this skill or the current project."""
    here = Path(__file__).resolve()
    roots = [here.parents[4], Path.cwd()]
    out: list[Path] = []
    for root in roots:
        candidate = root / "aseprite" / "build" / "bin" / "aseprite.exe"
        if candidate not in out:
            out.append(candidate)
    return out

# PICO-8, the palette most 32x32 game sprites start from
PALETTES = {
    "pico8": [
        "#000000", "#1D2B53", "#7E2553", "#008751", "#AB5236", "#5F574F",
        "#C2C3C7", "#FFF1E8", "#FF004D", "#FFA300", "#FFEC27", "#00E436",
        "#29ADFF", "#83769C", "#FF77A8", "#FFCCAA",
    ],
    "gameboy": ["#0F380F", "#306230", "#8BAC0F", "#9BBC0F"],
    "dawnbringer16": [
        "#140C1C", "#442434", "#30346D", "#4E4A4E", "#854C30", "#346524",
        "#D04648", "#757161", "#597DCE", "#D27D2C", "#8595A1", "#6DAA2C",
        "#D2AA99", "#6DC2CA", "#DAD45E", "#DEEED6",
    ],
    "c64": [
        "#000000", "#FFFFFF", "#880000", "#AAFFEE", "#CC44CC", "#00CC55",
        "#0000AA", "#EEEE77", "#DD8855", "#664400", "#FF7777", "#333333",
        "#777777", "#AAFF66", "#0088FF", "#BBBBBB",
    ],
    "cga": [
        "#000000", "#0000AA", "#00AA00", "#00AAAA", "#AA0000", "#AA00AA",
        "#AA5500", "#AAAAAA", "#555555", "#5555FF", "#55FF55", "#55FFFF",
        "#FF5555", "#FF55FF", "#FFFF55", "#FFFFFF",
    ],
}


class ToolError(RuntimeError):
    pass


def find_aseprite() -> Path:
    env = os.environ.get("ASEPRITE_PATH")
    if env:
        p = Path(env)
        if not p.is_file():
            raise ToolError(f"ASEPRITE_PATH does not point at a file: {p}")
        return p
    for candidate in default_aseprite_candidates():
        if candidate.is_file():
            return candidate
    found = shutil.which("aseprite") or shutil.which("aseprite.exe")
    if found:
        return Path(found)
    raise ToolError(
        "Aseprite not found. Set ASEPRITE_PATH to the compiled aseprite.exe."
    )


def run(args: list[str], allow_fail: bool = False) -> str:
    exe = find_aseprite()
    proc = subprocess.run(
        [str(exe), *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not allow_fail:
        raise ToolError(f"aseprite {' '.join(args)} failed ({proc.returncode}):\n{out.strip()}")
    # Batch scripts report in-script failures on stdout as "ERROR:" lines
    for line in out.splitlines():
        if line.startswith("ERROR:"):
            raise ToolError(line[6:].strip())
    return out


PROBE_LUA = Path(__file__).resolve().parent / "frame_count.lua"


def frame_count(sprite: Path) -> int:
    """Ask Aseprite how many frames the sprite has."""
    if not PROBE_LUA.is_file():
        return 1
    for line in run(["-b", str(sprite), "--script", str(PROBE_LUA)]).splitlines():
        if line.startswith("FRAMES="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return 1
    return 1


def check_layout(meta_json: dict, sprite: Path) -> None:
    """Guard against frames packed on top of each other.

    `--sheet-type packed` without an explicit extent silently crams every
    frame into a box the size of the sprite, writing metadata whose rects
    overlap. Overlapping rects mean corrupted sprites in engine, so fail loudly.
    """
    frames = list(meta_json.get("frames", {}).values())
    rects = [f.get("frame", {}) for f in frames]
    sheet = (meta_json.get("meta", {}) or {}).get("size", {}) or {}
    sw, sh = sheet.get("w"), sheet.get("h")
    for r in rects:
        if sw and sh and (r.get("x", 0) + r.get("w", 0) > sw or r.get("y", 0) + r.get("h", 0) > sh):
            raise ToolError(f"{sprite.name}: a frame rect falls outside the {sw}x{sh} sheet")
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                    and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]):
                raise ToolError(f"{sprite.name}: sprite sheet frames overlap — refusing to export a corrupt sheet")


def export_sheet(sprite: Path, png: Path, data: Path, scale: int, padding: int) -> dict:
    png.parent.mkdir(parents=True, exist_ok=True)
    # A square-ish grid: `rows` with an explicit column count is the only
    # layout that neither overlaps frames nor needs a max sheet extent.
    cols = max(1, math.ceil(math.sqrt(frame_count(sprite))))
    run([
        "-b", str(sprite),
        "--scale", str(scale),
        "--sheet", str(png),
        "--data", str(data),
        "--format", "json-hash",
        "--sheet-type", "rows",
        "--sheet-columns", str(cols),
        "--shape-padding", str(padding),
        "--list-tags",
    ])
    if not png.is_file() or png.stat().st_size == 0:
        raise ToolError(f"no sheet written for {sprite.name}")
    meta_json = json.loads(data.read_text(encoding="utf-8"))
    check_layout(meta_json, sprite)
    return meta_json


def export_gif(sprite: Path, out: Path, tag: str | None, scale: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["-b", str(sprite)]
    if tag:
        args += ["--tag", tag]
    args += ["--scale", str(scale), "--save-as", str(out)]
    run(args)
    if not out.is_file() or out.stat().st_size == 0:
        raise ToolError(f"no GIF written for {sprite.name} (tag={tag or 'all'})")


def frame_durations(meta_json: dict) -> list[int]:
    durations = []
    for frame in meta_json.get("frames", {}).values():
        durations.append(int(frame.get("duration", 0)))
    return durations


def build_entry(sprite: Path, out_dir: Path, scale: int, padding: int, want_gif: bool) -> dict:
    name = sprite.stem
    png = out_dir / f"{name}.png"
    data = out_dir / f"{name}.json"
    meta_json = export_sheet(sprite, png, data, scale, padding)

    tags = meta_json.get("meta", {}).get("frameTags", []) or []
    durations = frame_durations(meta_json)
    entries = []
    for tag in tags:
        count = tag["to"] - tag["from"] + 1
        span = durations[tag["from"]: tag["to"] + 1] or [0]
        avg = sum(span) / len(span) if span else 0
        gif_name = None
        if want_gif:
            gif_name = f"{name}_{tag['name']}.gif"
            export_gif(sprite, out_dir / gif_name, tag["name"], scale)

        entries.append({
            "name": tag["name"],
            "from": tag["from"],
            "to": tag["to"],
            "frames": count,
            "direction": tag.get("direction", "forward"),
            "fps": round(1000 / avg, 2) if avg else None,
            "gif": gif_name,
        })

    # meta.size is the packed SHEET size; the sprite's own size lives on each frame
    frames_json = meta_json.get("frames", {})
    first_frame = next(iter(frames_json.values()), {})
    src_size = first_frame.get("sourceSize", {}) or {}
    sheet = meta_json.get("meta", {}).get("size", {}) or {}
    return {
        "name": name,
        "source": sprite.name,
        "width": src_size.get("w"),
        "height": src_size.get("h"),
        "scale": scale,
        "sheet": {"w": sheet.get("w"), "h": sheet.get("h")},
        "frames": len(durations),
        "durations_ms": durations,
        "image": png.name,
        "data": data.name,
        "tags": entries,
    }


def cmd_new(args) -> int:
    try:
        w, h = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        raise ToolError("--size must look like 32x32")

    out = Path(args.path)
    out.parent.mkdir(parents=True, exist_ok=True)

    palette = PALETTES.get((args.palette or "").lower())
    if args.palette and palette is None:
        raise ToolError(f"unknown palette '{args.palette}'; try: {', '.join(PALETTES)}")

    lines = [
        f'local spr = Sprite({w}, {h})',
        f'spr.filename = "{out.as_posix()}"',
    ]
    if palette:
        # Color("#RRGGBB") parses to BLACK in the Lua API - build r,g,b components
        colors = ", ".join(
            "Color(%d,%d,%d)" % tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
            for c in palette
        )
        lines += [
            "local pal = Palette(#spr.palettes[1])",
            f"local cols = {{{colors}}}",
            "pal:resize(#cols)",
            "for i, c in ipairs(cols) do pal:setColor(i - 1, c) end",
            "spr:setPalette(pal)",
        ]
    if args.frames > 1:
        lines.append(f"for i = 2, {args.frames} do spr:newEmptyFrame(i - 1) end")
    if args.duration:
        # Frame.duration in the Lua API is SECONDS (float); the CLI speaks ms.
        lines.append(
            f"for i, f in ipairs(spr.frames) do f.duration = {args.duration} / 1000.0 end"
        )
    lines += [
        'spr:saveAs(spr.filename)',
        f'print("OK {w}x{h} frames=" .. #spr.frames)',
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False, encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
        script = fh.name
    try:
        out_text = run(["-b", "--script", script])
    finally:
        os.unlink(script)

    print(f"created {out} ({w}x{h}, {args.frames} frame(s)"
          + (f", palette {args.palette}" if args.palette else "") + ")")
    print(f"  aseprite: {out_text.strip()}")
    return 0


def cmd_info(args) -> int:
    sprite = Path(args.sprite)
    if not sprite.is_file():
        raise ToolError(f"no such sprite: {sprite}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        meta_json = export_sheet(sprite, tmp_path / "s.png", tmp_path / "s.json", 1, 0)
    meta = meta_json.get("meta", {})
    durations = frame_durations(meta_json)
    frames_json = meta_json.get("frames", {})
    first_frame = next(iter(frames_json.values()), {})
    src = first_frame.get("sourceSize", {}) or {}
    sheet = meta.get("size", {}) or {}
    print(f"{sprite.name}: {src.get('w')}x{src.get('h')}, {len(durations)} frame(s), "
          f"durations {durations}, packed sheet {sheet.get('w')}x{sheet.get('h')}")
    for tag in meta.get("frameTags", []) or []:
        print(f"  tag {tag['name']}: frames {tag['from']}-{tag['to']} ({tag.get('direction')})")
    return 0


def cmd_gif(args) -> int:
    sprite = Path(args.sprite)
    if not sprite.is_file():
        raise ToolError(f"no such sprite: {sprite}")
    out = Path(args.out)
    export_gif(sprite, out, args.tag, args.scale)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_build(args) -> int:
    src = Path(args.input)
    out_dir = Path(args.out)
    if not src.is_dir():
        raise ToolError(f"input directory not found: {src}")

    sprites = sorted(p for p in src.iterdir() if p.suffix.lower() == ".aseprite")
    if not sprites:
        raise ToolError(f"no .aseprite files in {src}")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "tool": "pixelart",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aseprite": str(find_aseprite()),
        "scale": args.scale,
        "sprites": [],
    }

    failures = 0
    for sprite in sprites:
        try:
            entry = build_entry(sprite, out_dir, args.scale, args.padding, not args.no_gif)
        except ToolError as exc:
            failures += 1
            print(f"FAIL {sprite.name}: {exc}", file=sys.stderr)
            continue
        manifest["sprites"].append(entry)
        tags = ", ".join(t["name"] for t in entry["tags"]) or "no tags"
        print(f"ok   {sprite.name}: {entry['frames']}f {entry['width']}x{entry['height']} -> "
              f"{entry['image']} + {entry['data']} [{tags}]")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nmanifest: {out_dir / 'manifest.json'}")

    if failures:
        print(f"{failures} sprite(s) failed", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pixelart", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="create a blank sprite")
    p_new.add_argument("path")
    p_new.add_argument("--size", default="32x32")
    p_new.add_argument("--palette", default=None, help=f"one of: {', '.join(PALETTES)}")
    p_new.add_argument("--frames", type=int, default=1)
    p_new.add_argument("--duration", type=int, default=None, help="frame duration in ms")
    p_new.set_defaults(func=cmd_new)

    p_build = sub.add_parser("build", help="export every .aseprite in a folder")
    p_build.add_argument("--input", default="art")
    p_build.add_argument("--out", default="dist")
    p_build.add_argument("--scale", type=int, default=1)
    p_build.add_argument("--padding", type=int, default=1, help="pixels between packed frames")
    p_build.add_argument("--no-gif", action="store_true", help="skip per-tag GIFs")
    p_build.set_defaults(func=cmd_build)

    p_info = sub.add_parser("info", help="summarise a sprite")
    p_info.add_argument("sprite")
    p_info.set_defaults(func=cmd_info)

    p_gif = sub.add_parser("gif", help="export one GIF")
    p_gif.add_argument("sprite")
    p_gif.add_argument("--out", required=True)
    p_gif.add_argument("--tag", default=None)
    p_gif.add_argument("--scale", type=int, default=1)
    p_gif.set_defaults(func=cmd_gif)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
