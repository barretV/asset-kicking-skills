#!/usr/bin/env python3
"""System check for asset-kicking-skills. Standard library only, so it runs before anything is installed.

Detects the OS, NVIDIA GPU and VRAM (nvidia-smi), RAM, free disk, Python, Blender, git, ffmpeg, Aseprite and
an existing ComfyUI, then picks a tier from setup/tiers.json and (unless --dry-run) writes the config file the
skills read: ~/.asset-kicking-skills/config.json (or $ASSET_KIT_CONFIG).

    python setup/detect.py --dry-run              # print what it found and the tier; writes nothing
    python setup/detect.py                        # same, then write the config
    python setup/detect.py --comfyui D:/ComfyUI   # tell it where ComfyUI is (or will be installed)
    python setup/detect.py --json                 # machine-readable output
    python setup/detect.py --tier 6gb             # force a tier (e.g. a 6 GB profile on a bigger card)

Runs nothing that changes the machine: every probe is a read-only query (`nvidia-smi --query-gpu`,
`blender --version`, ...). Works on Windows, Linux and macOS.
"""
import argparse
import ctypes
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GB = 1024 ** 3


def run(cmd, timeout=20):
    """Run a read-only probe; return stdout or None."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or "") + (out.stderr or "")


def config_path():
    return os.environ.get("ASSET_KIT_CONFIG") or os.path.join(os.path.expanduser("~"), ".asset-kicking-skills", "config.json")


# --------------------------------------------------------------------------- probes
def detect_os():
    system = platform.system()
    info = {"system": system, "release": platform.release(), "version": platform.version(), "machine": platform.machine()}
    if system == "Windows":
        build = platform.version().split(".")[-1]
        if build.isdigit() and int(build) >= 22000:
            info["release"] = "11"  # platform.release() still says "10" on Windows 11
        info["release"] += " (build %s)" % build
    if system == "Linux":
        try:
            with open("/etc/os-release", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        info["wsl"] = "microsoft" in platform.release().lower()
    if system == "Darwin":
        info["mac_version"] = platform.mac_ver()[0]
    return info


def detect_gpus():
    gpus = []
    smi = shutil.which("nvidia-smi")
    if not smi and platform.system() == "Windows":
        cand = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        smi = cand if os.path.exists(cand) else None
    if smi:
        out = run([smi, "--query-gpu=name,memory.total,driver_version,power.limit", "--format=csv,noheader,nounits"])
        for line in (out or "").strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2 and parts[1].replace(".", "").isdigit():
                gpus.append({
                    "vendor": "nvidia", "name": parts[0], "vram_mib": int(float(parts[1])),
                    "vram_gb": round(float(parts[1]) / 1024, 1),
                    "driver": parts[2] if len(parts) > 2 else None,
                    "power_limit_w": parts[3] if len(parts) > 3 else None,
                })
        cuda = run([smi])
        m = re.search(r"CUDA Version:\s*([\d.]+)", cuda or "")
        for g in gpus:
            g["cuda_driver_max"] = m.group(1) if m else None
    if not gpus and platform.system() == "Darwin":
        out = run(["system_profiler", "SPDisplaysDataType"], timeout=30) or ""
        for name in re.findall(r"Chipset Model:\s*(.+)", out):
            gpus.append({"vendor": "apple" if "Apple" in name else "other", "name": name.strip(), "vram_gb": None,
                         "note": "Apple GPUs use unified memory (MPS). The tested path needs an NVIDIA GPU."})
    if not gpus and shutil.which("rocm-smi"):
        gpus.append({"vendor": "amd", "name": "AMD GPU (rocm-smi found)", "vram_gb": None,
                     "note": "AMD/ROCm is not tested with these skills."})
    if not gpus and platform.system() == "Windows":
        out = run(["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"]) or ""
        for name in out.strip().splitlines():
            if name.strip():
                gpus.append({"vendor": "other", "name": name.strip(), "vram_gb": None,
                             "note": "No nvidia-smi: not an NVIDIA GPU, or the NVIDIA driver is missing."})
    return gpus


def detect_ram_gb():
    system = platform.system()
    try:
        if system == "Windows":
            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return round(st.ullTotalPhys / GB, 1)
        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        return round(int(line.split()[1]) * 1024 / GB, 1)
        if system == "Darwin":
            out = run(["sysctl", "-n", "hw.memsize"])
            return round(int(out.strip()) / GB, 1) if out else None
    except Exception:
        return None
    return None


def detect_disk(path):
    path = os.path.abspath(path)
    while not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        du = shutil.disk_usage(path)
        return {"path": path, "free_gb": round(du.free / GB, 1), "total_gb": round(du.total / GB, 1)}
    except OSError:
        return {"path": path, "free_gb": None, "total_gb": None}


def detect_pythons():
    found = [{"exe": sys.executable, "version": platform.python_version(), "running": True}]
    if platform.system() == "Windows" and shutil.which("py"):
        out = run(["py", "-0p"]) or ""
        for line in out.splitlines():
            m = re.search(r"-V:([\d.]+)\S*\s+\*?\s*(.+)$", line.strip())
            if m and os.path.normcase(m.group(2).strip()) != os.path.normcase(sys.executable):
                found.append({"exe": m.group(2).strip(), "version": m.group(1), "running": False})
    else:
        for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
            exe = shutil.which(name)
            if exe and os.path.realpath(exe) != os.path.realpath(sys.executable):
                found.append({"exe": exe, "version": name.replace("python", ""), "running": False})
    return found


def blender_candidates():
    env = os.environ.get("BLENDER_PATH")
    if env:
        yield env
    on_path = shutil.which("blender")
    if on_path:
        yield on_path
    system = platform.system()
    if system == "Windows":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if base:
                yield from sorted(glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe")), reverse=True)
        steam = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam", "steamapps", "common", "Blender", "blender.exe")
        yield steam
    elif system == "Darwin":
        yield "/Applications/Blender.app/Contents/MacOS/Blender"
    else:
        yield from ("/usr/bin/blender", "/snap/bin/blender", "/usr/local/bin/blender")
        yield from sorted(glob.glob(os.path.expanduser("~/blender*/blender")), reverse=True)


def detect_blender():
    seen = set()
    for exe in blender_candidates():
        if not exe or exe in seen or not os.path.exists(exe):
            continue
        seen.add(exe)
        out = run([exe, "--version"], timeout=60) or ""
        m = re.search(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", out)
        if m:
            ver = m.group(1)
            major_minor = tuple(int(x) for x in ver.split(".")[:2])
            return {"exe": exe, "version": ver, "ok_for_blender_anim": major_minor >= (4, 4),
                    "ok_for_stablegen": major_minor >= (5, 1) or (4, 2) <= major_minor <= (4, 5)}
    return None


def detect_tool(name, args=("-version",), pattern=r"(\d+\.\d+(?:\.\d+)?)"):
    exe = shutil.which(name)
    if not exe:
        return None
    out = run([exe, *args]) or ""
    m = re.search(pattern, out)
    return {"exe": exe, "version": m.group(1) if m else None}


def detect_aseprite():
    exe = os.environ.get("ASEPRITE_PATH") or shutil.which("aseprite")
    if not exe and platform.system() == "Windows":
        steam = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam", "steamapps", "common", "Aseprite", "Aseprite.exe")
        exe = steam if os.path.exists(steam) else None
    if not exe and platform.system() == "Darwin" and os.path.exists("/Applications/Aseprite.app/Contents/MacOS/aseprite"):
        exe = "/Applications/Aseprite.app/Contents/MacOS/aseprite"
    if not exe or not os.path.exists(exe):
        return None
    out = run([exe, "--version"], timeout=30) or ""
    m = re.search(r"(\d+\.\d+(?:\.\d+)*)", out)
    return {"exe": exe, "version": m.group(1) if m else None}


def detect_comfyui(path):
    if not path:
        return None
    path = os.path.abspath(os.path.expanduser(path))
    info = {"dir": path, "exists": os.path.isfile(os.path.join(path, "main.py"))}
    if not info["exists"]:
        return info
    try:
        with open(os.path.join(path, "comfyui_version.py"), encoding="utf-8") as fh:
            m = re.search(r"['\"]([\d.]+)['\"]", fh.read())
            info["version"] = m.group(1) if m else None
    except OSError:
        info["version"] = None
    for py in (os.path.join(path, "venv", "Scripts", "python.exe"), os.path.join(path, "venv", "bin", "python"),
               os.path.join(path, ".venv", "Scripts", "python.exe"), os.path.join(path, ".venv", "bin", "python"),
               os.path.join(os.path.dirname(path), "python_embeded", "python.exe")):
        if os.path.exists(py):
            info["python"] = py
            break
    nodes = os.path.join(path, "custom_nodes")
    info["custom_nodes"] = sorted(d for d in os.listdir(nodes) if os.path.isdir(os.path.join(nodes, d)) and not d.startswith("__")) if os.path.isdir(nodes) else []
    return info


# --------------------------------------------------------------------------- tier
def load_tiers():
    with open(os.path.join(HERE, "tiers.json"), encoding="utf-8") as fh:
        return json.load(fh)["tiers"]


def pick_tier(tiers, gpus, forced=None):
    by_id = {t["id"]: t for t in tiers}
    if forced:
        if forced not in by_id:
            raise SystemExit("unknown tier %r (choose from %s)" % (forced, ", ".join(by_id)))
        return by_id[forced], "forced with --tier"
    nvidia = [g for g in gpus if g.get("vendor") == "nvidia" and g.get("vram_gb")]
    if not nvidia:
        return by_id["cpu"], "no NVIDIA GPU detected"
    best = max(nvidia, key=lambda g: g["vram_gb"])
    fit = [t for t in tiers if t["min_vram_gb"] <= best["vram_gb"]]
    tier = max(fit, key=lambda t: t["min_vram_gb"])
    return tier, "%s with %.1f GB VRAM" % (best["name"], best["vram_gb"])


def disk_needed_gb(tier_id):
    with open(os.path.join(HERE, "models.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    order = [t["id"] for t in load_tiers()]
    rank = order.index(tier_id)
    default = {k for k, b in man["bundles"].items() if b.get("default") and order.index(b["min_tier"]) <= rank}
    everything = {k for k, b in man["bundles"].items() if order.index(b["min_tier"]) <= rank}
    size = lambda keep: sum(f["size_bytes"] for f in man["files"] if f["bundle"] in keep) / GB
    return round(size(default), 1), round(size(everything), 1)


def warnings_for(report, tier):
    w = []
    ram = report["ram_gb"]
    if ram is not None and ram < 15.5:
        w.append("RAM is %.1f GB; 16 GB is the tested floor. Keep --cache-none and expect MOSS's text encoder to swap." % ram)
    disk = report["disk"]["free_gb"]
    need_default, _ = report["disk_needed_gb"]
    if disk is not None and need_default and disk < need_default + 15:
        w.append("Free disk %.0f GB at %s; the default model set needs about %.0f GB plus ~15 GB for ComfyUI and its venv." % (disk, report["disk"]["path"], need_default))
    if not report["blender"]:
        w.append("Blender not found (blender-anim and concept-to-3d need 4.4+; set BLENDER_PATH if it is installed somewhere unusual).")
    elif not report["blender"]["ok_for_blender_anim"]:
        w.append("Blender %s is older than 4.4; blender-anim needs 4.4 or newer." % report["blender"]["version"])
    if not report["git"]:
        w.append("git not found: needed to install ComfyUI and its custom nodes.")
    if not report["ffmpeg"]:
        w.append("ffmpeg not found: the game-sfx finishing step needs it.")
    if report["os"]["system"] == "Darwin":
        w.append("macOS: only the CPU parts (pixel-art, Blender, sound) are expected to work; the GPU tiers assume NVIDIA CUDA.")
    if report["os"].get("wsl"):
        w.append("WSL detected: run ComfyUI on the side that has the NVIDIA driver; paths differ between Windows and WSL.")
    pyver = tuple(int(x) for x in platform.python_version().split(".")[:2])
    if pyver < (3, 10):
        w.append("This Python is %s; ComfyUI needs 3.10 or newer (3.12 recommended)." % platform.python_version())
    if not tier["tested"]:
        w.append("Tier %s is extrapolated, not tested. Start with its settings and step down a tier if a job runs out of memory." % tier["id"])
    return w


# --------------------------------------------------------------------------- output
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print only, write no config")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--comfyui", help="ComfyUI folder (existing, or where it will be installed)")
    ap.add_argument("--root", help="where models and tools will live, for the disk check (default: the ComfyUI folder or home)")
    ap.add_argument("--tier", help="force a tier id from setup/tiers.json")
    args = ap.parse_args()

    existing = {}
    if os.path.exists(config_path()):
        try:
            with open(config_path(), encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, ValueError):
            existing = {}
    comfy = args.comfyui or os.environ.get("COMFYUI_DIR") or existing.get("comfyui_dir")

    tiers = load_tiers()
    gpus = detect_gpus()
    tier, why = pick_tier(tiers, gpus, args.tier)
    report = {
        "os": detect_os(),
        "gpus": gpus,
        "ram_gb": detect_ram_gb(),
        "disk": detect_disk(args.root or comfy or os.path.expanduser("~")),
        "pythons": detect_pythons(),
        "blender": detect_blender(),
        "git": detect_tool("git", ("--version",)),
        "ffmpeg": detect_tool("ffmpeg"),
        "aseprite": detect_aseprite(),
        "comfyui": detect_comfyui(comfy),
        "tier": tier["id"],
        "tier_reason": why,
        "disk_needed_gb": disk_needed_gb(tier["id"]),
    }
    report["warnings"] = warnings_for(report, tier)

    config = {
        "schema": 1,
        "tier": tier["id"],
        "tier_tested": tier["tested"],
        "comfyui_dir": comfy,
        "comfyui_args": tier["comfyui_args"],
        "comfyui_args_rigging": tier.get("comfyui_args_rigging", []),
        "env": tier.get("env", {}),
        "blender": (report["blender"] or {}).get("exe"),
        "aseprite": (report["aseprite"] or {}).get("exe"),
        "ffmpeg": (report["ffmpeg"] or {}).get("exe"),
        "settings": {k: tier[k] for k in ("moss", "trellis2", "hi3d", "skintokens", "sfx_ai", "stablegen") if k in tier},
        "max_parallel_gpu_jobs": tier["max_parallel_gpu_jobs"],
        "gpu_lock_dir": existing.get("gpu_lock_dir"),
    }

    if args.json:
        print(json.dumps({"report": report, "config": config}, indent=2))
    else:
        o = report["os"]
        print("asset-kicking-skills system check")
        print("  OS        %s %s (%s)%s" % (o["system"], o.get("distro") or o.get("mac_version") or o["release"], o["machine"], "  [WSL]" if o.get("wsl") else ""))
        if gpus:
            for g in gpus:
                vram = "%.1f GB VRAM" % g["vram_gb"] if g.get("vram_gb") else "VRAM unknown"
                extra = ", driver %s" % g["driver"] if g.get("driver") else ""
                print("  GPU       %s, %s%s" % (g["name"], vram, extra))
        else:
            print("  GPU       none detected")
        print("  RAM       %s GB" % report["ram_gb"])
        d = report["disk"]
        print("  Disk      %s GB free on %s" % (d["free_gb"], d["path"]))
        print("  Python    %s (%s)" % (platform.python_version(), sys.executable))
        for p in report["pythons"][1:]:
            print("            also %s at %s" % (p["version"], p["exe"]))
        b = report["blender"]
        print("  Blender   %s" % ("%s at %s" % (b["version"], b["exe"]) if b else "not found"))
        for name in ("git", "ffmpeg", "aseprite"):
            t = report[name]
            print("  %-9s %s" % (name.capitalize() if name != "ffmpeg" else "FFmpeg", "%s at %s" % (t["version"], t["exe"]) if t else "not found"))
        c = report["comfyui"]
        if c is None:
            print("  ComfyUI   not set (pass --comfyui <folder>)")
        elif not c["exists"]:
            print("  ComfyUI   not installed yet at %s" % c["dir"])
        else:
            print("  ComfyUI   %s at %s (custom nodes: %s)" % (c.get("version"), c["dir"], ", ".join(c["custom_nodes"]) or "none"))
        nd, na = report["disk_needed_gb"]
        print()
        print("TIER: %s  -  %s%s" % (tier["id"], tier["label"], "" if tier["tested"] else "  [not tested]"))
        print("  because   %s" % why)
        print("  ComfyUI   main.py %s" % " ".join(tier["comfyui_args"]))
        if tier.get("comfyui_args_rigging"):
            print("  rigging   main.py %s  (SkinTokens)" % " ".join(tier["comfyui_args_rigging"]))
        print("  models    about %.0f GB for the default set, %.0f GB with every optional bundle" % (nd, na))
        print("  summary   %s" % tier["summary"])
        for w in report["warnings"]:
            print("  WARNING   %s" % w)

    if args.dry_run:
        if not args.json:
            print("\n(dry run: no config written; it would go to %s)" % config_path())
        return
    os.makedirs(os.path.dirname(config_path()), exist_ok=True)
    with open(config_path(), "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    if not args.json:
        print("\nwrote %s" % config_path())


if __name__ == "__main__":
    main()
