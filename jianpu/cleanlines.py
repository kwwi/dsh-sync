#!/usr/bin/env python3
"""
Strip the paper's printed dotted ruling before reading a line.

The notebook is printed with a ruling made of small dots about 2x3 pixels,
spaced roughly 5 pixels apart. There are hundreds of them on every line and they
sit right among the handwriting, which is what made the vision model misread the
denser, later lines - it was reporting octave dots and even digits (8, 9) that do
not exist in jianpu. Removing every ink blob too small to be a pen stroke leaves
only the handwriting.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anchors import label_components, band_ink

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")


def clean_line(src, band, out_png, min_h=8, min_px=45, scale=3.0, pad=14):
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    y0, y1 = band
    g = im.crop((0, max(0, y0 - pad), im.width, min(im.height, y1 + pad)))
    a = np.asarray(g, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1e-6) * 255, 0, 255)
    g = Image.fromarray(np.uint8(a))

    ink = band_ink(g, 28, 7)
    comps = label_components(ink, min_px=1, max_px=200000)
    keep = np.zeros_like(ink, dtype=bool)
    H, W = ink.shape
    # rebuild the mask from components large enough to be pen strokes
    lab = np.zeros((H, W), np.int32)
    cur = 0
    kept = 0
    for c in comps:
        if c["h"] >= min_h and c["n"] >= min_px:
            kept += 1
            x0, x1 = max(0, c["x0"] - 1), min(W, c["x1"] + 2)
            y0c, y1c = max(0, c["y0"] - 1), min(H, c["y1"] + 2)
            sub = ink[y0c:y1c, x0:x1]
            keep[y0c:y1c, x0:x1] |= sub
    out = np.where(keep, 0, 255).astype(np.uint8)
    o = Image.fromarray(out)
    o = o.filter(ImageFilter.MedianFilter(3))
    if scale != 1.0:
        o = o.resize((int(o.width * scale), int(o.height * scale)),
                     Image.LANCZOS)
    o.save(out_png, optimize=True)
    return kept, len(comps), o.size


def main():
    outdir = os.path.join(WORK, "cleanlines")
    os.makedirs(outdir, exist_ok=True)
    meta_all = {}
    for tag, name in (("p1", "sbd1.jpg"), ("p2", "sbd2.jpg")):
        meta = json.load(open(os.path.join(WORK, tag, f"{tag}_lines.json")))
        meta_all[tag] = {}
        for s in meta["strips"]:
            ln = s["idx"]
            if tag == "p1" and ln == 1:
                continue
            png = os.path.join(outdir, f"{tag}_L{ln:02d}_clean.png")
            kept, tot, size = clean_line(os.path.join(BASE, "src", name),
                                         tuple(s["band"]), png)
            meta_all[tag][ln] = {"file": png, "band": s["band"]}
            print(f"{tag} L{ln:02d}: kept {kept}/{tot} components -> {size}")
    json.dump(meta_all, open(os.path.join(WORK, "clean_lines.json"), "w"),
              indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
