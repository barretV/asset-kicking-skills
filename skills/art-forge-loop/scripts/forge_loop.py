"""Graded art iteration loop on local MOSS/ComfyUI: generate -> judge -> refine, per target, until a score bar.

    python ~/.claude/skills/art-forge-loop/scripts/forge_loop.py JOB_DIR gen       # one round for every target that needs one
    python ~/.claude/skills/art-forge-loop/scripts/forge_loop.py JOB_DIR sheets    # judging sheets for the newest round of each target
    python ~/.claude/skills/art-forge-loop/scripts/forge_loop.py JOB_DIR report    # N of M good, how many left, lowest scores
    python .claude/skills/art-forge-loop/scripts/forge_loop.py JOB_DIR status    # counts: final / pending / unjudged / out of rounds
    python ~/.claude/skills/art-forge-loop/scripts/forge_loop.py JOB_DIR wait [S]  # block up to S s (540) while a gen is running

JOB_DIR/job.json (written by the agent, see SKILL.md) defines targets and settings.
JOB_DIR/picks.json holds the verdicts (also written by the agent after judging).
Outputs go to JOB_DIR/out/<target>/r<N>-s<seed>.png and JOB_DIR/sheets/.
Paths in job.json and picks.json are relative to the directory you run from (the project root).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageDraw

REPO = os.getcwd()
# MOSS tools: $FORGE_MOSS_BIN, else the project's own art/pipeline/bin, else the copies bundled with this skill
_HERE = os.path.dirname(os.path.abspath(__file__))
BIN = next(b for b in (os.environ.get('FORGE_MOSS_BIN'), os.path.join(REPO, 'art', 'pipeline', 'bin'), os.path.join(_HERE, 'moss'))
           if b and os.path.exists(os.path.join(b, 'moss_generate.py')))
DEFAULTS = {
    'bar': 9.5, 'max_rounds': 10, 'seeds': 2, 'size': 768, 'init_scale': 8, 'factor': 8, 'palette': 32,
    'first_denoise': 0.66, 'polish_denoise': 0.45, 'fine_denoise': 0.38, 'fine_at': 9.3, 'speck': 60,
    'style': 'pxl8x, single isolated pixel art sprite, {prompt}, detailed 16-bit SNES era pixel art, rich 5 tone shading, '
             'rim light, crisp clean clusters, one dark outline, light from the top left, no floating particles, '
             'centered on a flat lavender background',
    'mode': 'pixel',
}
ILLUSTRATION = {
    'style': '{prompt}, polished 2D game character illustration, clean confident line art, cel shading with soft gradients, '
             'vibrant harmonious colours, rim light, crisp readable silhouette, high detail, full body, '
             'centered on a flat plain lavender background, no white outline border, no sticker edge, no ground shadow, no text, no frame',
    'size': 1024, 'out_px': 384, 'seeds': 2, 'lora': 0.0, 'bg_tol': 38,
}


def load(job):
    cfg = dict(DEFAULTS)
    user = json.load(open(os.path.join(job, 'job.json'), encoding='utf-8'))
    if user.get('mode') == 'illustration':
        cfg.update(ILLUSTRATION)
    cfg.update(user)
    pp = os.path.join(job, 'picks.json')
    picks = json.load(open(pp, encoding='utf-8')) if os.path.exists(pp) else {}
    return cfg, picks


def slug(key):
    return re.sub(r'[^A-Za-z0-9_.-]+', '__', key)


def despeck(path, keep):
    """Drop small detached islands (floating leaves, sparks, specks) that are not part of the main shape."""
    im = Image.open(path).convert('RGBA')
    w, h = im.size
    px = im.load()
    seen, comps = set(), []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] and (x, y) not in seen:
                st, c = [(x, y)], []
                seen.add((x, y))
                while st:
                    cx, cy = st.pop()
                    c.append((cx, cy))
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            q = (cx + dx, cy + dy)
                            if 0 <= q[0] < w and 0 <= q[1] < h and q not in seen and px[q][3]:
                                seen.add(q)
                                st.append(q)
                comps.append(c)
    if len(comps) < 2:
        return
    big = max(len(c) for c in comps)
    for c in comps:
        if len(c) < keep and len(c) < big:
            for p in c:
                px[p] = (0, 0, 0, 0)
    bb = im.getbbox()
    if bb:
        im.crop(bb).save(path)


BG = (208, 200, 216)  # the flat lavender MOSS is asked to paint on


def smooth_init(src, dst, size, fill=0.82):
    """Illustration init: scale smoothly (not nearest) to ~82% of the canvas, centred on the flat background."""
    im = Image.open(src).convert('RGBA')
    k = fill * size / max(im.size)
    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    c = Image.new('RGBA', (size, size), BG + (255,))
    c.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    c.convert('RGB').save(dst)


def strip_halo(im, passes=6, light=200, sat=40, ref=BG, fringe=45):
    """Peel a painted white 'sticker' outline and background-tinted rims (also around removed pockets):
    repeatedly drop edge pixels that are near-white or near the background colour, then remove 1-2 px stray lines."""
    import numpy as np
    from PIL import ImageFilter
    a = np.asarray(im.convert('RGBA')).copy()
    rgb = a[..., :3].astype(int)
    pale = (rgb.min(-1) >= light) & (rgb.max(-1) - rgb.min(-1) <= sat)
    pale |= np.sqrt(((rgb - np.array(ref)) ** 2).sum(-1)) < fringe
    for _ in range(passes):
        on = a[..., 3] > 0
        edge = on & ~(np.roll(on, 1, 0) & np.roll(on, -1, 0) & np.roll(on, 1, 1) & np.roll(on, -1, 1))
        kill = edge & pale
        if not kill.any():
            break
        a[..., 3][kill] = 0
    al = Image.fromarray(a[..., 3])
    opened = np.asarray(al.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)))
    a[..., 3] = np.minimum(a[..., 3], opened)
    return Image.fromarray(a)


_REMBG = []


def ai_mask(im):
    """Character matte from rembg's isnet-anime model (pip install "rembg[cpu]"), or None if it is not installed."""
    if not _REMBG:
        try:
            from rembg import new_session
            _REMBG.append(new_session('isnet-anime'))
        except Exception:
            _REMBG.append(None)
    if _REMBG[0] is None:
        return None
    from rembg import remove
    return remove(im.convert('RGB'), session=_REMBG[0], only_mask=True).convert('L')


