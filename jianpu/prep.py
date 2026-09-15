#!/usr/bin/env python3
"""
Preprocess photos of handwritten jianpu (numbered notation).

Cleans up camera artifacts so a vision model can read the score:
  1. grayscale + illumination flattening (removes shadows / uneven lighting)
  2. denoise + contrast enhancement
  3. ink binarization
  4. skew estimation and deskew
  5. content crop
  6. row-structure analysis -> line bands for strip-wise transcription
"""
import sys, os, json
import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageDraw

Image.MAX_IMAGE_PIXELS = None


def to_gray(im):
    return im.convert("L")


def flatten_illumination(g, radius_frac=0.06):
    """Divide by a heavily blurred copy to remove lighting gradients."""
    r = max(8, int(min(g.size) * radius_frac))
    bg = g.filter(ImageFilter.GaussianBlur(r))
    a = np.asarray(g, dtype=np.float32)
    b = np.asarray(bg, dtype=np.float32) + 1e-3
    # normalise so paper (~bright) maps to white
    out = a / b
    hi = np.percentile(out, 99.0)
    out = np.clip(out / max(hi, 1e-6), 0, 1.4)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def denoise_contrast(g):
    g = g.filter(ImageFilter.MedianFilter(3))
    g = ImageOps.autocontrast(g, cutoff=(1, 1))
    return g


def estimate_skew(gray, max_deg=6.0, step=0.25):
    """Estimate skew by maximising the variance of the horizontal ink profile."""
    a = 255.0 - np.asarray(gray, dtype=np.float32)  # ink = positive
    a = a - a.mean()
    h, w = a.shape
    # work on a downscaled copy for speed
    scale = 1.0
    if w > 1200:
        scale = 1200.0 / w
        im = Image.fromarray(np.uint8(np.clip(255 - a, 0, 255))).resize(
            (int(w * scale), int(h * scale)), Image.BILINEAR)
        a = 255.0 - np.asarray(im, dtype=np.float32)
        a = a - a.mean()
        h, w = a.shape

    best, best_deg = -1.0, 0.0
    deg = -max_deg
    while deg <= max_deg + 1e-9:
        im = Image.fromarray(np.uint8(np.clip(255 - a, 0, 255))).rotate(
            deg, resample=Image.BILINEAR, fillcolor=255, expand=False)
        p = 255.0 - np.asarray(im, dtype=np.float32)
        prof = p.sum(axis=1)
        v = float(np.var(prof))
        if v > best:
            best, best_deg = v, deg
        deg += step
    return best_deg


def binarize(gray, block=41, C=12):
    """Adaptive threshold (integral-image mean), returning 0=ink, 255=paper."""
    a = np.asarray(gray, dtype=np.float32)
    h, w = a.shape

    # integral image
    ii = np.zeros((h + 1, w + 1), dtype=np.float64)
    ii[1:, 1:] = np.cumsum(np.cumsum(a, axis=0), axis=1)

    r = block // 2
    ys = np.arange(h)
    xs = np.arange(w)
    y0 = np.clip(ys - r, 0, h)
    y1 = np.clip(ys + r + 1, 0, h)
    x0 = np.clip(xs - r, 0, w)
    x1 = np.clip(xs + r + 1, 0, w)

    S = (ii[np.ix_(y1, x1)] - ii[np.ix_(y0, x1)] -
         ii[np.ix_(y1, x0)] + ii[np.ix_(y0, x0)])
    n = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    mean = S / np.maximum(n, 1)

    out = np.where(a < mean - C, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


def content_bbox(binimg, pad=12):
    """Bounding box of the ink, ignoring tiny specks."""
    a = np.asarray(binimg)
    ink = a < 128
    rows = ink.sum(axis=1)
    cols = ink.sum(axis=0)
    thr_r = max(1, int(0.002 * a.shape[1]))
    thr_c = max(1, int(0.002 * a.shape[0]))
    ry = np.where(rows > thr_r)[0]
    rx = np.where(cols > thr_c)[0]
    if len(ry) == 0 or len(rx) == 0:
        return (0, 0, binimg.width, binimg.height)
    y0, y1 = int(ry[0]), int(ry[-1])
    x0, x1 = int(rx[0]), int(rx[-1])
    return (max(0, x0 - pad), max(0, y0 - pad),
            min(binimg.width, x1 + pad), min(binimg.height, y1 + pad))


def ink_rows(binimg):
    a = np.asarray(binimg)
    ink = (a < 128).sum(axis=1).astype(float)
    return ink


def find_bands(ink, min_gap, min_h):
    """Split a row-ink profile into contiguous text bands."""
    on = ink > max(1.0, 0.004 * ink.max() if ink.max() > 0 else 1.0)
    bands = []
    start = None
    gap = 0
    for i, v in enumerate(on):
        if v:
            if start is None:
                start = i
            gap = 0
        else:
            if start is not None:
                gap += 1
                if gap >= min_gap:
                    end = i - gap
                    if end - start >= min_h:
                        bands.append((start, end))
                    start = None
                    gap = 0
    if start is not None and (len(on) - start) >= min_h:
        bands.append((start, len(on) - 1))
    return bands


def process(src, outdir, tag):
    os.makedirs(outdir, exist_ok=True)
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)
    g = to_gray(im)

    g = flatten_illumination(g)
    g = denoise_contrast(g)

    skew = estimate_skew(g)
    if abs(skew) > 0.1:
        g = g.rotate(skew, resample=Image.BICUBIC, fillcolor=255, expand=False)

    b = binarize(g)
    box = content_bbox(b, pad=16)
    g = g.crop(box)
    b = b.crop(box)

    # upscale for legibility
    target_w = 1800
    if g.width < target_w:
        s = target_w / g.width
        g = g.resize((int(g.width * s), int(g.height * s)), Image.LANCZOS)
        b = b.resize((int(b.width * s), int(b.height * s)), Image.NEAREST)

    clean = os.path.join(outdir, f"{tag}_clean.png")
    binary = os.path.join(outdir, f"{tag}_bin.png")
    g.save(clean)
    b.save(binary)

    ink = ink_rows(b)
    # a "line" of jianpu is ~ a few % of page height; merge sub-bands
    h = b.height
    min_h = max(6, int(0.010 * h))
    min_gap = max(6, int(0.013 * h))
    bands = find_bands(ink, min_gap=min_gap, min_h=min_h)

    meta = {
        "src": src, "tag": tag, "size": [g.width, g.height],
        "crop_box": list(box), "skew_deg": round(float(skew), 3),
        "bands": [[int(a), int(bb)] for a, bb in bands],
        "clean": clean, "bin": binary,
    }
    with open(os.path.join(outdir, f"{tag}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[{tag}] size={g.width}x{g.height} skew={skew:+.2f}deg bands={len(bands)}")
    for i, (s, e) in enumerate(bands):
        print(f"   band {i:2d}: y {s:5d}..{e:5d}  h={e-s:4d}  ink={ink[s:e+1].sum():.0f}")
    return meta


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(base, "src")
    work = os.path.join(base, "work")
    for name, tag in (("sbd1.jpg", "p1"), ("sbd2.jpg", "p2")):
        p = os.path.join(src, name)
        if os.path.exists(p):
            process(p, work, tag)
