#!/usr/bin/env python3
"""
Locate measure boundaries from the bass row.

Every measure of this manuscript carries exactly one bass note, and that note is
written directly under its own measure. The bass digits are large and widely
spaced, so they can be found as connected components, and the midpoint between
two neighbouring bass notes is a far better measure boundary than an equal
division of the line - the handwriting is not evenly spaced, and an even split
silently cuts measures in half.
"""
import json, os, sys
import numpy as np
from PIL import Image, ImageFilter, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")


def label_components(mask, min_px=12, max_px=4000):
    """Iterative 4-neighbour connected components, filtered by pixel count."""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    out = []
    cur = 0
    for y0 in range(H):
        row = mask[y0]
        for x0 in range(W):
            if not row[x0] or lab[y0, x0]:
                continue
            cur += 1
            stack = [(y0, x0)]
            lab[y0, x0] = cur
            ys, xs = [], []
            while stack:
                y, x = stack.pop()
                ys.append(y)
                xs.append(x)
                if y + 1 < H and mask[y + 1, x] and not lab[y + 1, x]:
                    lab[y + 1, x] = cur
                    stack.append((y + 1, x))
                if y and mask[y - 1, x] and not lab[y - 1, x]:
                    lab[y - 1, x] = cur
                    stack.append((y - 1, x))
                if x + 1 < W and mask[y, x + 1] and not lab[y, x + 1]:
                    lab[y, x + 1] = cur
                    stack.append((y, x + 1))
                if x and mask[y, x - 1] and not lab[y, x - 1]:
                    lab[y, x - 1] = cur
                    stack.append((y, x - 1))
            n = len(ys)
            if min_px <= n <= max_px:
                out.append({"x0": min(xs), "x1": max(xs), "y0": min(ys),
                            "y1": max(ys), "n": n,
                            "cx": (min(xs) + max(xs)) / 2.0,
                            "cy": (min(ys) + max(ys)) / 2.0,
                            "h": max(ys) - min(ys) + 1,
                            "w": max(xs) - min(xs) + 1})
    return out


def band_ink(g, delta=30, r=7):
    a = np.asarray(g, np.float32)
    bg = np.asarray(g.filter(ImageFilter.GaussianBlur(r)), np.float32)
    return a < (bg - delta)


def bass_anchors(src, band, verbose=True):
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    y0, y1 = band
    h = y1 - y0
    # keep the lower two thirds: the bass row lives under the melody row
    top = int(y0 + h * 0.30)
    g = im.crop((0, top, im.width, y1))
    a = np.asarray(g, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1e-6) * 255, 0, 255)
    g = Image.fromarray(np.uint8(a))
    ink = band_ink(g, 30, 7)

    comps = label_components(ink, min_px=25, max_px=8000)
    if not comps:
        return [], g
    hs = np.array([c["h"] for c in comps])
    ws = np.array([c["w"] for c in comps])
    areas = np.array([c["n"] for c in comps])
    # bass digits are the tallest, chunkiest components
    hthr = max(10, 0.55 * np.percentile(hs, 90))
    big = [c for c in comps if c["h"] >= hthr and c["n"] >= 60]
    # drop specks and the dotted ruling (tiny, wide, thin)
    big = [c for c in big if c["w"] >= 6 and c["h"] >= 10]
    big.sort(key=lambda c: c["cx"])

    # merge components that overlap horizontally (a digit broken into pieces)
    merged = []
    for c in big:
        if merged and c["x0"] - merged[-1]["x1"] < 0.02 * im.width:
            m = merged[-1]
            m["x1"] = max(m["x1"], c["x1"])
            m["y1"] = max(m["y1"], c["y1"])
            m["y0"] = min(m["y0"], c["y0"])
            m["n"] += c["n"]
            m["cx"] = (m["x0"] + m["x1"]) / 2.0
        else:
            merged.append(dict(c))

    if verbose:
        print(f"  {len(comps)} components -> {len(big)} large -> {len(merged)} merged")
        print(f"  bass x centres: {[int(c['cx']) for c in merged]}")
        print(f"  bass heights  : {[c['h'] for c in merged]}")
    return merged, g


def anchors_for_all():
    out = {}
    for tag, name in (("p1", "sbd1.jpg"), ("p2", "sbd2.jpg")):
        meta = json.load(open(os.path.join(WORK, tag, f"{tag}_lines.json")))
        out[tag] = {}
        for s in meta["strips"]:
            ln = s["idx"]
            if tag == "p1" and ln == 1:
                continue
            print(f"=== {tag} L{ln:02d} band={s['band']} ===")
            bass, g = bass_anchors(os.path.join(BASE, "src", name),
                                   tuple(s["band"]))
            out[tag][ln] = {
                "band": list(s["band"]),
                "anchors": [int(c["cx"]) for c in bass],
                "count": len(bass),
            }
    json.dump(out, open(os.path.join(WORK, "bass_anchors.json"), "w"),
              indent=2, ensure_ascii=False)
    print()
    for tag in ("p1", "p2"):
        print(tag, {ln: v["count"] for ln, v in sorted(out[tag].items())})
    return out


if __name__ == "__main__":
    anchors_for_all()
