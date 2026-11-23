#!/usr/bin/env python3
"""Measure and repair the 1-px artefacts a snap leaves behind.

    python bin/hygiene.py native/                    # report only
    python bin/hygiene.py native/ --out native_fixed  # fill 1 px holes
    python bin/hygiene.py native/ --out native_fixed --spurs   # also drop spurs
    python bin/hygiene.py native/ --fail-over 3      # exit 1 if >3 holes remain

Why this exists: `moss_snap.py`'s clean_edges fills pinholes and *then* drops pixels
with <= 1 opaque neighbour, with no second fill, so its own drop step opens new holes.
A hole is also invisible to a speck filter -- the pixel is transparent, so nothing is
"floating" and no opaque pixel is isolated. Both have to be counted separately.

A hole is a transparent pixel with >= 5 of its 8 neighbours opaque. It reads as a dark
dot because the background shows through. Filling uses the MODE of the opaque neighbour
colours, never an average, so no colour outside the sprite's existing palette can appear.

Needs numpy + Pillow. Exits 1 only with --fail-over and too many holes left.
"""
import argparse
import json
import os
import sys
from collections import deque

import numpy as np
from PIL import Image

EXTS = (".png",)


def neighbours(alpha):
    """Return (opaque mask, 8-neighbour count, orthogonal-neighbour count)."""
    on = alpha > 0
    pad = np.pad(on.astype(np.uint8), 1)
    h, w = on.shape
    n8 = np.zeros((h, w), np.uint8)
    orth = np.zeros((h, w), np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            nb = pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
            n8 += nb
            if dy == 0 or dx == 0:
                orth += nb
    return on, n8, orth


def _colour_set(a, on):
    freq = {}
    for c in a[on][:, :3]:
        t = tuple(int(v) for v in c)
        freq[t] = freq.get(t, 0) + 1
    return freq


def speck_mask(a, max_uses=3):
    """Pixels whose colour is rare overall AND absent from their 8 neighbours.

    That is exactly the salt-and-pepper noise a diffusion decode leaves after the
    8:1 snap: one pixel of a colour used nowhere else, sitting on a flat area.
    Design details (outlines, eye glints) reuse a palette colour, so they survive.
    """
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    freq = _colour_set(a, on)
    out = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            if not on[y, x]:
                continue
            t = tuple(int(v) for v in a[y, x, :3])
            if freq.get(t, 0) > max_uses:
                continue
            nbs = [tuple(int(v) for v in a[yy, xx, :3])
                   for yy in range(max(0, y - 1), min(h, y + 2))
                   for xx in range(max(0, x - 1), min(w, x + 2))
                   if (yy, xx) != (y, x) and on[yy, xx]]
            if nbs and t not in nbs:
                out[y, x] = True
    return out


def _despeckle_once(a, max_uses):
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    snap = a.copy()
    changed = 0
    for y, x in np.argwhere(speck_mask(a, max_uses)):
        nbs = [tuple(int(v) for v in snap[yy, xx, :3])
               for yy in range(max(0, y - 1), min(h, y + 2))
               for xx in range(max(0, x - 1), min(w, x + 2))
               if (yy, xx) != (y, x) and on[yy, xx]]
        if not nbs:
            continue
        uniq, counts = np.unique(np.array(nbs, dtype=np.uint8), axis=0, return_counts=True)
        a[y, x, :3] = uniq[int(counts.argmax())]
        changed += 1
    return changed


def despeckle(a, max_uses=3, passes=3):
    """Replace 1 px colour outliers with the majority neighbouring colour.

    No majority threshold: a colour that appears nowhere else in the sprite AND
    nowhere in the pixel's 8 neighbours is noise, whatever the neighbours look
    like. Real 1 px details (outline pixels, eye glints) reuse a palette colour
    many times, so `max_uses` keeps them. Repeat until it settles, because a
    replacement can expose the next outlier.
    """
    total = 0
    for _ in range(passes):
        changed = _despeckle_once(a, max_uses)
        total += changed
        if not changed:
            break
    return total


def prune_palette(a, min_uses=4):
    """Merge every colour used fewer than `min_uses` times into its nearest kept colour.

    This is the deterministic cure for stray pixels: a 1-2 px lilac patch left by the
    decode cannot survive if its colour is remapped wholesale. Use it when the sprite
    has to sit on a fixed palette anyway; pass min_uses=1 to disable.
    """
    if min_uses <= 1:
        return 0
    on = a[:, :, 3] > 0
    freq = _colour_set(a, on)
    keep = [c for c, n in freq.items() if n >= min_uses]
    rare = [(c, n) for c, n in freq.items() if n < min_uses]
    if not keep or not rare:
        return 0
    keep_arr = np.array(keep, dtype=np.int32)
    changed = 0
    for c, _n in rare:
        d = ((keep_arr - np.array(c, dtype=np.int32)) ** 2).sum(axis=1)
        target = keep_arr[int(d.argmin())]
        mask = (a[:, :, 0] == c[0]) & (a[:, :, 1] == c[1]) & (a[:, :, 2] == c[2]) & on
        a[mask, 0:3] = target
        changed += int(mask.sum())
    return changed


def _outside_mask(on):
    """Transparent pixels connected to the border (true background)."""
    h, w = on.shape
    outside = np.zeros_like(on)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not on[y, x] and not outside[y, x]:
                outside[y, x] = True
                dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if not on[y, x] and not outside[y, x]:
                outside[y, x] = True
                dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and not on[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                dq.append((ny, nx))
    return outside


def fill_enclosed(a, max_area=14, passes=6):
    """Fill small transparent regions fully enclosed by the sprite.

    Those are the thin crack lines the snap leaves through a body. Regions bigger
    than `max_area` are left alone: a gap between legs or under a wing is real
    negative space, not a crack.
    """
    h, w = a.shape[:2]
    total = 0
    for _ in range(passes):
        on = a[:, :, 3] > 0
        holes = (~on) & (~_outside_mask(on))
        if not holes.any():
            break
        seen = np.zeros_like(holes)
        progressed = 0
        for sy, sx in np.argwhere(holes):
            if seen[sy, sx]:
                continue
            blob = []
            dq = deque([(sy, sx)])
            seen[sy, sx] = True
            while dq:
                y, x = dq.popleft()
                blob.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and holes[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        dq.append((ny, nx))
            if len(blob) > max_area:
                continue
            for y, x in blob:
                nbs = [tuple(int(v) for v in a[yy, xx, :3])
                       for yy in range(max(0, y - 1), min(h, y + 2))
                       for xx in range(max(0, x - 1), min(w, x + 2))
                       if (yy, xx) != (y, x) and a[yy, xx, 3] > 0]
                if not nbs:
                    continue
                uniq, counts = np.unique(np.array(nbs, dtype=np.uint8), axis=0,
                                         return_counts=True)
                a[y, x, :3] = uniq[int(counts.argmax())]
                a[y, x, 3] = 255
                progressed += 1
        total += progressed
        if not progressed:
            break
    return total


def unmix_fringe(a, bg, t_min=0.3):
    """Strip background tint from silhouette-edge pixels.

    A native pixel on the edge is often an 8x8 average of fur and background, so it
    survives the cutout as a pale blue/grey dot. Treat the pixel as a mixture of the
    background and its dominant neighbour colour and, when the background share is
    real (t >= t_min), replace it with the pure neighbour colour. Shape is kept; the
    tint is not.
    """
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    pad = np.pad(~on, 1, constant_values=False)
    edge = np.zeros_like(on)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                edge |= pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    edge &= on
    b = np.array(bg, dtype=np.float64)
    changed = 0
    for y, x in np.argwhere(edge):
        nbs = [tuple(int(v) for v in a[yy, xx, :3])
               for yy in range(max(0, y - 1), min(h, y + 2))
               for xx in range(max(0, x - 1), min(w, x + 2))
               if (yy, xx) != (y, x) and a[yy, xx, 3] > 0]
        if not nbs:
            continue
        uniq, counts = np.unique(np.array(nbs, dtype=np.uint8), axis=0, return_counts=True)
        n = uniq[int(counts.argmax())].astype(np.float64)
        d = b - n
        denom = float((d * d).sum())
        if denom < 1.0:
            continue
        p = a[y, x, :3].astype(np.float64)
        t = float(((p - n) * d).sum() / denom)
        if t >= t_min:
            a[y, x, :3] = n.astype(np.uint8)
            changed += 1
    return changed


def _components(mask):
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    out = []
    for y0, x0 in np.argwhere(mask):
        if seen[y0, x0]:
            continue
        dq = deque([(y0, x0)])
        seen[y0, x0] = True
        pts = []
        while dq:
            y, x = dq.popleft()
            pts.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (dy or dx) and 0 <= ny < h and 0 <= nx < w \
                            and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        dq.append((ny, nx))
        out.append(pts)
    return out


def _edge_mask(on):
    h, w = on.shape
    pad = np.pad(~on, 1, constant_values=False)
    edge = np.zeros_like(on)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                edge |= pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    return edge


def fill_dark_blobs(a, lum_max=75.0, need=5, passes=4, protect_area=5):
    """Erode dark pixels that are surrounded by body colour.

    A shadow bar or a dark line the model painted inside a body reads as a black spot
    on the finished sprite. Only dark pixels with >= `need` non-dark opaque neighbours
    erode, so a 1-2 px outline (whose neighbours are transparent or dark) survives.
    Dark features that are fully enclosed AND at least `protect_area` px -- eyes, nose,
    mouth -- are left alone, which is what keeps this from hollowing out a face. Keep
    `protect_area` small (5): a mouth or nose can be only 6 px, and at 20 this pass ate
    the rabbit's mouth and nose outright.
    """
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    lum = (a[:, :, :3].astype(np.float64) * (0.299, 0.587, 0.114)).sum(-1)
    dark = on & (lum < lum_max)
    edge = _edge_mask(on)
    protected = np.zeros_like(dark)
    for pts in _components(dark):
        if len(pts) >= protect_area and not any(edge[y, x] for y, x in pts):
            for y, x in pts:
                protected[y, x] = True
    total = 0
    for _ in range(passes):
        lum = (a[:, :, :3].astype(np.float64) * (0.299, 0.587, 0.114)).sum(-1)
        dark = on & (lum < lum_max) & ~protected
        changed = 0
        for y, x in np.argwhere(dark):
            nbs = [(yy, xx) for yy in range(max(0, y - 1), min(h, y + 2))
                   for xx in range(max(0, x - 1), min(w, x + 2))
                   if (yy, xx) != (y, x) and on[yy, xx] and not dark[yy, xx]]
            if len(nbs) < need:
                continue
            cols = np.array([a[yy, xx, :3] for yy, xx in nbs], dtype=np.uint8)
            uniq, counts = np.unique(cols, axis=0, return_counts=True)
            a[y, x, :3] = uniq[int(counts.argmax())]
            changed += 1
        total += changed
        if not changed:
            break
    return total


def drop_orphan_outline(a, lum_max=75.0, min_body_ratio=0.45):
    """Delete dark pixels that outline empty space instead of a body.

    Outline pixels are supposed to sit next to body colour. When a thin dark curl is
    left around a transparent notch -- the model drew a gap and then outlined it, or the
    snapper kept the outline of a piece it cut away -- the artist sees a floating hook
    with nothing inside it. Whole dark components whose body-adjacency ratio falls below
    `min_body_ratio` are deleted. Real outline and enclosed features (eyes, nose) sit
    against body colour along most of their length, so they survive.
    """
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    lum = (a[:, :, :3].astype(np.float64) * (0.299, 0.587, 0.114)).sum(-1)
    dark = on & (lum < lum_max)
    body = on & ~dark
    dropped = 0
    for pts in _components(dark):
        touch = 0
        for y, x in pts:
            if any(body[yy, xx]
                   for yy in range(max(0, y - 1), min(h, y + 2))
                   for xx in range(max(0, x - 1), min(w, x + 2))
                   if (yy, xx) != (y, x)):
                touch += 1
        if touch / len(pts) < min_body_ratio:
            for y, x in pts:
                a[y, x] = (0, 0, 0, 0)
            dropped += len(pts)
    return dropped


def despeckle_clusters(a, max_area=2, max_share=0.008, min_dist=60.0, min_uses=5):
    """Remove tiny same-colour blobs whose colour is a minority in the sprite.

    Fringe that lands *inside* the silhouette is not an edge pixel, and a 2 px blob is
    not an isolated pixel, so it survives both the fringe unmix and the single-pixel
    despeckle. That is exactly the stray lilac/blue speck pair you can see on a gill or
    under an arm.    Three gates keep real art safe: the colour must be a small share of the sprite,
    the blob must be tiny, and its colour must sit far from the surrounding majority.
    A shading patch fails that last test (it is a near-neighbour of the colour around
    it), while a purple fringe pixel on a pink gill passes it easily.
    """
    h, w = a.shape[:2]
    on = a[:, :, 3] > 0
    freq = _colour_set(a, on)
    total = int(on.sum()) or 1
    limit = max(min_uses, int(total * max_share))
    rare = {c for c, n in freq.items() if n <= limit}
    if not rare:
        return 0
    snap = a.copy()
    visited = np.zeros((h, w), bool)
    changed = 0
    for y0, x0 in np.argwhere(on):
        if visited[y0, x0]:
            continue
        c0 = tuple(int(v) for v in a[y0, x0, :3])
        if c0 not in rare:
            continue
        blob = []
        dq = deque([(y0, x0)])
        visited[y0, x0] = True
        while dq:
            y, x = dq.popleft()
            blob.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (dy or dx) and 0 <= ny < h and 0 <= nx < w \
                            and not visited[ny, nx] and on[ny, nx] \
                            and tuple(int(v) for v in a[ny, nx, :3]) == c0:
                        visited[ny, nx] = True
                        dq.append((ny, nx))
        if len(blob) > max_area:
            continue
        blobset = set(blob)
        ring = [tuple(int(v) for v in snap[yy, xx, :3])
                for y, x in blob
                for yy in range(max(0, y - 1), min(h, y + 2))
                for xx in range(max(0, x - 1), min(w, x + 2))
                if (yy, xx) not in blobset and on[yy, xx]]
        if not ring:
            continue
        uniq, counts = np.unique(np.array(ring, dtype=np.uint8), axis=0, return_counts=True)
        target = uniq[int(counts.argmax())]
        gap = ((target.astype(np.int32) - np.array(c0, dtype=np.int32)) ** 2).sum()
        if float(gap) < min_dist * min_dist:
            continue          # close to its surroundings: that is shading, not noise
        for y, x in blob:
            a[y, x, :3] = target
            changed += 1
    return changed


def load_bg(path):
    """Background colour written by moss_snap.py next to each native PNG."""
    side = os.path.splitext(path)[0] + ".bg.json"
    if not os.path.exists(side):
        return None
    try:
        with open(side, encoding="utf-8") as fh:
            return json.load(fh).get("bg")
    except Exception:
        return None


def measure(a, hole_need=5, max_uses=3):
    on, n8, orth = neighbours(a[:, :, 3])
    freq = _colour_set(a, on)
    holes = (~on) & (n8 >= hole_need)
    floating = on & (n8 == 0)
    return dict(
        colours=len(freq),
        longtail=sum(1 for n in freq.values() if n <= 4),
        rare_px=sum(n for n in freq.values() if n <= 4),
        specks=int(speck_mask(a, max_uses).sum()),
        holes=int(holes.sum()),
        spurs=int((on & (orth == 1)).sum()),
        floating=int(floating.sum()),
    )


def fill_holes(a, hole_need=5, passes=4):
    """Fill 1-px holes with the dominant neighbouring colour. Returns px filled."""
    h, w = a.shape[:2]
    total = 0
    for _ in range(passes):
        on, n8, _ = neighbours(a[:, :, 3])
        cand = np.argwhere((~on) & (n8 >= hole_need))
        if not len(cand):
            break
        progressed = 0
        for y, x in cand:
            nb = [
                tuple(int(v) for v in a[y + dy, x + dx, :3])
                for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if (dy or dx)
                and 0 <= y + dy < h and 0 <= x + dx < w
                and a[y + dy, x + dx, 3] > 0
            ]
            if not nb:
                continue
            uniq, counts = np.unique(np.array(nb, dtype=np.uint8), axis=0, return_counts=True)
            a[y, x, :3] = uniq[int(counts.argmax())]
            a[y, x, 3] = 255
            progressed += 1
        total += progressed
        if not progressed:
            break
    return total


def drop_spurs(a):
    """Clear opaque pixels with a single orthogonal neighbour. Returns px dropped."""
    on, _n8, orth = neighbours(a[:, :, 3])
    drop = on & (orth <= 1)
    a[drop, 3] = 0
    return int(drop.sum())


def process(path, out, spurs, hole_need, no_specks=False, min_uses=4, bg=None,
            no_blobs=False, dark_blobs=False, orphan=False):
    im = Image.open(path).convert("RGBA")
    a = np.array(im)
    before = measure(a, hole_need)
    palette_before = {tuple(int(v) for v in c) for c in a[a[:, :, 3] > 0][:, :3]}

    bgc = bg or load_bg(path)
    unmixed = unmix_fringe(a, bgc) if bgc else 0
    # neighbour-based fill catches pinholes that reach the silhouette edge (a crack
    # line does); enclosed fill catches thin gaps fully inside a body. Need both.
    filled = fill_holes(a, hole_need) + fill_enclosed(a)
    specks = 0 if no_specks else despeckle(a)
    blobs = 0 if (no_specks or no_blobs) else despeckle_clusters(a, min_uses=min_uses)
    darkblobs = fill_dark_blobs(a) if dark_blobs else 0
    orphans = drop_orphan_outline(a) if orphan else 0
    dropped = drop_spurs(a) if spurs else 0
    pruned = prune_palette(a, min_uses)
    filled += fill_holes(a, hole_need) + fill_enclosed(a)   # never leave a gap behind a repair

    after = measure(a, hole_need)
    palette_after = {tuple(int(v) for v in c) for c in a[a[:, :, 3] > 0][:, :3]}
    new_colours = len(palette_after - palette_before)

    print("%-26s %dx%d  colours=%d longtail=%d specks=%d holes=%d spurs=%d float=%d"
          % (os.path.basename(path), im.width, im.height, before["colours"],
             before["longtail"], before["specks"], before["holes"], before["spurs"],
             before["floating"]))
    if out:
        print("    repaired: holes %d -> %d, specks %d -> %d, blobs %d px, dark blobs %d px, "
              "orphan outline %d px, spurs %d -> %d, longtail %d -> %d, filled %d px, "
              "fringe %d px, spurs dropped %d, pruned %d px, new colours %d"
              % (before["holes"], after["holes"], before["specks"], after["specks"], blobs,
                 darkblobs, orphans, before["spurs"], after["spurs"], before["longtail"],
                 after["longtail"], filled, unmixed, dropped, pruned, new_colours))
    if new_colours:
        print("    WARN  %d colour(s) outside the original palette" % new_colours)
    if not out:
        return before, after, None
    os.makedirs(out if os.path.isdir(out) or not out.lower().endswith(EXTS) else os.path.dirname(out),
                exist_ok=True)
    dest = os.path.join(out, os.path.basename(path)) if not out.lower().endswith(EXTS) else out
    Image.fromarray(a, "RGBA").save(dest)
    return before, after, dest


def main():
    ap = argparse.ArgumentParser(description="measure/repair 1-px snap artefacts")
    ap.add_argument("input", help="sprite PNG or a folder of PNGs")
    ap.add_argument("--out", default="", help="output folder (or .png path); omit to only report")
    ap.add_argument("--spurs", action="store_true", help="also drop 1-px spurs")
    ap.add_argument("--no-despeckle", action="store_true",
                    help="keep rare-colour isolated pixels (they are usually model noise)")
    ap.add_argument("--fill-dark-blobs", action="store_true",
                    help="erode dark shadow bars/lines inside a body (keeps enclosed "
                         "features such as eyes); off by default")
    ap.add_argument("--drop-orphan-outline", action="store_true",
                    help="delete thin dark curls that outline empty space instead of a body")
    ap.add_argument("--no-blob", action="store_true",
                    help="keep tiny same-colour blobs (they can be intentional shading "
                         "patches, so this is the safer setting for a signed-off sprite)")
    ap.add_argument("--hole-need", type=int, default=5,
                    help="opaque 8-neighbours required to call a gap a hole (default 5)")
    ap.add_argument("--min-uses", type=int, default=4,
                    help="merge colours used fewer times than this into the nearest kept "
                         "colour (1 disables); default 4")
    ap.add_argument("--fail-over", type=int, default=None,
                    help="exit 1 if more than N holes remain")
    args = ap.parse_args()

    if os.path.isdir(args.input):
        files = sorted(os.path.join(args.input, f) for f in os.listdir(args.input)
                       if f.lower().endswith(EXTS))
    else:
        files = [args.input]
    if not files:
        raise SystemExit("no PNGs in %s" % args.input)

    worst = 0
    for path in files:
        _before, after, _dest = process(path, args.out, args.spurs, args.hole_need,
                                        args.no_despeckle, args.min_uses, None,
                                        args.no_blob, args.fill_dark_blobs,
                                        args.drop_orphan_outline)
        worst = max(worst, after["holes"])

    if args.fail_over is not None and worst > args.fail_over:
        print("\nFAIL  %d hole(s) remain (limit %d)" % (worst, args.fail_over))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
