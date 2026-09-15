#!/usr/bin/env python3
"""
Produce the cleaned page images.

The photographs are of ruled notebook paper under uneven light. Cleaning them
means: flatten the lighting so the paper is uniformly white, drop the printed
rules (they are lighter than the pen ink and run the full page width), suppress
sensor noise, and straighten the small camera tilt.
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lines import long_runs

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "out", "preprocessed")
Image.MAX_IMAGE_PIXELS = None


def flatten(g, frac=0.20):
    r = max(12, int(min(g.size) * frac))
    bg = g.filter(ImageFilter.GaussianBlur(r))
    a = np.asarray(g, np.float32)
    b = np.asarray(bg, np.float32) + 1.0
    out = a / b
    out = out / np.percentile(out, 99.5) * 255.0
    return Image.fromarray(np.uint8(np.clip(out, 0, 255)))


def est_skew(g, lo=-4.0, hi=4.0, step=0.25):
    a = 255.0 - np.asarray(g.resize((600, int(600 * g.height / g.width))),
                           np.float32)
    best, bd = -1, 0.0
    d = lo
    while d <= hi + 1e-9:
        im = Image.fromarray(np.uint8(np.clip(255 - a, 0, 255))).rotate(
            d, resample=Image.BILINEAR, fillcolor=255)
        p = 255.0 - np.asarray(im, np.float32)
        v = float(np.var(p.sum(axis=1)))
        if v > best:
            best, bd = v, d
        d += step
    return bd


def remove_rules(dark, width_frac=0.12, density=0.80):
    """
    Drop the notebook's printed rules and keep the pen strokes.

    A rule pixel sits inside a very long unbroken horizontal dark run - roughly
    the whole page width - while a note stroke or a jianpu beam underline is
    short. Noise breaks the rules into fragments, so instead of measuring a run
    length the horizontal dark density is measured in a wide window: a rule
    pixel is dark and almost everything beside it along the row is dark too.
    """
    H, W = dark.shape
    K = max(8, int(width_frac * W))
    ii = np.zeros((H + 1, W + 1), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(dark.astype(np.float64), axis=0), axis=1)
    xs = np.arange(W)
    x0 = np.clip(xs - K, 0, W)
    x1 = np.clip(xs + K + 1, 0, W)
    cols = (ii[1:H + 1, x1] - ii[0:H, x1]
            - ii[1:H + 1, x0] + ii[0:H, x0])
    widths = (x1 - x0)[None, :]
    dens = cols / np.maximum(widths, 1)
    rule = dark & (dens >= density)
    return dark & ~rule


def ink_mask(g0, delta=26, radius_frac=0.05):
    """
    Locally adaptive ink mask.

    A global threshold cannot work here: the page carries a shadow, so paper
    that reads 196 in the middle reads 150 near the bottom edge, and any fixed
    cut-off either loses strokes in the light area or turns paper texture into
    ink in the dark one. Each pixel is therefore compared with the paper level
    around it. The printed rules are only faintly darker than the paper and fall
    below the margin; the pen strokes are far darker and survive.
    """
    a = np.asarray(g0, np.float32)
    r = max(10, int(radius_frac * min(g0.size)))
    bg = np.asarray(g0.filter(ImageFilter.GaussianBlur(r)), np.float32)
    return a < (bg - delta)


DELTA = 26


def clean(src, tag):
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    a = np.asarray(im, np.float32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    blueness = np.clip(b - (r + g) / 2.0, 0, 255)
    score = lum - 0.55 * blueness           # pen ink is dark blue
    g0 = Image.fromarray(np.uint8(np.clip(score, 0, 255)))

    g0 = flatten(g0, 0.20)
    g0 = g0.filter(ImageFilter.MedianFilter(3))

    sk = est_skew(g0)
    if abs(sk) > 0.1:
        g0 = g0.rotate(sk, resample=Image.BICUBIC, fillcolor=255, expand=False)

    a = np.asarray(g0, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255)
    g0 = Image.fromarray(np.uint8(a))
    g0 = g0.filter(ImageFilter.UnsharpMask(radius=3, percent=120, threshold=3))

    # ink-only mask: dark pixels minus the printed rules
    m = ink_mask(g0, delta=DELTA)
    binf = Image.fromarray(np.where(m, 0, 255).astype(np.uint8))

    os.makedirs(OUT, exist_ok=True)
    p1 = os.path.join(OUT, f"{tag}_clean.png")
    p2 = os.path.join(OUT, f"{tag}_ink-only.png")
    g0.save(p1)
    binf.save(p2)
    print(f"{tag}: skew={sk:+.2f}deg  {g0.width}x{g0.height}")
    print(f"   {p1}")
    print(f"   {p2}")


if __name__ == "__main__":
    clean(os.path.join(BASE, "src", "sbd1.jpg"), "sbd1")
    clean(os.path.join(BASE, "src", "sbd2.jpg"), "sbd2")