def cutout(src, dst, tol, out_px, hole_tol=32):
    """Remove the flat background by flood fill from the border, soften the edge, crop, and downscale."""
    import numpy as np
    from collections import deque
    im = Image.open(src).convert('RGB')
    a = np.asarray(im).astype(np.int32)
    h, w, _ = a.shape
    ref = np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0)
    close = np.sqrt(((a - ref) ** 2).sum(-1)) < tol
    bg = np.zeros((h, w), bool)
    q = deque((y, x) for y in range(h) for x in (0, w - 1)) + deque((y, x) for x in range(w) for y in (0, h - 1))
    while q:
        y, x = q.popleft()
        if 0 <= y < h and 0 <= x < w and close[y, x] and not bg[y, x]:
            bg[y, x] = True
            q.extend(((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))
    # enclosed pockets (between a tail and a body, under an arm): background-coloured blobs the border
    # flood fill cannot reach. Tighter tolerance than the border pass so lavender characters survive.
    # With the AI matte available it handles pockets by meaning; the colour pass then only takes near-exact
    # background (shaded white fur sits within ~30 of the lavender and must survive).
    ai_ok = ai_mask(im) is not None
    near = np.sqrt(((a - ref) ** 2).sum(-1)) < (min(hole_tol, 12) if ai_ok else hole_tol)
    seen = bg.copy()
    min_area = max(30, int(h * w * 0.0004))  # smaller than this eats shaded white fur (tested)
    for y0, x0 in zip(*np.nonzero(near & ~seen)):
        if seen[y0, x0]:
            continue
        comp, q2 = [], deque([(y0, x0)])
        seen[y0, x0] = True
        while q2:
            y, x = q2.popleft()
            comp.append((y, x))
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q2.append((ny, nx))
        if len(comp) >= min_area:
            ys, xs = zip(*comp)
            bg[list(ys), list(xs)] = True
    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8))
    ai = ai_mask(im)
    if ai is not None:
        # the AI matte only ever REMOVES (background pockets the colour pass missed); it never fades the character.
        # Sanity guard: if it rejects much of what the colour pass kept, it misread the image, so ignore it.
        fg = ~bg
        keep = np.asarray(ai) >= 128
        if fg.sum() and (keep & fg).sum() / fg.sum() >= 0.9:
            bg = bg | ~keep
        alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8))
    from PIL import ImageFilter
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = im.convert('RGBA')
    out.putalpha(alpha)
    out = strip_halo(out)
    bb = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if bb:
        out = out.crop(bb)
    if dst.endswith('.png'):
        out.save(dst[:-4] + '-hi.png')   # full-size cutout: what SVG tracing works from
    if out_px and max(out.size) > out_px:
        k = out_px / max(out.size)
        out = out.resize((round(out.width * k), round(out.height * k)), Image.LANCZOS)
    out.save(dst)


