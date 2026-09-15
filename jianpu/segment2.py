#!/usr/bin/env python3
"""
Segment handwritten-jianpu photos into per-system strips.

The page is lined notebook paper under uneven light, so the raw row-ink profile
carries a slow shadow trend. Subtracting that trend leaves sharp system peaks;
systems are then cut at the valleys between peaks. Every strip is exported at
high resolution with local contrast normalisation.
"""
import os, json
import numpy as np
from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = None
BASE = os.path.dirname(os.path.abspath(__file__))


def load_ink(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    a = np.asarray(im, np.float32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    blueness = np.clip(b - (r + g) / 2.0, 0, 255)
    score = lum - 0.55 * blueness
    s = Image.fromarray(np.uint8(np.clip(score, 0, 255)))
    rad = max(12, int(min(s.size) * 0.22))
    bg = s.filter(ImageFilter.GaussianBlur(rad))
    fr = np.asarray(s, np.float32) / (np.asarray(bg, np.float32) + 1.0)
    fr = np.clip(fr / np.percentile(fr, 99.0), 0, 1.6)
    return fr, im


def smooth(v, k):
    k = max(3, int(k) | 1)
    ker = np.hanning(k)
    ker /= ker.sum()
    return np.convolve(v, ker, mode="same")


def find_peaks(x, min_dist, min_prom):
    cand = [i for i in range(1, len(x) - 1) if x[i] >= x[i - 1] and x[i] > x[i + 1]]
    cand.sort(key=lambda i: -x[i])
    kept = []
    for i in cand:
        if any(abs(i - j) < min_dist for j in kept):
            continue
        lo = x[max(0, i - min_dist):i + 1].min()
        hi = x[i:min(len(x), i + min_dist + 1)].min()
        if x[i] - max(lo, hi) >= min_prom:
            kept.append(i)
    return sorted(kept)


def segment(path, min_prom=0.30, min_dist_frac=0.055, verbose=True):
    f, im = load_ink(path)
    H, W = f.shape
    ink = (f < 0.72).astype(np.float32)
    rows = ink.sum(axis=1)

    sm = smooth(rows, H * 0.008)
    trend = smooth(sm, H * 0.20)
    adj = sm - trend

    span = adj.max() - adj.min()
    if span <= 0:
        return [], im
    norm = (adj - adj.min()) / span

    peaks = find_peaks(norm, min_dist=int(H * min_dist_frac), min_prom=min_prom)
    # drop peaks that sit on the extreme top/bottom border (photo edge artefacts)
    peaks = [p for p in peaks if H * 0.03 < p < H * 0.97]
    if verbose:
        print(f"  {len(peaks)} peaks at {peaks}")

    if not peaks:
        return [], im

    cuts = []
    for i in range(len(peaks) - 1):
        a, b = peaks[i], peaks[i + 1]
        cuts.append(a + int(np.argmin(norm[a:b + 1])))

    # outer edges: walk out from first/last peak to where ink falls to noise
    def edge(start, direction):
        base = np.percentile(rows, 12)
        i = start
        while 0 < i < H - 1:
            if rows[i] <= base * 1.15:
                return i
            i += direction
        return 0 if direction < 0 else H - 1

    top = edge(peaks[0], -1)
    bot = edge(peaks[-1], +1)
    edges = [top] + cuts + [bot]

    out = []
    for i in range(len(edges) - 1):
        y0, y1 = int(edges[i]), int(edges[i + 1])
        if y1 - y0 < H * 0.02:
            continue
        sub = ink[y0:y1 + 1]
        if sub.sum() < 0.002 * sub.size:
            continue
        out.append((y0, y1))
    if verbose:
        for i, (a, b) in enumerate(out):
            print(f"    sys{i+1:02d}: y {a:5d}..{b:5d} h={b-a:4d}")
    return out, im


def crop_strip(im, y0, y1, pad_frac=0.35, target_w=2400):
    H, W = im.height, im.width
    h = y1 - y0
    pad = int(h * pad_frac) + 10
    box = (0, max(0, y0 - pad), W, min(H, y1 + pad))
    s = im.crop(box)
    g = s.convert("L")
    a = np.asarray(g, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    if hi - lo > 8:
        a = (a - lo) / (hi - lo) * 255.0
    g = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
    g = g.filter(ImageFilter.UnsharpMask(radius=4, percent=160, threshold=3))
    s = g.convert("RGB")
    if s.width < target_w:
        r = target_w / s.width
        s = s.resize((int(s.width * r), int(s.height * r)), Image.LANCZOS)
    return s, box


def run(name, tag, min_prom=0.30):
    outdir = os.path.join(BASE, "work", tag)
    os.makedirs(outdir, exist_ok=True)
    bands, im = segment(os.path.join(BASE, "src", name), min_prom=min_prom)
    meta = {"tag": tag, "src": name, "page": [im.width, im.height], "strips": []}
    for i, (y0, y1) in enumerate(bands):
        s, box = crop_strip(im, y0, y1)
        p = os.path.join(outdir, f"{tag}_s{i+1:02d}.png")
        s.save(p, optimize=True)
        meta["strips"].append({"idx": i + 1, "band": [y0, y1],
                               "box": list(box), "size": [s.width, s.height],
                               "file": p})
        print(f"    -> {os.path.basename(p)} {s.width}x{s.height}")
    with open(os.path.join(outdir, f"{tag}_strips.json"), "w") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return meta


if __name__ == "__main__":
    for name, tag, mp in (("sbd1.jpg", "p1", 0.30), ("sbd2.jpg", "p2", 0.22)):
        print(f"=== {tag} ({name}) ===")
        run(name, tag, min_prom=mp)
