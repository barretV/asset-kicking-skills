#!/usr/bin/env python3
"""Write ComfyUI launch scripts for this machine's tier (from ~/.asset-kicking-skills/config.json).

    python setup/launcher.py                 # writes <ComfyUI>/run_asset_kit.(bat|sh) and run_asset_kit_rigging.*
    python setup/launcher.py --print         # only print the commands
    python setup/launcher.py --check-flags   # also drop flags this ComfyUI build does not know (runs `main.py --help`)

Two profiles: the general one (MOSS, TRELLIS.2, Hi3D, Stable Audio) and a rigging one for SkinTokens, which
needs ComfyUI started with less VRAM in use. Start one, use it, stop it. Never run two at once.
"""
import argparse
import json
import os
import platform
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def config():
    path = os.environ.get("ASSET_KIT_CONFIG") or os.path.join(os.path.expanduser("~"), ".asset-kicking-skills", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        raise SystemExit("no config yet: run `python setup/detect.py --comfyui <folder>` first")


def venv_python(comfy):
    for rel in (("venv", "Scripts", "python.exe"), ("venv", "bin", "python"), (".venv", "Scripts", "python.exe"), (".venv", "bin", "python")):
        p = os.path.join(comfy, *rel)
        if os.path.exists(p):
            return p, os.path.join(*rel)
    raise SystemExit("no venv under %s: create it first (AGENTS.md step 4)" % comfy)


def known_flags(py, comfy):
    out = subprocess.run([py, "main.py", "--help"], cwd=comfy, capture_output=True, text=True, timeout=180)
    return set(re.findall(r"(--[a-z0-9][a-z0-9-]*)", out.stdout + out.stderr))


def filter_args(args, known):
    kept, dropped, i = [], [], 0
    while i < len(args):
        flag = args[i]
        value = [args[i + 1]] if i + 1 < len(args) and not args[i + 1].startswith("--") else []
        (kept if flag in known else dropped).extend([flag] + value)
        i += 1 + len(value)
    return kept, dropped


def write(comfy, name, rel_py, args, env, windows):
    if windows:
        path = os.path.join(comfy, name + ".bat")
        lines = ["@echo off", "REM written by asset-kicking-skills setup/launcher.py; re-run it after changing tier",
                 'cd /d "%~dp0"']
        lines += ["set %s=%s" % kv for kv in env.items()]
        lines += ["%s -s main.py %s" % (rel_py, " ".join(args))]
    else:
        path = os.path.join(comfy, name + ".sh")
        lines = ["#!/usr/bin/env bash", "# written by asset-kicking-skills setup/launcher.py; re-run it after changing tier",
                 'cd "$(dirname "$0")"']
        lines += ["export %s='%s'" % kv for kv in env.items()]
        lines += ["exec %s -s main.py %s" % (rel_py.replace(os.sep, "/"), " ".join(args))]
    with open(path, "w", encoding="utf-8", newline="\r\n" if windows else "\n") as fh:
        fh.write("\n".join(lines) + "\n")
    if not windows:
        os.chmod(path, 0o755)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", action="store_true", help="print the commands, write nothing")
    ap.add_argument("--check-flags", action="store_true", help="drop flags `main.py --help` does not list")
    a = ap.parse_args()

    cfg = config()
    comfy = cfg.get("comfyui_dir")
    if not comfy or not os.path.isfile(os.path.join(comfy, "main.py")):
        raise SystemExit("ComfyUI not found at %r: install it, then re-run detect.py --comfyui <folder>" % comfy)
    py, rel_py = venv_python(comfy)
    profiles = {"run_asset_kit": cfg["comfyui_args"], "run_asset_kit_rigging": cfg.get("comfyui_args_rigging") or cfg["comfyui_args"]}
    if a.check_flags:
        known = known_flags(py, comfy)
        for k in profiles:
            profiles[k], dropped = filter_args(profiles[k], known)
            if dropped:
                print("%s: this ComfyUI build does not know %s, dropped" % (k, " ".join(dropped)))
    windows = platform.system() == "Windows"
    for name, args in profiles.items():
        if a.print:
            print("%s: %s -s main.py %s" % (name, rel_py, " ".join(args)))
        else:
            print("wrote", write(comfy, name, rel_py, args, cfg.get("env", {}), windows))
    print("Check it is up with:  curl -s http://127.0.0.1:8188/system_stats")


if __name__ == "__main__":
    main()
