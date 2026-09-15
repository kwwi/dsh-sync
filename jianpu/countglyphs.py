#!/usr/bin/env python3
"""
Count the symbols in a music line without a vision model.

Digits are separated by gaps, so a vertical projection of the melody row shows
one run of ink per digit. Horizontal strokes (the notebook's ruled lines and any
jianpu beam underlines) would bridge the gaps, so they are removed first by
looking for ink that is locally part of a wide horizontal run.
"""
import os, sys, json
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")


def load(p):
    return Image.open(p).convert("L")


def horizontal_mask(a, T=150, width_frac=0.10, density=0.75):
    """Pixels belonging to a long horizontal stroke."""
    dark = a < T
    H, W = dark.shape
    K = max(6, int(width_frac * W))
    ii = np.zeros((H + 1, W + 1), np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(dark.astype(np.float64), 0), 1)
    xs = np.arange(W)
    x0 = np.clip(xs - K, 0, W)
    x1 = np.clip(xs + K + 1, 0, W)
    cnt = (ii[1:H + 1, x1] - ii[0:H, x1] - ii[1:H + 1, x0] + ii[0:H, x0])
    dens = cnt / np.maximum((x1 - x0)[None, :], 1)
    return dark & (dens >= density), dark


def runs(profile, thr):
    on = profile > thr
    out, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return out


def analyse(png, band=None, label=""):
    im = load(png)
    a = np.asarray(im, np.float32)
    H, W = a.shape
    if band:
        y0, y1 = int(H * band[0]), int(H * band[1])
        a = a[y0:y1]
    else:
        y0 = 0
    hmask, dark = horizontal_mask(a)
    nohoriz = dark & ~hmask

    col = nohoriz.sum(axis=0).astype(float)
    thr = max(1.0, 0.06 * col.max())
    rr = runs(col, thr)
    # merge runs separated by less than ~1% of the width (parts of one glyph)
    merged = []
    for s, e in rr:
        if merged and s - merged[-1][1] < 0.006 * W:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    widths = [e - s + 1 for s, e in merged]
    big = [w for w in widths if w > 0.004 * W]

    print(f"--- {label or os.path.basename(png)} ---")
    print(f"  image {W}x{H}, band y {y0}-{y0+a.shape[0]}")
    print(f"  ink {dark.mean():.4f}  of which horizontal {hmask.mean():.4f}")
    print(f"  {len(merged)} separated ink groups, "
          f"{len(big)} wider than {0.004*W:.0f}px")
    print(f"  group widths: {widths}")
    return merged, widths


if __name__ == "__main__":
    p = os.path.join(WORK, "p1", "p1_L02.png")
    # whole line, then just the upper (melody) row
    analyse(p, None, "p1 L02 full line")
    analyse(p, (0.05, 0.45), "p1 L02 upper row only")
