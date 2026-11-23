#!/usr/bin/env python3
"""List, check and (only after the user says yes) download the model weights in setup/models.json.

    python setup/models.py plan  [--bundles moss,trellis2] [--all]   # the confirm-before-download table
    python setup/models.py check [--bundles ...]                       # what is already on disk
    python setup/models.py fetch --bundles moss,trellis2 --yes         # download (needs huggingface_hub)

`plan` and `check` use the standard library only and never touch the network. `fetch` refuses to run
without --yes: an agent passes it only after showing `plan` to the user and getting a clear yes.
Run `fetch` with ComfyUI's own venv Python, which already has huggingface_hub.

Bundles default to the ones marked "default" in models.json that fit the configured tier.
Files land in <ComfyUI>/models/<dest>/. Sizes are checked after download; sha256 too where it is known.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GB = 1e9


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def config():
    path = os.environ.get("ASSET_KIT_CONFIG") or os.path.join(os.path.expanduser("~"), ".asset-kicking-skills", "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def pick_bundles(man, args, tier):
    order = [t["id"] for t in load("tiers.json")["tiers"]]
    rank = order.index(tier) if tier in order else order.index("6gb")
    if args.bundles:
        names = [b.strip() for b in args.bundles.split(",") if b.strip()]
        bad = [b for b in names if b not in man["bundles"]]
        if bad:
            raise SystemExit("unknown bundle(s): %s (have: %s)" % (", ".join(bad), ", ".join(man["bundles"])))
        return names
    return [k for k, b in man["bundles"].items()
            if (args.all or b.get("default")) and order.index(b["min_tier"]) <= rank]


def dest_path(comfy, f):
    base = os.path.join(comfy or "<ComfyUI>", "models", *f["dest"].split("/"))
    return base if f.get("snapshot") else os.path.join(base, f["file"])


def present(comfy, f):
    p = dest_path(comfy, f)
    if f.get("snapshot"):
        return os.path.isfile(os.path.join(p, "config.json"))
    if not os.path.isfile(p):
        return False
    if f.get("approx"):
        return os.path.getsize(p) > 0.9 * f["size_bytes"]
    return os.path.getsize(p) == f["size_bytes"]


def human(n):
    return "%.2f GB" % (n / GB) if n >= 1e8 else "%.0f MB" % (n / 1e6)


def plan(man, bundles, comfy):
    rows = [f for f in man["files"] if f["bundle"] in bundles]
    total = need = 0
    print("Model files for bundles: %s" % ", ".join(bundles))
    print("Destination: %s/models/...\n" % (comfy or "<ComfyUI>"))
    print("| # | File | Folder | Source | Size | Licence | Commercial use | On disk |")
    print("|---|---|---|---|---|---|---|---|")
    for i, f in enumerate(rows, 1):
        src = "https://huggingface.co/%s" % f["repo"]
        if f.get("revision"):
            src += " @ %s" % f["revision"][:10]
        if f.get("remote") is None and not f.get("snapshot"):
            src += " (path looked up by name)"
        size = ("~" if f.get("approx") else "") + human(f["size_bytes"])
        have = present(comfy, f) if comfy else False
        total += f["size_bytes"]
        need += 0 if have else f["size_bytes"]
        flags = " (gated: accept licence first)" if f.get("gated") else ""
        print("| %d | %s | %s | %s | %s | %s%s | %s | %s |" % (i, f["file"], f["dest"], src, size, f["licence"], flags, f["commercial"], "yes" if have else "no"))
    nodes = [n for n in man.get("custom_nodes", []) if n["bundle"] in bundles]
    if nodes:
        print("\nComfyUI custom nodes (git clone into custom_nodes/):")
        for n in nodes:
            print("  - %s  %s @ %s  (%s)  %s" % (n["name"], n["repo"], n["commit"], n["licence"], n.get("note", "")))
    notes = [f for f in rows if f.get("note")]
    if notes:
        print("\nNotes:")
        for f in notes:
            print("  - %s: %s" % (f["file"], f["note"]))
    print("\nTotal %s, still to download %s." % (human(total), human(need)))
    if comfy and os.path.isdir(comfy):
        free = shutil.disk_usage(comfy).free
        print("Free disk at %s: %s%s" % (comfy, human(free), "  -- NOT ENOUGH" if free < need * 1.1 else ""))
    print("\nNothing has been downloaded. Ask the user to approve this list before running `fetch`.")


def check(man, bundles, comfy):
    ok = True
    for f in (f for f in man["files"] if f["bundle"] in bundles):
        have = present(comfy, f)
        ok &= have
        print("%-5s %s/%s" % ("OK" if have else "MISS", f["dest"], "" if f.get("snapshot") else f["file"]))
    for n in (n for n in man.get("custom_nodes", []) if n["bundle"] in bundles):
        have = os.path.isdir(os.path.join(comfy, "custom_nodes", n["name"]))
        ok &= have
        print("%-5s custom_nodes/%s" % ("OK" if have else "MISS", n["name"]))
    return ok


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(man, bundles, comfy):
    try:
        from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    except ImportError:
        raise SystemExit("huggingface_hub is missing: run this with ComfyUI's venv Python")
    api = HfApi()
    for f in (f for f in man["files"] if f["bundle"] in bundles):
        if present(comfy, f):
            print("SKIP  %s (already there)" % f["file"])
            continue
        dest = dest_path(comfy, f)
        rev = f.get("revision") if f.get("revision") and len(f["revision"]) == 40 else None
        if f.get("snapshot"):
            print("==>   %s (snapshot of %s)" % (f["dest"], f["repo"]), flush=True)
            snapshot_download(repo_id=f["repo"], local_dir=dest, ignore_patterns=f.get("ignore_patterns"), revision=rev)
            continue
        remote = f.get("remote")
        if remote is None:
            matches = [p for p in api.list_repo_files(f["repo"], revision=rev) if p.rsplit("/", 1)[-1] == f["file"]]
            if len(matches) != 1:
                raise SystemExit("could not find exactly one %s in %s (found %s): stop and ask the user" % (f["file"], f["repo"], matches))
            remote = matches[0]
            print("      %s resolved to %s" % (f["file"], remote))
        print("==>   %s/%s -> %s" % (f["repo"], remote, dest), flush=True)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        staging = os.path.join(comfy, "models", ".download")
        got = hf_hub_download(repo_id=f["repo"], filename=remote, revision=rev, local_dir=staging)
        size = os.path.getsize(got)
        if not f.get("approx") and size != f["size_bytes"]:
            raise SystemExit("size mismatch for %s: %d bytes, expected %d. Not moved into place." % (f["file"], size, f["size_bytes"]))
        if f.get("sha256"):
            digest = sha256(got)
            if digest != f["sha256"]:
                raise SystemExit("sha256 mismatch for %s: %s. Not moved into place." % (f["file"], digest))
            print("      sha256 OK")
        os.replace(got, dest)
        print("      %s" % human(size))
    shutil.rmtree(os.path.join(comfy, "models", ".download"), ignore_errors=True)
    print("\nDone. Run `python setup/models.py check` to confirm.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["plan", "check", "fetch"])
    ap.add_argument("--bundles", help="comma list from models.json 'bundles'")
    ap.add_argument("--all", action="store_true", help="include optional bundles that fit the tier")
    ap.add_argument("--comfyui", help="ComfyUI folder (default: $COMFYUI_DIR or the config)")
    ap.add_argument("--tier", help="tier id (default: the config's)")
    ap.add_argument("--yes", action="store_true", help="the user approved the plan; required for fetch")
    args = ap.parse_args()

    man = load("models.json")
    cfg = config()
    comfy = args.comfyui or os.environ.get("COMFYUI_DIR") or cfg.get("comfyui_dir")
    bundles = pick_bundles(man, args, args.tier or cfg.get("tier", "6gb"))
    if args.action == "plan":
        plan(man, bundles, comfy)
    elif args.action == "check":
        if not comfy:
            raise SystemExit("ComfyUI folder unknown: pass --comfyui or run setup/detect.py --comfyui <folder>")
        sys.exit(0 if check(man, bundles, comfy) else 1)
    else:
        if not args.yes:
            raise SystemExit("fetch needs --yes, given only after the user approved `plan`'s list")
        if not comfy or not os.path.isfile(os.path.join(comfy, "main.py")):
            raise SystemExit("install ComfyUI first (AGENTS.md step 4), then pass --comfyui")
        fetch(man, bundles, comfy)


if __name__ == "__main__":
    main()