def apply_mask(init, out_path, mask_path, grow=1):
    """Keep the init everywhere except the marked spots; take the new generation only inside them.

    The mask is a PNG drawn on the init image (review page "Mark bad spots"): any non-transparent
    pixel is marked. It is grown by `grow` px so the repaint blends past the stroke edge. The new
    image is aligned onto the init canvas by the offset that best matches the UNMARKED area (a
    generation can shift a pixel or two), so the result is always on the init's own canvas and
    the same mask keeps lining up in later rounds. Transparent new pixels inside the mask erase,
    so a marked stray speck or leftover background is removed, not just recoloured.
    Returns the share of the mask that changed (0..1).
    """
    import numpy as np
    I = np.array(Image.open(init).convert('RGBA'))
    O = Image.open(out_path).convert('RGBA')
    h, w = I.shape[:2]
    if abs(O.width / w - 1) > 0.08 or abs(O.height / h - 1) > 0.08:
        O = O.resize((w, h), Image.NEAREST if cfg_mode_pixel(I) else Image.LANCZOS)
    O = np.array(O)
    M = np.array(Image.open(mask_path).convert('RGBA').resize((w, h), Image.NEAREST))[:, :, 3] > 0
    for _ in range(max(0, grow)):
        g = M.copy()
        g[1:] |= M[:-1]; g[:-1] |= M[1:]; g[:, 1:] |= M[:, :-1]; g[:, :-1] |= M[:, 1:]
        M = g
    oh, ow = O.shape[:2]
    keep = ~M & (I[:, :, 3] > 0)
    ys, xs = np.nonzero(keep)
    best = (-1.0, 0, 0)
    r = max(4, int(max(w, h) * 0.1))
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            yy, xx = ys - dy, xs - dx               # pixel (y, x) on the init canvas comes from O[y-dy, x-dx]
            ok = (yy >= 0) & (yy < oh) & (xx >= 0) & (xx < ow)
            if not ok.any():
                continue
            a = I[ys[ok], xs[ok]].astype(int)
            b = O[yy[ok], xx[ok]].astype(int)
            score = ((np.abs(a[:, :3] - b[:, :3]).sum(1) < 60) & (b[:, 3] > 0)).sum() / max(1, len(ys))
            if score > best[0]:
                best = (score, dx, dy)
    _, dx, dy = best
    res = I.copy()
    my, mx = np.nonzero(M)
    sy, sx = my - dy, mx - dx
    ok = (sy >= 0) & (sy < oh) & (sx >= 0) & (sx < ow)
    res[my, mx] = 0                                   # outside the new image's reach: erase
    res[my[ok], mx[ok]] = O[sy[ok], sx[ok]]
    Image.fromarray(res).save(out_path)
    changed = (np.abs(res[M].astype(int) - I[M].astype(int)).sum(1) > 0).mean() if M.any() else 0.0
    return float(changed)


def cfg_mode_pixel(arr):
    """Pixel art has few colours; an illustration has thousands. Picks the resize filter for a size mismatch."""
    import numpy as np
    return len(np.unique(arr.reshape(-1, 4), axis=0)) < 400


