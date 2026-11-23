"""
Measure a model against a sculpt donor, CPU only (numpy + Pillow, no Blender, no GPU).

Both inputs are .npz dumps from hi3d_export_mesh.py (game axes: +Y up, +Z forward). The sculpt is aligned to
the model: yaw picked from 0/90/180/270 by best silhouette match (or --yaw), uniformly scaled to the model's
length along Z, centred on X, its lowest point put on the model's floor, and centred on the model's Z extent.

    python bin/hi3d_compare.py <model.npz> <sculpt.npz> <out_prefix> [--yaw 90] [--parts body,armor,...]

Writes <out_prefix>-overlay.png (side / front / top; model red, sculpt cyan, overlap white),
<out_prefix>.json (IoU per view, the alignment, and width / height / top-line profiles at 16 Z stations).
"""
import argparse
import json

import numpy as np
from PIL import Image, ImageDraw

VIEWS = {"side": (2, 1), "front": (0, 1), "top": (0, 2)}   # (horizontal axis, vertical axis)


def load(path, parts=None, skip=("Icosphere", "glow")):
    d = np.load(path)
    names = sorted({k[:-3] for k in d.files})
    vs, fs, off = [], [], 0
    for n in names:
        if parts and n not in parts:
            continue
        if not parts and n in skip:
            continue
        v, f = d[n + "__v"], d[n + "__f"]
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    return np.concatenate(vs), np.concatenate(fs)


def yaw(v, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    out = v.copy()
    out[:, 0] = c * v[:, 0] + s * v[:, 2]
    out[:, 2] = -s * v[:, 0] + c * v[:, 2]
    return out


def align(sv, mv, deg):
    sv = yaw(sv, deg)
    s = np.ptp(mv[:, 2]) / max(1e-9, np.ptp(sv[:, 2]))
    sv = sv * s
    sv[:, 0] -= (sv[:, 0].max() + sv[:, 0].min()) / 2 - (mv[:, 0].max() + mv[:, 0].min()) / 2
    sv[:, 1] -= sv[:, 1].min() - mv[:, 1].min()
    sv[:, 2] -= (sv[:, 2].max() + sv[:, 2].min()) / 2 - (mv[:, 2].max() + mv[:, 2].min()) / 2
    return sv, s


def raster(v, f, view, box, px):
    h, vv = VIEWS[view]
    (x0, x1), (y0, y1) = box[h], box[vv]
    k = px / max(x1 - x0, y1 - y0)
    W, H = int((x1 - x0) * k) + 4, int((y1 - y0) * k) + 4
    im = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(im)
    P = np.stack([(v[:, h] - x0) * k + 2, H - 2 - (v[:, vv] - y0) * k], 1)
    for tri in P[f]:
        dr.polygon([tuple(p) for p in tri], fill=255)
    return np.array(im) > 0


def profiles(v, f, mv_box, n=16):
    z0, z1 = mv_box[2]
    out = []
    for i in range(n):
        za, zb = z0 + (z1 - z0) * i / n, z0 + (z1 - z0) * (i + 1) / n
        m = (v[:, 2] >= za) & (v[:, 2] < zb)
        if m.sum() < 3:
            out.append(None)
            continue
        out.append({"z": round((za + zb) / 2, 3), "width": round(float(np.ptp(v[m, 0])), 3),
                    "top": round(float(v[m, 1].max()), 3), "bottom": round(float(v[m, 1].min()), 3)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("sculpt")
    ap.add_argument("out")
    ap.add_argument("--yaw", type=float)
    ap.add_argument("--parts")
    ap.add_argument("--px", type=int, default=420)
    a = ap.parse_args()
    mv, mf = load(a.model, a.parts.split(",") if a.parts else None)
    sv0, sf = load(a.sculpt, skip=())
    box = [(mv[:, i].min(), mv[:, i].max()) for i in range(3)]
    best = None
    for deg in ([a.yaw] if a.yaw is not None else (0, 90, 180, 270)):
        sv, s = align(sv0, mv, deg)
        bb = [(min(box[i][0], sv[:, i].min()), max(box[i][1], sv[:, i].max())) for i in range(3)]
        ious, masks = {}, {}
        for view in VIEWS:
            A, B = raster(mv, mf, view, bb, a.px), raster(sv, sf, view, bb, a.px)
            ious[view] = float((A & B).sum() / max(1, (A | B).sum()))
            masks[view] = (A, B)
        score = ious["side"] * 2 + ious["front"] + ious["top"]
        print(f"yaw {deg:5.0f}  IoU side {ious['side']:.3f} front {ious['front']:.3f} top {ious['top']:.3f}")
        if best is None or score > best[0]:
            best = (score, deg, s, sv, ious, masks)
    _, deg, s, sv, ious, masks = best
    tiles = []
    for view in VIEWS:
        A, B = masks[view]
        rgb = np.zeros(A.shape + (3,), np.uint8) + 18
        rgb[A & ~B] = (230, 60, 60)
        rgb[B & ~A] = (60, 210, 230)
        rgb[A & B] = (235, 235, 235)
        im = Image.fromarray(rgb)
        ImageDraw.Draw(im).text((6, 4), f"{view}  IoU {ious[view]:.2f}", fill=(255, 196, 76))
        tiles.append(im)
    W = sum(t.width for t in tiles) + 8 * (len(tiles) - 1)
    sheet = Image.new("RGB", (W, max(t.height for t in tiles)), (18, 12, 28))
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width + 8
    sheet.save(a.out + "-overlay.png")
    rep = {"yaw": float(deg), "scale": float(s), "iou": ious,
           "offset": [float(sv[:, i].min() - (yaw(sv0, deg) * s)[:, i].min()) for i in range(3)],
           "model_box": [list(map(float, b)) for b in box],
           "model": profiles(mv, mf, box), "sculpt": profiles(sv, sf, box)}
    json.dump(rep, open(a.out + ".json", "w"), indent=1, default=float)
    print(f"best yaw {deg}  scale {s:.3f}  IoU {ious}")


if __name__ == "__main__":
    main()
