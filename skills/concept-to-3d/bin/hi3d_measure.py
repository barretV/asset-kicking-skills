"""
Measure named masses of a model and an aligned sculpt donor in the model's frame (CPU only), to turn the
sculpt into numbers for a procedural build script. Uses the alignment json from hi3d_compare.py.

    python bin/hi3d_measure.py <model.npz> <sculpt.npz> <align.json> [--parts body,armor]

Regions (game axes, +Z forward) are boxes given as fractions of the model's bounding box, so they carry over
to other quadrupeds: head (front 14%), forelimbs (outer thirds of the front half, below the shoulder line),
shoulder hump (middle third, front half), haunch (rear 35%), tail (rear 12%).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi3d_compare import load, yaw  # noqa: E402

REGIONS = {  # name: (x range, y range, z range) as fractions of the model box (-9 / 9 = unbounded)
    "head": ((0.3, 0.7), (-9, 9), (0.86, 9)),
    "forelimbs": ((-9, 9), (-9, 0.45), (0.5, 0.9)),
    "shoulders": ((0.33, 0.67), (-9, 9), (0.5, 0.86)),
    "haunch": ((-9, 9), (-9, 9), (0.12, 0.47)),
    "tail": ((-9, 9), (-9, 9), (-9, 0.12)),
    "whole": ((-9, 9), (-9, 9), (-9, 9)),
}


def stats(v, box, reg):
    m = np.ones(len(v), bool)
    for i in range(3):
        lo, hi = box[i][0] + (box[i][1] - box[i][0]) * reg[i][0], box[i][0] + (box[i][1] - box[i][0]) * reg[i][1]
        m &= (v[:, i] >= lo) & (v[:, i] <= hi)
    if m.sum() < 10:
        return None
    p = v[m]
    return {"width": round(float(np.ptp(p[:, 0])), 3), "height": round(float(np.ptp(p[:, 1])), 3),
            "top": round(float(p[:, 1].max()), 3), "bottom": round(float(p[:, 1].min()), 3),
            "x_outer": round(float(np.abs(p[:, 0]).max()), 3), "z_front": round(float(p[:, 2].max()), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("sculpt")
    ap.add_argument("align")
    ap.add_argument("--parts", help="comma list of the model's mesh names to measure (default: all but helper meshes)")
    a = ap.parse_args()
    al = json.load(open(a.align))
    mv, _ = load(a.model, a.parts.split(",") if a.parts else None)
    sv, _ = load(a.sculpt, skip=())
    sv = yaw(sv, al["yaw"]) * al["scale"]
    sv += np.array(al["offset"], np.float32)
    box = al["model_box"]
    out = {}
    for name, reg in REGIONS.items():
        m, s = stats(mv, box, reg), stats(sv, box, reg)
        out[name] = {"model": m, "sculpt": s}
        if m and s:
            print(f"{name:10s} " + "  ".join(f"{k} {m[k]:6.2f}->{s[k]:6.2f}" for k in ("width", "height", "top", "x_outer")))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
