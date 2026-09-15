#!/usr/bin/env python3
"""
Decide whether the small marks under the melody digits are hand-drawn octave
dots or the paper's printed ruling dots.

The printed ruling is a row of dots at a fixed vertical spacing and a fixed
horizontal pitch that ignores where the digits are. A hand-drawn octave dot sits
directly under the digit it belongs to, so its x follows the digit centres and
its horizontal spacing is irregular - it tracks the handwriting, not the paper.
"""
import os, sys
import numpy as np
from PIL import Image, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))


def components(mask):
    """Very small connected-component labeller (4-neighbour, iterative)."""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    cur = 0
    out = []
    stack = []
    for y0 in range(H):
        for x0 in range(W):
            if not mask[y0, x0] or lab[y0, x0]:
                continue
            cur += 1
            stack.append((y0, x0))
            lab[y0, x0] = cur
            ys, xs = [], []
            while stack:
                y, x = stack.pop()
                ys.append(y)
                xs.append(x)
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = cur
                        stack.append((ny, nx))
            out.append({"y0": min(ys), "y1": max(ys), "x0": min(xs), "x1": max(xs),
                        "n": len(ys), "cx": (min(xs) + max(xs)) / 2,
                        "cy": (min(ys) + max(ys)) / 2})
    return out


def analyse(src, box, label):
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    g = im.crop(box)
    a = np.asarray(g, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1e-6) * 255, 0, 255)

    # ink well below the paper level around it
    from PIL import ImageFilter
    bg = np.asarray(Image.fromarray(np.uint8(a)).filter(
        ImageFilter.GaussianBlur(9)), np.float32)
    ink = a < (bg - 26)

    comps = components(ink)
    comps = [c for c in comps if c["n"] >= 4]
    if not comps:
        print(f"{label}: no components")
        return
    hs = [c["y1"] - c["y0"] + 1 for c in comps]
    ws = [c["x1"] - c["x0"] + 1 for c in comps]
    med_h = float(np.median(hs))
    med_w = float(np.median(ws))

    big = [c for c in comps if (c["y1"] - c["y0"] + 1) > 0.6 * med_h
           and c["n"] > 25]
    small = [c for c in comps if c not in big and c["n"] <= 25]

    print(f"--- {label} ---")
    print(f"  {len(comps)} components: {len(big)} large, {len(small)} tiny")
    if not big or not small:
        print("  cannot separate")
        return

    big.sort(key=lambda c: c["cx"])
    small.sort(key=lambda c: c["cx"])
    bxs = [c["cx"] for c in big]
    sxs = [c["cx"] for c in small]
    gaps_big = np.diff(bxs)
    gaps_small = np.diff(sxs)
    print(f"  digit centres x: {[int(v) for v in bxs]}")
    print(f"  digits spacing : {[int(v) for v in gaps_big]}  "
          f"(sd {np.std(gaps_big):.1f})")
    print(f"  tiny marks x   : {[int(v) for v in sxs]}")
    if len(gaps_small):
        print(f"  tiny spacing   : {[int(v) for v in gaps_small]}  "
              f"(sd {np.std(gaps_small):.1f})")

    # how far is each tiny mark below the nearest digit's bottom?
    below = []
    for s in small:
        near = min(big, key=lambda b: abs(b["cx"] - s["cx"]))
        dy = s["cy"] - near["y1"]
        dx = abs(s["cx"] - near["cx"])
        below.append((dx, dy))
    print(f"  tiny marks: dx to nearest digit "
          f"{[int(d[0]) for d in below]}, dy below its bottom "
          f"{[int(d[1]) for d in below]}")


if __name__ == "__main__":
    src = os.path.join(BASE, "src", "sbd1.jpg")
    analyse(src, (60, 200, 1000, 300), "melody row, measure 1-2")
    analyse(src, (60, 195, 1520, 420), "whole system 1")
