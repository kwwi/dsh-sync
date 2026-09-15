#!/usr/bin/env python3
"""Find music-system bands from a page's row-ink profile, robust to shadows."""
import numpy as np
from PIL import Image, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = None


def load_ink(path):
    """Return (ink_mask, page_w, page_h) with ink isolated from paper and rules."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    a = np.asarray(im, np.float32)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    blueness = np.clip(b - (r + g) / 2.0, 0, 255)
    score = lum - 0.55 * blueness
    s = Image.fromarray(np.uint8(np.clip(score, 0, 255)))

    rad = max(12, int(min(s.size) * 0.22))
    bg = s.filter(ImageFilter.GaussianBlur(rad))
    f = np.asarray(s, np.float32) / (np.asarray(bg, np.float32) + 1.0)
    f = f / np.percentile(f, 99.0)
    f = np.clip(f, 0, 1.6)
    return f, im


def smooth(v, k):
    if k < 3:
        return v
    ker = np.hanning(k)
    ker /= ker.sum()
    return np.convolve(v, ker, mode="same")


def find_peaks(v, min_dist, min_prom):
    """Plain local-maximum peak finder with a prominence floor."""
    cand = []
    n = len(v)
    for i in range(1, n - 1):
        if v[i] >= v[i - 1] and v[i] > v[i + 1]:
            cand.append(i)
    cand.sort(key=lambda i: -v[i])
    kept = []
    for i in cand:
        if all(abs(i - j) >= min_dist for j in kept):
            lo = v[max(0, i - min_dist):i + 1].min()
            hi = v[i:min(n, i + min_dist + 1)].min()
            prom = v[i] - max(lo, hi)
            if prom >= min_prom:
                kept.append(i)
    kept.sort()
    return kept


def systems(path, verbose=True):
    f, im = load_ink(path)
    H, W = f.shape
    ink = (f < 0.72).astype(np.float32)          # darkness relative to local paper
    rows = ink.sum(axis=1)

    k = max(5, int(H * 0.010)) | 1
    sm = smooth(rows, k)

    # noise floor from the quietest 10% of the page
    floor = np.percentile(sm, 10)
    top = np.percentile(sm, 99)
    if top - floor < 1:
        return [], im, sm
    norm = (sm - floor) / (top - floor)

    mind = int(H * 0.035)
    peaks = find_peaks(norm, min_dist=mind, min_prom=0.22)
    if verbose:
        print(f"  profile: floor={floor:.0f} top={top:.0f} peaks={len(peaks)} "
              f"at {peaks}")

    if not peaks:
        return [], im, sm

    # cut between consecutive peaks at the profile minimum
    bounds = []
    for i in range(len(peaks) - 1):
        a, b = peaks[i], peaks[i + 1]
        seg = norm[a:b + 1]
        cut = a + int(np.argmin(seg))
        bounds.append(cut)

    edges = [0] + bounds + [H - 1]
    out = []
    for i in range(len(edges) - 1):
        y0, y1 = edges[i], edges[i + 1]
        # tighten to actual ink extent inside the band
        sub = ink[y0:y1 + 1]
        rr = sub.sum(axis=1)
        nz = np.where(rr > max(1.0, 0.02 * rr.max()))[0]
        if len(nz) == 0:
            continue
        yy0, yy1 = y0 + int(nz[0]), y0 + int(nz[-1])
        if (yy1 - yy0) < H * 0.012:
            continue
        mass = sub.sum()
        if mass < 0.002 * sub.size:
            continue
        out.append((yy0, yy1, float(mass)))

    if verbose:
        for i, (a, b, m) in enumerate(out):
            print(f"    sys{i+1:02d}: y {a:5d}..{b:5d} h={b-a:4d} ink={m:9.0f}")
    return out, im, sm


if __name__ == "__main__":
    import sys, os
    base = os.path.dirname(os.path.abspath(__file__))
    for n in ("sbd1.jpg", "sbd2.jpg"):
        p = os.path.join(base, "src", n)
        print(f"=== {n} ===")
        systems(p)
