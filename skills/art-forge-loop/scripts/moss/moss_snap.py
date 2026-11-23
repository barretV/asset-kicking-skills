"""Snap MOSS pixel-art output (8x logical pixels) down to a clean native sprite.

Pipeline:
  1. estimate the flat background colour from the image border
  2. flood-fill from the border -> hard alpha (no AI matte, no halos)
  3. despill: erase bg-tinted fringe pixels touching the cutout
  4. union crop to the sprite
  5. BOX downsample by the logical pixel factor (8 by default)
  6. optional 1 px edge clean (pinholes filled, lone specks dropped)
  7. optional shared k-means palette (keeps every frame on one palette)
  8. write native PNG + nearest-neighbour preview + optional A/B sheet

Examples:
  python moss_snap.py raw native
  python moss_snap.py raw native --factor 8 --palette 32
  python moss_snap.py raw native --compare current_frame.png --scale 6
"""
import argparse
import json
import os
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFont

IMG_EXTS = (".png", ".webp", ".bmp", ".tga")
OFFS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
OFFS8 = OFFS4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


# --------------------------------------------------------------------------- #
# background
# --------------------------------------------------------------------------- #
def estimate_bg(rgb, ring=8):
    h, w, _ = rgb.shape
    r = max(1, min(ring, h // 2, w // 2))
    border = np.concatenate([
        rgb[:r].reshape(-1, 3), rgb[-r:].reshape(-1, 3),
        rgb[:, :r].reshape(-1, 3), rgb[:, -r:].reshape(-1, 3),
    ])
    q = np.round(border).astype(np.int16)
    uniq, counts = np.unique(q, axis=0, return_counts=True)
    return uniq[counts.argmax()].astype(np.float32)


def flood_from(mask, seeds):
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    dq = deque()
    ys, xs = np.where(mask & seeds)
    for y, x in zip(ys.tolist(), xs.tolist()):
        seen[y, x] = True
        dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in OFFS4:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                dq.append((ny, nx))
    return seen


def alpha_cutout(im, tol=38.0, despill=10.0, hole_min=20):
    rgb = np.array(im.convert("RGB")).astype(np.float32)
    h, w, _ = rgb.shape
    bg = estimate_bg(rgb)
    dist = np.sqrt(((rgb - bg) ** 2).sum(-1))
    bg_mask = flood_from(dist < tol, np.ones((h, w), bool))

    # enclosed near-exact bg pockets (inside the silhouette)
    strict = (dist < max(4.0, tol * 0.26)) & ~bg_mask
    seen = np.zeros_like(strict, bool)
    for y, x in zip(*np.where(strict)):
        if seen[y, x]:
            continue
        dq = deque([(y, x)])
        seen[y, x] = True
        pts = []
        while dq:
            cy, cx = dq.popleft()
            pts.append((cy, cx))
            for dy, dx in OFFS4:
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h and 0 <= nx < w and strict[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    dq.append((ny, nx))
        if len(pts) >= hole_min:
            for cy, cx in pts:
                bg_mask[cy, cx] = True

    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    for _ in range(2):
        if despill <= 0:
            break
        pad = np.pad(alpha == 0, 1, constant_values=False)
        edge = np.zeros_like(bg_mask)
        for dy, dx in OFFS8:
            edge |= pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        fringe = edge & (alpha > 0) & (dist < tol + despill)
        if not fringe.any():
            break
        alpha[fringe] = 0
    out = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), alpha])
    return Image.fromarray(out, "RGBA"), [int(v) for v in bg]


def union_crop(im, pad=1):
    bbox = im.getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    return im.crop((max(0, x0 - pad), max(0, y0 - pad),
                    min(im.width, x1 + pad), min(im.height, y1 + pad)))


