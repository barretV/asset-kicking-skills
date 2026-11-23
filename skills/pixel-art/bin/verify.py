#!/usr/bin/env python3
"""Verify a pixel-art skill install end to end.

    py -3 bin/verify.py [--mcp-python <venv-python>] [--keep]

Checks, in order:

  files     SKILL.md, the craft rules, and the CLI scripts are present
  aseprite  the binary resolves and reports a version
  sprite    a 32x32, 4-frame, 120 ms PICO-8 sprite can be created
  tag       an idle tag covers frames 0-3 (note Lua newTag is 1-based)
  export    info + build produce a non-empty PNG, parseable JSON, a GIF,
            and a manifest whose tag is 0-based and whose fps is sane
  mcp       optional: import aseprite_mcp with the given Python

Every check is a measurement. Exits non-zero if any check fails, so it can gate
an install or a machine migration. Nothing is written outside a temp directory
unless --keep is used.

Aseprite is located through ASEPRITE_PATH, <project>/aseprite/build/bin/aseprite.exe,
or PATH. Set ASEPRITE_PATH when the binary lives elsewhere.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
RULES = SKILL / "knowledge" / "rules"
CLI = HERE / "pixelart.py"

sys.path.insert(0, str(HERE))
import pixelart  # noqa: E402


def run(args, cwd=None, env=None):
    proc = subprocess.run(
        [str(a) for a in args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed (%d): %s\n%s%s"
            % (proc.returncode, " ".join(str(a) for a in args), proc.stdout, proc.stderr)
        )
    return proc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mcp-python",
        default=os.environ.get("ASEPRITE_MCP_PYTHON", ""),
        help="Python from the aseprite-mcp virtualenv (optional)",
    )
    ap.add_argument("--keep", action="store_true", help="keep the temp smoke-test directory")
    args = ap.parse_args()

    failures = []
    skipped = []
    tmp = Path(tempfile.mkdtemp(prefix="pixelart-verify-"))

    def check(name, ok, detail=""):
        print("%-8s %-9s %s" % ("PASS" if ok else "FAIL", name, detail))
        if not ok:
            failures.append("%s: %s" % (name, detail))

    def skip(name, detail):
        print("%-8s %-9s %s" % ("SKIP", name, detail))
        skipped.append(name)

    # ---- files -------------------------------------------------------------
    print("skill: %s" % SKILL)
    check("files", (SKILL / "SKILL.md").is_file(), "SKILL.md")
    rule_count = len(list(RULES.glob("*.md"))) if RULES.is_dir() else 0
    check("rules", rule_count >= 60, "%d rule modules" % rule_count)
    check("cli", CLI.is_file() and (HERE / "frame_count.lua").is_file(), "pixelart.py + frame_count.lua")
    palettes = {"pico8", "gameboy", "dawnbringer16", "c64", "cga"}
    check("palettes", palettes <= set(pixelart.PALETTES),
          ", ".join(sorted(pixelart.PALETTES)))

    # ---- aseprite ----------------------------------------------------------
    exe = None
    try:
        exe = pixelart.find_aseprite()
        version = run([exe, "--version"]).stdout.strip()
        print("binary:  %s" % exe)
        check("aseprite", "Aseprite" in version and "1.3" in version, version)
    except Exception as exc:
        check("aseprite", False, str(exc))
        print("\n%s check(s) failed; see the message above." % len(failures))
        return 1

    # ---- sprite + tag ------------------------------------------------------
    sprite = tmp / "smoke" / "slime.aseprite"
    try:
        run([sys.executable, CLI, "new", sprite, "--size", "32x32",
             "--palette", "pico8", "--frames", "4", "--duration", "120"])
        check("sprite", sprite.is_file() and sprite.stat().st_size > 0, str(sprite))
    except Exception as exc:
        check("sprite", False, str(exc))
        print("\n%s check(s) failed; temp kept at %s" % (len(failures), tmp))
        return 1

    # Draw a visible block on every frame, then tag frames 0-3. Lua newTag takes
    # 1-based frame numbers; newTag(0, 3) silently drops frame 1.
    lua = tmp / "prepare.lua"
    lua.write_text(
        "\n".join([
            "local spr = app.activeSprite",
            "local layer = spr.layers[1]",
            "for f = 1, #spr.frames do",
            "  local cel = spr:newCel(layer, f)",
            "  local img = cel.image",
            "  for y = 10, 21 do",
            "    for x = 12, 19 do",
            "      img:putPixel(x, y, app.pixelColor.rgba(0, 228, 54, 255))",
            "    end",
            "  end",
            "end",
            "local tag = spr:newTag(1, 4)",
            'tag.name = "idle"',
            "spr:saveAs(spr.filename)",
            'print("DRAW=ok")',
            'print("TAG=idle")',
            "",
        ]),
        encoding="utf-8",
    )
    try:
        prep_out = run([exe, "-b", sprite, "--script", lua]).stdout.strip()
        check("pixels", "DRAW=ok" in prep_out, "4 frames filled")
        check("tag", "TAG=idle" in prep_out, "idle tag created")
    except Exception as exc:
        check("tag", False, str(exc))

    # ---- info + build ------------------------------------------------------
    try:
        info = run([sys.executable, CLI, "info", sprite]).stdout
        ok_info = (
            "32x32" in info
            and "4 frame" in info
            and "[120, 120, 120, 120]" in info
            and "idle" in info
            and "0-3" in info
        )
        check("info", ok_info, info.strip().splitlines()[0] if info.strip() else "no output")
    except Exception as exc:
        check("info", False, str(exc))

    dist = tmp / "dist"
    try:
        run([sys.executable, CLI, "build", "--input", sprite.parent, "--out", dist])
        png = dist / "slime.png"
        data = dist / "slime.json"
        gif = dist / "slime_idle.gif"
        manifest_path = dist / "manifest.json"
        check("png", png.is_file() and png.stat().st_size > 0,
              "%s bytes" % (png.stat().st_size if png.is_file() else 0))
        check("gif", gif.is_file() and gif.stat().st_size > 0,
              "%s bytes" % (gif.stat().st_size if gif.is_file() else 0))

        meta = json.loads(data.read_text(encoding="utf-8"))
        frames = meta.get("frames", {})
        tags = (meta.get("meta", {}) or {}).get("frameTags", []) or []
        first = next(iter(frames.values()), {})
        source_size = first.get("sourceSize", {}) or {}
        durations = [int(f.get("duration", 0)) for f in frames.values()]
        tag = tags[0] if tags else {}
        ok_json = (
            len(frames) == 4
            and durations == [120, 120, 120, 120]
            and tag.get("name") == "idle"
            and tag.get("from") == 0
            and tag.get("to") == 3
            and source_size.get("w") == 32
            and source_size.get("h") == 32
        )
        check("json", ok_json,
              "%d frames, tags=%s, durations=%s, sourceSize=%s"
              % (len(frames), [t.get("name") for t in tags], durations,
                 source_size))

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = (manifest.get("sprites") or [{}])[0]
        mtag = (entry.get("tags") or [{}])[0]
        ok_manifest = (
            entry.get("width") == 32
            and entry.get("height") == 32
            and mtag.get("name") == "idle"
            and mtag.get("from") == 0
            and mtag.get("to") == 3
            and mtag.get("frames") == 4
            and abs(float(mtag.get("fps") or 0) - 8.33) < 0.01
        )
        check("manifest", ok_manifest,
              "idle %s-%s, %s frames, %s fps"
              % (mtag.get("from"), mtag.get("to"), mtag.get("frames"), mtag.get("fps")))
    except Exception as exc:
        check("export", False, str(exc))

    # ---- optional MCP import ----------------------------------------------
    mcp_python = args.mcp_python
    if not mcp_python:
        candidates = [
            SKILL.parents[2] / "aseprite-mcp" / ".venv" / "Scripts" / "python.exe",
            SKILL.parents[2] / "aseprite-mcp" / ".venv" / "bin" / "python",
            Path.cwd() / "aseprite-mcp" / ".venv" / "Scripts" / "python.exe",
            Path.cwd() / "aseprite-mcp" / ".venv" / "bin" / "python",
        ]
        for candidate in candidates:
            if candidate.is_file():
                mcp_python = str(candidate)
                break
    if mcp_python and Path(mcp_python).is_file():
        try:
            # <aseprite-mcp>/.venv/Scripts/python.exe (or .venv/bin/python) -> <aseprite-mcp>
            import_root = Path(mcp_python).resolve().parents[2]
            env = dict(os.environ)
            env["PYTHONPATH"] = str(import_root)
            proc = run([mcp_python, "-c", "import aseprite_mcp; print('MCP_OK')"],
                       cwd=import_root, env=env)
            check("mcp", "MCP_OK" in proc.stdout, mcp_python)
        except Exception as exc:
            check("mcp", False, str(exc))
    else:
        skip("mcp", "pass --mcp-python <aseprite-mcp venv python> to check")

    # ---- result ------------------------------------------------------------
    print("")
    if failures:
        print("%d check(s) failed; temp kept at %s" % (len(failures), tmp))
        for item in failures:
            print("  - %s" % item)
        return 1

    if args.keep:
        print("all checks passed; temp kept at %s" % tmp)
    else:
        shutil.rmtree(tmp, ignore_errors=True)
        print("all checks passed (%d skipped)" % len(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
