#!/usr/bin/env python3
"""Locate bar lines inside each music line and export one crop per measure."""
import os, json
import numpy as np
from PIL import Image, ImageFilter

BASE = os.path.dirname(os.path.abspath(__file__))


def vertical_strokes(gray, min_frac=0.45):
    """Columns containing a tall vertical ink run -> candidate bar lines."""
    a = np.asarray(gray, np.float32)
    H, W = a.shape
    ink = a < 150
    runs = np.zeros(W)
    for x in range(W):
        col = ink[:, x]
        if not col.any():
            continue
        d = np.diff(np.concatenate(([0], col.astype(np.int32), [0])))
        st = np.where(d == 1)[0]
        en = np.where(d == -1)[0]
        runs[x] = (en - st).max() if len(st) else 0
    return runs / max(H, 1)


def find_barlines(gray, min_frac=0.45, min_gap_frac=0.04):
    W = gray.width
    r = vertical_strokes(gray, min_frac)
    thresh = max(min_frac, 0.55 * r.max()) if r.max() > 0 else 1.0
    cand = np.where(r >= max(min_frac, 0.5 * r.max()))[0]
    groups = []
    for x in cand:
        if groups and x - groups[-1][-1] <= 3:
            groups[-1].append(x)
        else:
            groups.append([x])
    centres = [int(np.mean(g)) for g in groups]
    # drop centre duplicates closer than min_gap
    min_gap = max(6, int(W * min_gap_frac))
    kept = []
    for c in centres:
        if not kept or c - kept[-1] >= min_gap:
            kept.append(c)
    return kept, r


def export_measures(tag, line_idx, png, outdir, pad_frac=0.06):
    im = Image.open(png).convert("L")
    W, H = im.size
    bl, r = find_barlines(im)
    # a measure needs a left and right boundary
    edges = [0] + [b for b in bl if 0.02 * W < b < 0.98 * W] + [W]
    edges = sorted(set(edges))
    out = []
    for i in range(len(edges) - 1):
        x0, x1 = edges[i], edges[i + 1]
        if x1 - x0 < 0.04 * W:
            continue
        pad = int((x1 - x0) * pad_frac) + 6
        box = (max(0, x0 - pad), 0, min(W, x1 + pad), H)
        c = im.crop(box)
        # 3x upscale with contrast boost
        a = np.asarray(c, np.float32)
        lo, hi = np.percentile(a, 1), np.percentile(a, 99)
        if hi - lo > 8:
            a = (a - lo) / (hi - lo) * 255.0
        c = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
        sc = max(1.0, 1200.0 / c.width)
        if sc > 1.2:
            c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS)
        c = c.filter(ImageFilter.UnsharpMask(radius=3, percent=150, threshold=3))
        p = os.path.join(outdir, f"{tag}_L{line_idx:02d}_m{i+1:02d}.png")
        c.save(p, optimize=True)
        out.append({"m": i + 1, "x": [x0, x1], "file": p, "size": list(c.size)})
    return bl, out


if __name__ == "__main__":
    for tag in ("p1", "p2"):
        d = os.path.join(BASE, "work", tag)
        meta = json.load(open(os.path.join(d, f"{tag}_lines.json")))
        allm = {}
        for s in meta["strips"]:
            bl, ms = export_measures(tag, s["idx"], s["file"], d)
            allm[s["idx"]] = {"barlines": bl, "measures": ms}
            print(f"{tag} L{s['idx']:02d}: {len(bl)} barlines at {bl} "
                  f"-> {len(ms)} measures")
        json.dump(allm, open(os.path.join(d, f"{tag}_measures.json"), "w"),
                  indent=2, ensure_ascii=False)