# --------------------------------------------------------------------------- #
# native grid
# --------------------------------------------------------------------------- #
def downscale(im, factor):
    nw = max(1, im.width // factor)
    nh = max(1, im.height // factor)
    out = im.resize((nw, nh), Image.BOX)
    # BOX averages alpha too; pixel art needs hard 0/255 or the rim reads as a halo
    a = np.array(out)
    a[..., 3] = np.where(a[..., 3] >= 128, 255, 0)
    return Image.fromarray(a, "RGBA")


def clean_edges(im):
    """Fill 1 px pinholes and drop opaque pixels with <= 1 opaque neighbour."""
    a = np.array(im)
    alpha = a[..., 3] > 0
    h, w = alpha.shape
    pad_o = np.pad(alpha, 1, constant_values=False)
    on = np.zeros_like(alpha, dtype=np.uint8)
    acc = np.zeros((h, w, 3), np.float32)
    for dy, dx in OFFS8:
        nb = pad_o[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        on += nb
        acc += a[..., :3].astype(np.float32) * nb[..., None]
    fill = (~alpha) & (on >= 5)
    if fill.any():
        a[fill, :3] = np.clip(acc[fill] / on[fill, None], 0, 255).astype(np.uint8)
        a[fill, 3] = 255
    drop = (a[..., 3] > 0) & (on <= 1)
    a[drop, 3] = 0
    return Image.fromarray(a, "RGBA")


def kmeans_palette(images, k=32, iters=30, seed=7):
    pixels = []
    for im in images:
        a = np.array(im)
        pixels.append(a[a[..., 3] > 0][:, :3])
    pixels = np.concatenate(pixels, 0).astype(np.int16)
    if len(pixels) == 0:
        return images
    # unique colours first: keeps the palette stable frame to frame
    uniq, counts = np.unique(pixels, axis=0, return_counts=True)
    if len(uniq) <= k:
        lut = {tuple(c): tuple(c) for c in uniq}
        return [apply_lut(im, lut) for im in images]
    rng = np.random.default_rng(seed)
    center_idx = [int(counts.argmax())]
    d2 = ((uniq - uniq[center_idx[0]]) ** 2).sum(1).astype(np.float64)
    for _ in range(k - 1):
        d2 = np.maximum(d2, 0.0)
        total = d2.sum()
        if total <= 0:
            break
        pick = rng.choice(len(uniq), p=d2 / total)
        center_idx.append(int(pick))
        d2 = np.minimum(d2, ((uniq - uniq[pick]) ** 2).sum(1))
    centers = uniq[center_idx].astype(np.float32)
    for _ in range(iters):
        d = ((uniq[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        new = centers.copy()
        for j in range(len(centers)):
            m = lab == j
            if m.any():
                new[j] = (uniq[m] * counts[m, None]).sum(0) / counts[m].sum()
        if np.allclose(new, centers, atol=0.5):
            centers = new
            break
        centers = new
    lut = {}
    for c in uniq:
        j = int(((c.astype(np.float32) - centers) ** 2).sum(1).argmin())
        lut[tuple(int(v) for v in c)] = tuple(int(v) for v in np.round(centers[j]))
    return [apply_lut(im, lut) for im in images]


def apply_lut(im, lut):
    a = np.array(im)
    out = a.copy()
    ys, xs = np.where(a[..., 3] > 0)
    for y, x in zip(ys, xs):
        out[y, x, :3] = lut.get(tuple(int(v) for v in a[y, x, :3]), a[y, x, :3])
    return Image.fromarray(out, "RGBA")


# --------------------------------------------------------------------------- #
# preview
# --------------------------------------------------------------------------- #
def font(size):
    try:
        return ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", size)
    except Exception:
        return ImageFont.load_default()


def checker(size, cell=8, a=(44, 40, 56, 255), b=(58, 52, 72, 255)):
    im = Image.new("RGBA", size, a)
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=b)
    return im


def preview(im, scale):
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    out = checker((big.width + 24, big.height + 24), cell=max(4, scale))
    out.alpha_composite(big, (12, 12))
    return out


def scaled_to_height(im, target_h):
    s = target_h / im.height
    return im.resize((max(1, round(im.width * s)), target_h), Image.NEAREST)


def alpha_bbox(im, pad=1):
    b = im.getbbox()
    if not b:
        return im
    x0, y0, x1, y1 = b
    return im.crop((max(0, x0 - pad), max(0, y0 - pad),
                    min(im.width, x1 + pad), min(im.height, y1 + pad)))


def ab_sheet(left, right, ltitle, rtitle, out):
    # match body height, not canvas height: the two pipelines have different margins
    left, right = alpha_bbox(left), alpha_bbox(right)
    h = max(left.height, right.height)
    left, right = scaled_to_height(left, h), scaled_to_height(right, h)
    pad, top = 20, 48
    img = Image.new("RGBA", (pad + left.width + pad + right.width + pad, top + h + pad),
                    (20, 17, 28, 255))
    d = ImageDraw.Draw(img)
    d.text((pad, 12), ltitle, font=font(22), fill=(255, 168, 168, 255))
    d.text((pad * 2 + left.width, 12), rtitle, font=font(22), fill=(150, 235, 180, 255))
    bg1 = checker(left.size, 6); bg1.alpha_composite(left, (0, 0))
    bg2 = checker(right.size, 6); bg2.alpha_composite(right, (0, 0))
    img.alpha_composite(bg1, (pad, top))
    img.alpha_composite(bg2, (pad * 2 + left.width, top))
    img.save(out)
    print(f"sheet -> {out} {img.size}")


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="folder of raw MOSS PNGs")
    ap.add_argument("out", help="output folder for native sprites")
    ap.add_argument("--factor", type=int, default=8, help="logical pixel scale (default 8)")
    ap.add_argument("--tol", type=float, default=38.0)
    ap.add_argument("--despill", type=float, default=10.0)
    ap.add_argument("--palette", type=int, default=0,
                    help="optional shared palette size (0 keeps model colours)")
    ap.add_argument("--scale", type=int, default=8, help="preview zoom")
    ap.add_argument("--no-clean", action="store_true", help="skip the 1 px edge clean")
    ap.add_argument("--compare", default=None, help="sprite from the other pipeline for A/B")
    ap.add_argument("--compare-label", default="CURRENT")
    args = ap.parse_args()

    if not os.path.isdir(args.input):
        raise SystemExit(f"not a folder: {args.input}")
    files = sorted(f for f in os.listdir(args.input) if f.lower().endswith(IMG_EXTS))
    if not files:
        raise SystemExit(f"no images in {args.input}")
    os.makedirs(os.path.join(args.out, "preview"), exist_ok=True)

    natives = []
    for name in files:
        im = Image.open(os.path.join(args.input, name)).convert("RGBA")
        cut, bg = alpha_cutout(im, args.tol, args.despill)
        # downsample the FULL canvas first: cropping before the BOX pass moves
        # the 8x grid phase and produces soft/doubled blocks
        native = union_crop(downscale(cut, args.factor), pad=0)
        if not args.no_clean:
            native = clean_edges(native)
        stem = os.path.splitext(name)[0]
        # record the background we removed: hygiene.py uses it to unmix fringe
        # pixels at native size, where the 8:1 average leaves bg-tinted specks
        with open(os.path.join(args.out, stem + ".bg.json"), "w", encoding="utf-8") as fh:
            json.dump({"bg": [int(v) for v in bg], "tol": args.tol}, fh)
        natives.append((stem, native))
        cut.save(os.path.join(args.out, "preview", f"{stem}_cutout.png"))
        print(f"{name}: {im.size} -> native {native.size} bg={bg}", flush=True)

    if args.palette > 0:
        natives = [(stem, im) for (stem, _), im in
                   zip(natives, kmeans_palette([im for _, im in natives], args.palette))]

    for stem, native in natives:
        native.save(os.path.join(args.out, stem + ".png"))
        preview(native, args.scale).save(
            os.path.join(args.out, "preview", f"{stem}_{args.scale}x.png"))
        cols = len(set(map(tuple, np.array(native)[np.array(native)[..., 3] > 0][:, :3])))
        print(f"  -> {os.path.join(args.out, stem + '.png')}  {cols} colours")

    if args.compare and os.path.exists(args.compare):
        ref = Image.open(args.compare).convert("RGBA")
        for stem, native in natives:
            ab_sheet(ref, native, args.compare_label,
                     "MOSS pixel-art (native 8:1)",
                     os.path.join(args.out, f"compare_{stem}.png"))


if __name__ == "__main__":
    main()