def generate(cfg, job, key, rnd, init, denoise, note):
    t = cfg['targets'][key]
    prompt = cfg['style'].replace('{prompt}', t['prompt'] + (', ' + note if note else ''))
    work = os.path.join(job, 'out', slug(key))
    os.makedirs(work, exist_ok=True)
    made = []
    for i in range(cfg['seeds']):
        seed = 1000 * rnd + 17 * i + 7
        tmp = os.path.join(work, f'_tmp{i}')
        shutil.rmtree(tmp, ignore_errors=True)
        raw, nat, fix = (os.path.join(tmp, d) for d in ('raw', 'native', 'fixed'))
        os.makedirs(raw)
        if cfg['mode'] == 'illustration':
            os.makedirs(fix)
            sinit = os.path.join(tmp, 'init.png')
            smooth_init(init, sinit, cfg['size'])
            try:
                subprocess.run([sys.executable, os.path.join(BIN, 'moss_generate.py'), '--init', sinit, '--init-scale', '1',
                                '--size', str(cfg['size']), '--denoise', str(denoise), '--seed', str(seed), '--lora', str(cfg['lora']),
                                '--prefix', f'forge/{slug(key)}', '--out', raw, '--prompt', prompt], check=True, stdout=subprocess.DEVNULL)
            except subprocess.CalledProcessError as e:
                print('FAILED', key, seed, e, flush=True)
                continue
            for f in sorted(os.listdir(raw)):
                if f.endswith('.png'):
                    cutout(os.path.join(raw, f), os.path.join(fix, f), cfg['bg_tol'], cfg['out_px'], cfg.get('hole_tol', 32))
        else:
          try:
            for cmd in (
                [sys.executable, os.path.join(BIN, 'moss_generate.py'), '--init', init, '--init-scale', str(cfg['init_scale']),
                 '--size', str(cfg['size']), '--denoise', str(denoise), '--seed', str(seed),
                 '--prefix', f'forge/{slug(key)}', '--out', raw, '--prompt', prompt],
                [sys.executable, os.path.join(BIN, 'moss_snap.py'), raw, nat, '--factor', str(cfg['factor']), '--palette', str(cfg['palette'])],
                [sys.executable, os.path.join(BIN, 'hygiene.py'), nat, '--out', fix, '--spurs'],
            ):
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
          except subprocess.CalledProcessError as e:
            print('FAILED', key, seed, e, flush=True)
            continue
        outs = sorted(f for f in os.listdir(fix) if f.endswith('.png') and not f.endswith('-hi.png'))
        if not outs:
            continue
        dst = os.path.join(work, f'r{rnd}-s{seed}.png')
        shutil.copy(os.path.join(fix, outs[-1]), dst)
        hi = os.path.join(fix, outs[-1])[:-4] + '-hi.png'
        if os.path.exists(hi):
            shutil.copy(hi, dst[:-4] + '-hi.png')
        shutil.rmtree(tmp, ignore_errors=True)
        if cfg['mode'] == 'pixel':
            despeck(dst, cfg['speck'])
        if t.get('mask'):
            # repaint only the marked spots: the result stays on the init's canvas, so a full-size
            # -hi trace of the free generation would no longer match it
            ch = apply_mask(init, dst, t['mask'], int(t.get('mask_grow', 1 if cfg['mode'] == 'pixel' else 4)))
            if os.path.exists(dst[:-4] + '-hi.png'):
                os.remove(dst[:-4] + '-hi.png')
            print(f'  masked: {ch:.0%} of the marked area repainted', flush=True)
        made.append(dst)
    with open(os.path.join(work, 'log.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps({'round': rnd, 'init': init, 'denoise': denoise, 'prompt': prompt, 'results': made}) + '\n')
    with open(os.path.join(work, f'r{rnd}.done'), 'w') as f:
        f.write(str(len(made)))
    print(f'r{rnd} {key}: {len(made)} made', flush=True)


def plan(cfg, job, picks):
    """(key, round, init, denoise, note) for every target that needs a round now."""
    todo = []
    for key, t in cfg['targets'].items():
        done = lambda r: os.path.exists(os.path.join(job, 'out', slug(key), f'r{r}.done'))
        pk = picks.get(key)
        if not pk:
            if not done(1):
                todo.append((key, 1, t['init'], cfg['first_denoise'], t.get('note', '')))
            continue
        if pk.get('final'):
            continue
        rnd = int(pk.get('round', 1)) + 1
        if rnd > cfg['max_rounds'] or done(rnd):
            continue
        dn = pk.get('denoise') or (cfg['fine_denoise'] if pk.get('score', 0) >= cfg['fine_at'] else cfg['polish_denoise'])
        todo.append((key, rnd, pk['path'], float(dn), pk.get('note', '')))
    return todo


def cmd_gen(job):
    cfg, picks = load(job)
    todo = plan(cfg, job, picks)
    print(f'{len(todo)} targets this round', flush=True)
    for key, rnd, init, dn, note in todo:
        generate(cfg, job, key, rnd, init, dn, note)


def latest_unjudged(cfg, job, picks, key):
    d = os.path.join(job, 'out', slug(key))
    if not os.path.isdir(d):
        return None, []
    rounds = sorted({int(m.group(1)) for f in os.listdir(d) for m in [re.match(r'r(\d+)-s\d+\.png$', f)] if m})
    judged = int(picks.get(key, {}).get('round', 0))
    newer = [r for r in rounds if r > judged]
    if not newer:
        return None, []
    r = newer[-1]
    return r, sorted(os.path.join(d, f) for f in os.listdir(d) if re.match(rf'r{r}-s\d+\.png$', f))


def cmd_sheets(job, per=7, S=2):
    cfg, picks = load(job)
    if cfg['mode'] == 'illustration':
        S = 1
    rows = []
    for key, t in cfg['targets'].items():
        if picks.get(key, {}).get('final'):
            continue
        r, cands = latest_unjudged(cfg, job, picks, key)
        if not cands:
            continue
        pk = picks.get(key)
        ims = [('ref', t.get('ref', t['init']))]
        if pk:
            ims.append((f'best {pk["score"]:.1f}', pk.get('best', pk['path'])))
        ims += [(os.path.basename(c)[:-4], c) for c in cands]
        rows.append((key, ims))
    sd = os.path.join(job, 'sheets')
    shutil.rmtree(sd, ignore_errors=True)
    os.makedirs(sd)
    paths = []
    for n in range(0, len(rows), per):
        chunk = rows[n:n + per]
        def opn(p):
            im = Image.open(p).convert('RGBA')
            if cfg['mode'] == 'illustration' and max(im.size) != 260:
                k = 260 / max(im.size)
                im = im.resize((round(im.width * k), round(im.height * k)), Image.NEAREST if k > 1 else Image.LANCZOS)
            return im
        loaded = [(k, [(lab, opn(p)) for lab, p in ims]) for k, ims in chunk]
        cw = max(im.width for _, ims in loaded for _, im in ims) * S + 12
        ch = max(im.height for _, ims in loaded for _, im in ims) * S + 16
        cols = max(len(ims) for _, ims in loaded)
        sheet_bg = (224, 33, 138, 255) if cfg['mode'] == 'illustration' else (40, 44, 60, 255)  # magenta: leftovers pop
        sh = Image.new('RGBA', (cols * cw, len(loaded) * ch), sheet_bg)
        d = ImageDraw.Draw(sh)
        for ri, (k, ims) in enumerate(loaded):
            for ci, (lab, im) in enumerate(ims):
                im = im.resize((im.width * S, im.height * S), Image.NEAREST)
                sh.alpha_composite(im, (ci * cw + (cw - im.width) // 2, ri * ch + ch - im.height - 2))
                d.text((ci * cw + 3, ri * ch + 2), (k if ci == 0 else '') + ' ' + lab, fill='white')
        p = os.path.join(sd, f'sheet-{n // per + 1:02d}.png')
        sh.save(p)
        paths.append(p)
    print(f'{len(rows)} targets to judge')
    for p in paths:
        print(p)


def cmd_status(job):
    cfg, picks = load(job)
    final = [k for k in cfg['targets'] if picks.get(k, {}).get('final')]
    unjudged = [k for k in cfg['targets'] if not picks.get(k, {}).get('final') and latest_unjudged(cfg, job, picks, k)[1]]
    todo = plan(cfg, job, picks)
    out = [k for k in cfg['targets'] if k not in final and k not in unjudged and not any(t[0] == k for t in todo)]
    print(json.dumps({'targets': len(cfg['targets']), 'final': len(final), 'to_judge': len(unjudged),
                      'to_generate': len(todo), 'stalled_or_out_of_rounds': out}, indent=1))
    if len(final) == len(cfg['targets']):
        print('ALL FINAL')


def cmd_report(job, lowest=8):
    """Progress report: how many pass the bar, how many left, the lowest scores, rounds used."""
    jp = os.path.join(job, 'job.json')
    cfg = dict(DEFAULTS)
    if os.path.exists(jp):
        cfg.update(json.load(open(jp, encoding='utf-8')))
    pp = os.path.join(job, 'picks.json')
    picks = json.load(open(pp, encoding='utf-8')) if os.path.exists(pp) else {}
    keys = list(cfg.get('targets') or picks)
    bar, maxr = cfg['bar'], cfg['max_rounds']
    good = [k for k in keys if picks.get(k, {}).get('score', 0) >= bar]
    capped = [k for k in keys if k not in good and picks.get(k, {}).get('final')]
    left = [k for k in keys if k not in good and k not in capped]
    unscored = [k for k in left if k not in picks]
    print(f'{len(good)} of {len(keys)} are good (>= {bar})  |  {len(left)} still working  |  {len(capped)} out of rounds below the bar')
    sc = [picks[k]['score'] for k in keys if k in picks]
    if sc:
        sc.sort()
        print(f'scores: lowest {sc[0]}, median {sc[len(sc) // 2]}, highest {sc[-1]}')
        a, b = round(bar - 0.5, 1), round(bar - 1.0, 1)
        bands = [(bar, 99, 'at bar'), (a, bar, f'{a}-{bar}'), (b, a, f'{b}-{a}'), (0, b, f'below {b}')]
        print('  ' + '  |  '.join(f'{lab}: {sum(lo <= v < hi for v in sc)}' for lo, hi, lab in bands))
    ranked = sorted((k for k in left if k in picks), key=lambda k: picks[k]['score'])
    if ranked:
        print(f'lowest {min(lowest, len(ranked))} still working:')
        for k in ranked[:lowest]:
            pk = picks[k]
            first = 11 if pk.get('round', 1) > maxr else 1  # tolerate runs that started numbering at 11
            print(f"  {pk['score']:.1f}  {k}  (round {pk.get('round', '?')}, {maxr - (pk.get('round', 1) - first + 1)} left)"
                  + (f"  -> {pk['note'][:70]}" if pk.get('note') else ''))
    if unscored:
        print(f'{len(unscored)} not scored yet')
    for k in capped:
        print(f"  capped at {picks[k]['score']:.1f}: {k}")


def pixel_svg(src, dst):
    """Exact vector copy of pixel art: one rect per horizontal run of a colour, crisp at any size."""
    im = Image.open(src).convert('RGBA')
    w, h = im.size
    px = im.load()
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w * 8}" height="{h * 8}" shape-rendering="crispEdges">']
    for y in range(h):
        x = 0
        while x < w:
            c = px[x, y]
            x1 = x + 1
            while x1 < w and px[x1, y] == c:
                x1 += 1
            if c[3] > 0:
                op = '' if c[3] == 255 else f' fill-opacity="{c[3] / 255:.3f}"'
                out.append(f'<rect x="{x}" y="{y}" width="{x1 - x}" height="1" fill="#{c[0]:02x}{c[1]:02x}{c[2]:02x}"{op}/>')
            x = x1
    out.append('</svg>')
    open(dst, 'w', encoding='utf-8').write(chr(10).join(out))


def traced_svg(src, dst, colors=24):
    """Vector trace of painted art (needs `pip install vtracer`). Cel-shaded art traces well; soft gradients become bands."""
    try:
        import vtracer
    except ImportError:
        raise SystemExit('illustration SVG needs the vtracer package: pip install vtracer')
    vtracer.convert_image_to_svg_py(src, dst, colormode='color', hierarchical='stacked', mode='spline',
                                    filter_speckle=10, color_precision=6, layer_difference=20,
                                    corner_threshold=60, length_threshold=4.0, splice_threshold=45, path_precision=3)


def cmd_svg(job):
    """Export every pick (best version) to JOB/svg/<target>.svg."""
    cfg, picks = load(job)
    d = os.path.join(job, 'svg')
    os.makedirs(d, exist_ok=True)
    for key, pk in picks.items():
        src = pk.get('best', pk['path'])
        if cfg['mode'] != 'pixel' and os.path.exists(src[:-4] + '-hi.png'):
            src = src[:-4] + '-hi.png'
        dst = os.path.join(d, slug(key) + '.svg')
        (pixel_svg if cfg['mode'] == 'pixel' else traced_svg)(src, dst)
        print(dst, f'{os.path.getsize(dst) // 1024} KB')


def cmd_wait(limit=540):
    me = os.getpid()
    def busy():
        out = subprocess.run(['powershell', '-NoProfile', '-Command',
                              "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
                             capture_output=True, text=True).stdout if os.name == 'nt' else subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True).stdout
        return [l for l in out.splitlines() if ('forge_loop.py' in l and ' gen' in l) or 'moss_generate.py' in l if not l.strip().startswith(str(me))]
    t0 = time.time()
    while busy() and time.time() - t0 < limit:
        time.sleep(20)
    print('BUSY' if busy() else 'IDLE')


if __name__ == '__main__':
    job, cmd = sys.argv[1], sys.argv[2]
    if cmd == 'gen':
        cmd_gen(job)
    elif cmd == 'sheets':
        cmd_sheets(job)
    elif cmd == 'svg':
        cmd_svg(job)
    elif cmd == 'report':
        cmd_report(job)
    elif cmd == 'status':
        cmd_status(job)
    elif cmd == 'wait':
        cmd_wait(int(sys.argv[3]) if len(sys.argv) > 3 else 540)
