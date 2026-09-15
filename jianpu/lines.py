#!/usr/bin/env python3
"""
Split a handwritten-jianpu photo into one strip per music line.

Ink is dark blue; the notebook's ruled lines are light blue and span the page.
Thresholding at T keeps the ink and drops most rules; the remaining long
horizontal runs are erased explicitly. The resulting row-ink profile has sharp
system peaks, and systems are cut at the valleys between them.
"""
import os, json, argparse
import numpy as np
from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = None
BASE = os.path.dirname(os.path.abspath(__file__))


def long_runs(row, minlen):
    x = np.concatenate(([0], row.astype(np.int32), [0]))
    d = np.diff(x)
    st = np.where(d == 1)[0]
    en = np.where(d == -1)[0]
    out = np.zeros_like(row)
    for s, e in zip(st, en):
        if e - s >= minlen:
            out[s:e] = True
    return out


def ink_mask(path, T=138, run_frac=0.25):
    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    a = np.asarray(im, np.float32)
    H, W = a.shape
    dark = a < T
    m = dark.copy()
    minlen = int(run_frac * W)
    for y in range(H):
        r = long_runs(dark[y], minlen)
        if r.any():
            m[y] = dark[y] & ~r
    return m, im


def smooth(v, k):
    k = max(3, int(k) | 1)
    ker = np.hanning(k)
    ker /= ker.sum()
    return np.convolve(v, ker, mode="same")


def find_systems(mask, H):
    rows = mask.sum(axis=1).astype(float)
    sm = smooth(rows, 15)
    adj = sm - smooth(sm, int(H * 0.20))

    thr = 0.16 * adj.max()
    raw = [i for i in range(1, H - 1)
           if adj[i] >= adj[i - 1] and adj[i] > adj[i + 1] and adj[i] > thr]

    kept = []
    for i in sorted(raw, key=lambda i: -adj[i]):
        if all(abs(i - j) > H * 0.045 for j in kept):
            kept.append(i)
    kept.sort()
    # drop photo-edge artefacts (top/bottom 3%)
    kept = [p for p in kept if H * 0.03 < p < H * 0.97]

    if not kept:
        return [], adj, rows

    cuts = []
    for i in range(len(kept) - 1):
        a, b = kept[i], kept[i + 1]
        cuts.append(a + int(np.argmin(adj[a:b + 1])))

    base = np.percentile(rows, 20)
    top = kept[0]
    while top > 0 and rows[max(0, top - 1)] > base * 1.5:
        top -= 1
    bot = kept[-1]
    while bot < H - 1 and rows[min(H - 1, bot + 1)] > base * 1.5:
        bot += 1

    edges = [top] + cuts + [bot]
    bands = [(int(edges[i]), int(edges[i + 1])) for i in range(len(edges) - 1)]
    return bands, adj, rows


def export(im, bands, outdir, tag, target_w=2600, pad_frac=0.10):
    os.makedirs(outdir, exist_ok=True)
    meta = {"tag": tag, "page": [im.width, im.height], "strips": []}
    for i, (y0, y1) in enumerate(bands):
        pad = int((y1 - y0) * pad_frac) + 8
        box = (0, max(0, y0 - pad), im.width, min(im.height, y1 + pad))
        s = im.crop(box).convert("L")
        a = np.asarray(s, np.float32)
        lo, hi = np.percentile(a, 1), np.percentile(a, 98)
        if hi - lo > 8:
            a = (a - lo) / (hi - lo) * 255.0
        s = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
        s = s.filter(ImageFilter.UnsharpMask(radius=4, percent=170, threshold=3))
        s = s.convert("RGB")
        if s.width < target_w:
            r = target_w / s.width
            s = s.resize((int(s.width * r), int(s.height * r)), Image.LANCZOS)
        p = os.path.join(outdir, f"{tag}_L{i+1:02d}.png")
        s.save(p, optimize=True)
        meta["strips"].append({"idx": i + 1, "band": [y0, y1],
                               "size": [s.width, s.height], "file": p})
    with open(os.path.join(outdir, f"{tag}_lines.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta


def run(name, tag, T=138, outdir=None):
    src = os.path.join(BASE, "src", name)
    mask, im = ink_mask(src, T=T)
    H = im.height
    bands, adj, rows = find_systems(mask, H)
    print(f"[{tag}] {name}: {len(bands)} lines")
    for i, (a, b) in enumerate(bands):
        print(f"   L{i+1:02d}: y {a:5d}..{b:5d}  h={b-a:4d}")
    outdir = outdir or os.path.join(BASE, "work", tag)
    return export(im, bands, outdir, tag)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=int, default=138)
    a = ap.parse_args()
    run("sbd1.jpg", "p1", T=a.t)
    run("sbd2.jpg", "p2", T=a.t)
