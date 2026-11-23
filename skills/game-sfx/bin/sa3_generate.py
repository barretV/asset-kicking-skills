"""
Generate game sound effects with Stable Audio 3 Small-SFX through a running ComfyUI (HTTP, standard library only).

  # one prompt, 3 seeds
  python sa3_generate.py --prompt "heavy sword hit on plate armour, metallic, short tail" --seconds 2 --seed 100 --count 3 --out work/sa3

  # a batch file: [{"name": "door", "prompt": "...", "seconds": 3}, ...]  (optional per item: "seed", "count", "negative")
  python sa3_generate.py --batch prompts.json --seed 100 --count 2 --out work/sa3

Start ComfyUI first (the tier's launch flags; Small-SFX and the T5Gemma encoder must be in models/). Each take is queued
on its own, the audio is fetched from the server (no need to share a disk with it) and saved as <out>/<name>_s<seed>.flac,
and <out>/sa3_manifest.json records prompt, seconds, seed and timing for every take. Exit code 0 only if every take worked.
"""
import argparse
import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH = os.path.join(HERE, "..", "assets", "sa3_small_sfx_api.json")


def call(server, path, data=None, timeout=60):
    req = urllib.request.Request(
        f"http://{server}{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_file(server, info, dest):
    q = urllib.parse.urlencode({"filename": info["filename"], "subfolder": info.get("subfolder", ""), "type": info.get("type", "output")})
    with urllib.request.urlopen(f"http://{server}/view?{q}", timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


def slug(text, n=40):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:n] or "take"


def build(graph, prompt, negative, seconds, seed, prefix):
    """Copy the graph and set prompt, negative, length, seed and file prefix. Nodes are found by class and wiring, not by id."""
    g = copy.deepcopy(graph)
    for node in g.values():
        t, i = node["class_type"], node["inputs"]
        if t == "EmptyLatentAudio":
            i["seconds"] = float(seconds)
        elif t == "KSampler":
            i["seed"] = int(seed)
        elif t == "SaveAudio":
            i["filename_prefix"] = prefix
    ks = next(n for n in g.values() if n["class_type"] == "KSampler")
    g[ks["inputs"]["positive"][0]]["inputs"]["text"] = prompt
    g[ks["inputs"]["negative"][0]]["inputs"]["text"] = negative or ""
    return g


def run_take(server, graph, timeout):
    """Queue one graph, wait, return (audio_info, wall_seconds, graph_seconds). Raises RuntimeError on failure."""
    t0 = time.time()
    try:
        r = call(server, "/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    except urllib.error.HTTPError as e:
        raise RuntimeError("REJECTED " + e.read().decode()[:3000])
    pid = r["prompt_id"]
    while time.time() - t0 < timeout:
        time.sleep(0.5)
        h = call(server, f"/history/{pid}")
        if pid not in h:
            continue
        st = h[pid]["status"]
        msgs = {m[0]: m[1] for m in st.get("messages", [])}
        if "execution_error" in msgs:
            raise RuntimeError("ERROR " + json.dumps(msgs["execution_error"])[:3000])
        if st.get("completed"):
            wall = time.time() - t0
            graph_s = None
            if "execution_start" in msgs and "execution_success" in msgs:
                graph_s = (msgs["execution_success"]["timestamp"] - msgs["execution_start"]["timestamp"]) / 1000.0
            for out in h[pid]["outputs"].values():
                if out.get("audio"):
                    return out["audio"][0], wall, graph_s
            raise RuntimeError("finished but saved no audio")
    raise RuntimeError("TIMEOUT")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", help="sound-library style description")
    ap.add_argument("--batch", help="JSON file: list of {name, prompt, seconds, [seed], [count], [negative]}")
    ap.add_argument("--name", help="file name stem for --prompt (default: from the prompt)")
    ap.add_argument("--seconds", type=float, default=3.0, help="clip length, default 3")
    ap.add_argument("--seed", type=int, default=1, help="first seed (take k uses seed+k)")
    ap.add_argument("--count", type=int, default=1, help="takes per prompt (consecutive seeds)")
    ap.add_argument("--negative", default="", help="negative prompt (ignored at CFG 1, kept for graphs you change)")
    ap.add_argument("--out", required=True, help="folder for the saved takes")
    ap.add_argument("--server", default="127.0.0.1:8188")
    ap.add_argument("--graph", default=GRAPH, help="API graph to rewrite (default: assets/sa3_small_sfx_api.json)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for one take")
    a = ap.parse_args()
    if bool(a.prompt) == bool(a.batch):
        ap.error("give exactly one of --prompt or --batch")

    items = json.load(open(a.batch, encoding="utf-8")) if a.batch else [{"name": a.name or slug(a.prompt), "prompt": a.prompt}]
    graph = json.load(open(a.graph, encoding="utf-8"))
    os.makedirs(a.out, exist_ok=True)
    try:
        call(a.server, "/system_stats", timeout=10)
    except Exception as e:
        print(f"cannot reach ComfyUI at {a.server}: {e}")
        return 1

    mpath = os.path.join(a.out, "sa3_manifest.json")
    manifest = json.load(open(mpath, encoding="utf-8")) if os.path.exists(mpath) else []
    failed = 0
    for item in items:
        name = item.get("name") or slug(item["prompt"])
        secs = item.get("seconds", a.seconds)
        seed0 = item.get("seed", a.seed)
        for k in range(item.get("count", a.count)):
            seed = seed0 + k
            prefix = f"sa3_sfx/{name}_s{seed}_{uuid.uuid4().hex[:6]}"
            g = build(graph, item["prompt"], item.get("negative", a.negative), secs, seed, prefix)
            try:
                info, wall, graph_s = run_take(a.server, g, a.timeout)
            except RuntimeError as e:
                print(f"FAIL {name} seed {seed}: {e}")
                failed += 1
                continue
            dest = os.path.join(a.out, f"{name}_s{seed}{os.path.splitext(info['filename'])[1] or '.flac'}")
            fetch_file(a.server, info, dest)
            extra = f", graph {graph_s:.1f} s" if graph_s is not None else ""
            print(f"ok {os.path.basename(dest)}  {secs:g} s clip, wall {wall:.1f} s{extra}", flush=True)
            manifest.append({"file": os.path.basename(dest), "name": name, "prompt": item["prompt"], "seconds": secs,
                             "seed": seed, "model": "stable_audio_3_small_sfx", "steps": 8, "cfg": 1.0,
                             "sampler": "lcm", "scheduler": "simple", "wall_s": round(wall, 2),
                             "graph_s": round(graph_s, 2) if graph_s is not None else None})
            json.dump(manifest, open(mpath, "w", encoding="utf-8"), indent=1)
    print(f"{len(items)} prompt(s) done, {failed} failed. Manifest: {mpath}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
