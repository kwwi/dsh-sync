#!/usr/bin/env python3
"""
Segment a handwritten jianpu photo into clean per-system strips.

Strategy: the page is lined paper with light-blue rules and a shadow gradient.
Blue pen ink is much darker than the rules, so after illumination flattening an
Otsu threshold cleanly separates ink from rules and paper. Bands of ink are then
merged into systems, and each system is exported as an enhanced strip at high
resolution for transcription.
"""
import os, sys, json
import numpy as np
from PIL import Image, ImageOps, ImageFilter

Image.MAX_IMAGE_PIXELS = None
BASE = os.path.dirname(os.path.abspath(__file__))


def gray_of(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    a = np.asarray(im, dtype=np.float32)
    # ink is blue: emphasise blue-dark pixels, suppress warm paper/shadow
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    blueness = np.clip(b - (r + g) / 2.0, 0, 255)          # >0 where blue
    score = lum - 0.55 * blueness                            # ink -> low
    return Image.fromarray(np.uint8(np.clip(score, 0, 255)))


def flatten(g, radius_frac=0.10):
    r = max(10, int(min(g.size) * radius_frac))
    bg = g.filter(ImageFilter.GaussianBlur(r))
    a = np.asarray(g, np.float32)
    b = np.asarray(bg, np.float32) + 1.0
    out = a / b
    out = out / np.percentile(out, 99.5) * 255.0
    return Image.fromarray(np.uint8(np.clip(out, 0, 255)))


def otsu(vals):
    hist, _ = np.histogram(vals, bins=256, range=(0, 256))
    tot = hist.sum()
    if tot == 0:
        return 128
    p = hist / tot
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mu_t = mu[-1]
    denom = omega * (1 - omega)
    denom[denom == 0] = 1e-12
    sigma = (mu_t * omega - mu) ** 2 / denom
    return int(np.argmax(sigma))


def make_mask(g):
    a = np.asarray(g, np.float32)
    t = otsu(a.ravel())
    # bias slightly dark so faint strokes are kept but paper texture is not
    t = int(t * 0.92)
    return (a < t), t


def bands_from_mask(mask, page_h):
    ink = mask.sum(axis=1).astype(np.float32)
    # smooth to avoid splitting a system at a thin row
    k = max(3, int(page_h * 0.004))
    ker = np.ones(k) / k
    sm = np.convolve(ink, ker, mode="same")
    thr = max(2.0, 0.010 * sm.max())
    on = sm > thr
    bands, start, gap = [], None, 0
    min_gap = max(4, int(page_h * 0.008))
    for i, v in enumerate(on):
        if v:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                bands.append((start, i - gap))
                start = None
                gap = 0
    if start is not None:
        bands.append((start, len(on) - 1))
    min_h = max(8, int(page_h * 0.012))
    bands = [b for b in bands if b[1] - b[0] >= min_h]
    return bands, ink


def merge_into_systems(bands, page_h):
    """Merge band fragments that belong to the same music system."""
    if not bands:
        return []
    gaps = [bands[i + 1][0] - bands[i][1] for i in range(len(bands) - 1)]
    if not gaps:
        return bands
    g = np.array(gaps, dtype=float)
    # a new system starts where the gap is a clear outlier (much larger)
    med = np.median(g)
    thr = max(med * 2.2, page_h * 0.014)
    sysb, cur = [], list(bands[0])
    for i, gap in enumerate(gaps):
        if gap > thr:
            sysb.append(tuple(cur))
            cur = list(bands[i + 1])
        else:
            cur[1] = bands[i + 1][1]
    sysb.append(tuple(cur))
    return sysb


def enhance_strip(im, box, target_w=2200):
    s = im.crop(box)
    g = flatten(s.convert("L") if s.mode != "L" else s, 0.12)
    g = g.filter(ImageFilter.UnsharpMask(radius=3, percent=140, threshold=3))
    # contrast stretch on the ink range
    a = np.asarray(g, np.float32)
    lo, hi = np.percentile(a, 2), np.percentile(a, 97)
    if hi - lo > 10:
        a = (a - lo) / (hi - lo) * 255.0
    g = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
    if g.width < target_w:
        r = target_w / g.width
        g = g.resize((int(g.width * r), int(g.height * r)), Image.LANCZOS)
    return g


def run(name, tag, expect=None):
    src = os.path.join(BASE, "src", name)
    out = os.path.join(BASE, "work", tag)
    os.makedirs(out, exist_ok=True)

    g0 = gray_of(src)
    g0 = flatten(g0)
    mask, thr = make_mask(g0)

    rows = mask.sum(axis=1)
    cols = mask.sum(axis=0)
    ry = np.where(rows > max(1, rows.max() * 0.02))[0]
    rx = np.where(cols > max(1, cols.max() * 0.02))[0]
    y0, y1 = (int(ry[0]), int(ry[-1])) if len(ry) else (0, g0.height)
    x0, x1 = (int(rx[0]), int(rx[-1])) if len(rx) else (0, g0.width)

    bands, _ = bands_from_mask(mask, g0.height)
    systems = merge_into_systems(bands, g0.height)

    # keep only systems that look like real music lines (enough ink + width)
    real = []
    for (a, b) in systems:
        sub = mask[a:b + 1, x0:x1 + 1]
        if sub.sum() < 0.004 * sub.size:
            continue
        if (b - a) < 0.010 * g0.height:
            continue
        real.append((a, b))

    info = {"tag": tag, "src": name, "page": [g0.width, g0.height],
            "otsu_thr": thr, "content_box": [x0, y0, x1, y1],
            "n_raw_bands": len(bands), "n_systems": len(real),
            "expected": expect, "systems": []}

    for i, (a, b) in enumerate(real):
        pad = int((b - a) * 0.28) + 8
        box = (max(0, x0 - int(0.01 * g0.width)),
               max(0, a - pad),
               min(g0.width, x1 + int(0.01 * g0.width)),
               min(g0.height, b + pad))
        strip = enhance_strip(ImageOps.exif_transpose(Image.open(src)), box)
        p = os.path.join(out, f"{tag}_sys{i+1:02d}.png")
        strip.save(p)
        info["systems"].append({"idx": i + 1, "band": [a, b], "box": list(box),
                                "h": box[3] - box[1], "file": p})

    with open(os.path.join(out, f"{tag}_systems.json"), "w") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

    print(f"[{tag}] page={g0.width}x{g0.height} otsu={thr} "
          f"raw_bands={len(bands)} systems={len(real)} (expected {expect})")
    for s in info["systems"]:
        print(f"   sys{s['idx']:02d}: y{s['band'][0]:5d}..{s['band'][1]:5d} "
              f"h={s['band'][1]-s['band'][0]:4d} -> {os.path.basename(s['file'])}")
    return info


if __name__ == "__main__":
    run("sbd1.jpg", "p1", expect=8)
    run("sbd2.jpg", "p2", expect=None)
