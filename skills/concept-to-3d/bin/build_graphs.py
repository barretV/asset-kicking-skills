"""
Build the two ComfyUI API graphs of the sculpt-donor pipeline (see the concept-to-3d SKILL.md)
from PixelArtistry's workflow 01 (MIT, github.com/pixelartistry/PixelArtistry-Hi3D, vendored as pa_wf01.json):

  coarse  image -> BiRefNet cut-out -> TRELLIS.2 int8 (structure, shape 512, upsample 1024) -> SaveGLB
          (the Pixal3D / MoGe branch and its switches are removed, so their models are never required)
  refine  coarse GLB (input/3d/...) -> Remesh x2 -> Hi3D 512 -> 1024 [-> 1536] -> SaveGLB each stage

Widget values are mapped to input names with the running server's /object_info, so the graphs follow
whatever ComfyUI build is installed.

  python bin/build_graphs.py <out_dir> --image creature_side.png --name creature [--seed 42] [--tseed 56]
         [--mesh 3d/creature_coarse.glb] [--stages 512,1024] [--no-remesh] [--dino dino_v3_vit_l.safetensors]
"""
import argparse
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def object_info(host):
    with urllib.request.urlopen(f"http://{host}/object_info") as r:
        return json.load(r)


def widget_names(info, ctype):
    spec = info[ctype]["input"]
    names = []
    for group in ("required", "optional"):
        for name, val in (spec.get(group) or {}).items():
            t, opts = val[0], (val[1] if len(val) > 1 and isinstance(val[1], dict) else {})
            if isinstance(t, list) or t in WIDGET_TYPES or "default" in opts:
                names.append(name)
                if opts.get("control_after_generate"):
                    names.append(None)  # the UI's "fixed/randomize" value, not an input
    return names


def to_api(ui, info, keep, extra=()):
    """keep: {ui_node_id: overrides dict}. Links to nodes not kept must be rewired by overrides."""
    links = {l[0]: l for l in ui["links"]}
    nodes = {n["id"]: n for n in ui["nodes"]}
    api = {}
    for nid, over in keep.items():
        n = nodes[nid]
        inputs = {}
        linked = set()
        for i in n.get("inputs", []):
            if i.get("link") is not None:
                l = links[i["link"]]
                inputs[i["name"]] = [str(l[1]), l[2]]
                linked.add(i["name"])
        vals = list(n.get("widgets_values") or [])
        for name, v in zip(widget_names(info, n["type"]), vals):
            if name and name not in linked:
                inputs[name] = v
        inputs.update(over)
        api[str(nid)] = {"class_type": n["type"], "inputs": inputs, "_meta": {"title": n.get("title", n["type"])}}
    for nid, node in api.items():
        for k, v in node["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in api and v[0] not in extra:
                raise SystemExit(f"node {nid}.{k} links to dropped node {v[0]}")
    return api


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--host", default="127.0.0.1:8188")
    ap.add_argument("--image", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--mesh", help="coarse GLB under ComfyUI/input (default 3d/<name>_coarse.glb)")
    ap.add_argument("--seed", type=int, default=42, help="Hi3D sampler seed")
    ap.add_argument("--tseed", type=int, default=56, help="TRELLIS.2 structure seed")
    ap.add_argument("--stages", default="512,1024")
    ap.add_argument("--no-remesh", action="store_true")
    ap.add_argument("--dino", default="dino_v3_vit_l.safetensors")
    a = ap.parse_args()
    ui = json.load(open(os.path.join(HERE, "pa_wf01.json"), encoding="utf-8"))
    info = object_info(a.host)
    os.makedirs(a.out, exist_ok=True)
    L = lambda nid, slot=0: [str(nid), slot]

    # ---- coarse: TRELLIS.2 only (switch nodes 10/18/19 and Pixal3D 9/14-17 dropped, rewired to 8 / 13)
    coarse = to_api(ui, info, {
        1: {"image": a.image}, 2: {}, 3: {}, 5: {"masks": L(3)},
        8: {}, 11: {}, 12: {"clip_name": a.dino}, 13: {"image": L(5)},
        20: {"model": L(8)}, 21: {}, 22: {}, 23: {},
        24: {"positive": L(13, 0), "negative": L(13, 1), "seed": a.tseed},
        25: {}, 26: {"model": L(8)}, 27: {},
        28: {"positive": L(13, 0), "negative": L(13, 1)}, 29: {}, 30: {}, 31: {}, 32: {},
        33: {"filename_prefix": f"hi3d/{a.name}_coarse"},
    })
    json.dump(coarse, open(os.path.join(a.out, f"{a.name}_coarse.api.json"), "w"), indent=1)

    # ---- refine: Load3D (no viewer, so a stub capture dict) -> Get3DComponents -> Remesh x2 -> Hi3D stages
    mesh = a.mesh or f"3d/{a.name}_coarse.glb"
    stages = [s for s in a.stages.split(",") if s]
    chain = {41: (42, 43, 44, "512"), 45: (46, 47, 48, "1024"), 49: (50, 51, 52, "1536")}
    keep = {1: {"image": a.image}, 2: {}, 3: {}, 36: {}, 37: {}, 38: {}, 39: {}, 40: {}}
    src = L(901)
    if not a.no_remesh:
        # RemeshMesh's sign_mode is a DynamicCombo: its sub-widgets go in as "sign_mode.<field>", so the
        # positional UI values are set by name here (AeroX's tip: solid, fill 20, twice, at 1024).
        remesh = {"resolution": 1024, "sign_mode": "solid", "sign_mode.fill": 20.0, "sign_mode.qef": False,
                  "band": 1.0, "project_back": 0.0, "fix_poles": False, "smooth_iters": 0,
                  "drop_small_components": 0.01, "precluster_max_verts": 20000000}
        keep[34] = dict(remesh, mesh=L(901))
        keep[35] = dict(remesh)
        src = L(35)
    prev = src
    for rid, (sid, did, gid, res) in chain.items():
        if res not in stages:
            continue
        keep[rid] = {"mesh": prev}
        keep[sid] = {"seed": a.seed}
        keep[did] = {}
        keep[gid] = {"filename_prefix": f"hi3d/{a.name}_r{res}"}
        prev = L(did)
    refine = to_api(ui, info, keep, extra=("900", "901"))
    capture = {"image": a.image, "mask": a.image, "normal": a.image, "recording": "", "camera_info": {}}
    refine["900"] = {"class_type": "Load3D", "inputs": {"model_file": mesh, "image": capture, "width": 1024, "height": 1024}}
    refine["901"] = {"class_type": "Get3DComponents", "inputs": {"model_3d": ["900", 6]}}
    json.dump(refine, open(os.path.join(a.out, f"{a.name}_refine.api.json"), "w"), indent=1)
    print("wrote", a.out, len(coarse), "+", len(refine), "nodes")


if __name__ == "__main__":
    main()
