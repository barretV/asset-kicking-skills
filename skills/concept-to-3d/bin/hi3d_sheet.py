"""
Compose a before / sculpt / after sheet next to the concept (Pillow only, no GPU).

    python bin/hi3d_sheet.py <out.webp> --title "My creature"
        --row "3/4" concept=<png> before=<jpg> sculpt=<png> after=<jpg>
        --row "side" concept=<png> before=<jpg> sculpt=<png> after=<jpg>

Any column may be left out of a row. Tiles are fitted into 420x330 cells; gold labels.
"""
import argparse

from PIL import Image, ImageDraw, ImageFont

COLS = ["concept", "before", "sculpt", "after"]
LABEL = {"concept": "MOSS concept", "before": "before (game shader)", "sculpt": "Hi3D sculpt (clay)",
         "after": "after (game shader)"}
CW, CH, PAD, HEAD = 420, 330, 8, 34


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((CW, CH))
    cell = Image.new("RGB", (CW, CH), (18, 12, 28))
    cell.paste(im, ((CW - im.width) // 2, (CH - im.height) // 2))
    return cell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--title", default="")
    ap.add_argument("--row", nargs="+", action="append", required=True)
    a = ap.parse_args()
    rows = []
    for r in a.row:
        name, cells = r[0], dict(kv.split("=", 1) for kv in r[1:])
        rows.append((name, cells))
    cols = [c for c in COLS if any(c in cells for _, cells in rows)]
    W = PAD + len(cols) * (CW + PAD)
    H = HEAD * 2 + PAD + len(rows) * (CH + PAD)
    sheet = Image.new("RGB", (W, H), (12, 8, 20))
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 6), a.title, fill=(255, 196, 76), font=font(20))
    for i, c in enumerate(cols):
        d.text((PAD + i * (CW + PAD), HEAD + 6), LABEL[c], fill=(230, 220, 240), font=font(16))
    for j, (name, cells) in enumerate(rows):
        y = HEAD * 2 + j * (CH + PAD)
        for i, c in enumerate(cols):
            x = PAD + i * (CW + PAD)
            if c in cells:
                sheet.paste(fit(cells[c]), (x, y))
            d.text((x + 6, y + 4), name, fill=(255, 196, 76), font=font(14))
    sheet.save(a.out, quality=88)
    print("wrote", a.out, sheet.size)


if __name__ == "__main__":
    main()
