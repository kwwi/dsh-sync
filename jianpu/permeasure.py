#!/usr/bin/env python3
"""
Read one measure at a time.

Each line is split at the measure boundaries reported for it, every measure is
exported as its own magnified crop (with a little context on both sides), and
each crop is sampled several times. The majority reading wins, so isolated
misreads do not survive.
"""
import json, os, sys, re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask
from parse import extract, norm_oct

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

# measures per line and the notation's horizontal extent (fractions of width)
GEOM = {
    "p1": {2: (4, 0.05, 0.965), 3: (4, 0.05, 0.965), 4: (4, 0.06, 0.96),
           5: (4, 0.05, 0.96), 6: (4, 0.07, 0.97), 7: (3, 0.07, 0.93),
           8: (3, 0.08, 0.88), 9: (3, 0.05, 0.99)},
    "p2": {1: (3, 0.08, 0.98), 2: (2, 0.05, 0.95), 3: (2, 0.06, 0.94),
           4: (3, 0.09, 0.98), 5: (3, 0.08, 0.94), 6: (2, 0.09, 0.97),
           7: (4, 0.04, 0.96), 8: (4, 0.09, 0.96)},
}

PROMPT = """This is a heavily magnified crop from a handwritten jianpu (numbered musical notation) manuscript.

The CROP CONTAINS ONE COMPLETE MEASURE in its central area; you may also see a small sliver of the neighbouring measures at the far left or far right.

Transcribe ONLY that one central complete measure.

Answer in EXACTLY this form:

MELODY: [n|oct|beats] [n|oct|beats] ...
BASS: [n|oct|beats] ...
CHORD: <any chord letters written above this measure, or none>

Definitions:
- n is a single digit 0-7. A written run like "06" is TWO numbers: 0 then 6. Never merge digits.
- oct is one of: up2 (two dots above the number), up1 (one dot above), mid (no dot),
  dn1 (one dot below), dn2 (two dots below). Look at every number individually for its dot.
- beats is one of: 4 3 2 1.5 1 0.75 0.5 0.375 0.25 0.125, read from the underlines and dashes:
  one underline = 0.5, two = 0.25, three = 0.125, a dash after a number adds 1 beat,
  a dot after a number multiplies by 1.5.
- Write every note of the measure, in order, with no omissions.

If a symbol is genuinely unreadable write [7|mid|1] is NOT acceptable - instead add a final line:
UNCLEAR: <describe exactly what you cannot read>
"""


def measure_crops(tag, ln, line_png, outdir):
    M, xs, xe = GEOM[tag][ln]
    im = Image.open(line_png).convert("L")
    W, H = im.size
    out = []
    for i in range(M):
        x0 = xs + (xe - xs) * i / M
        x1 = xs + (xe - xs) * (i + 1) / M
        ctx = (x1 - x0) * 0.35
        a = max(0.0, x0 - ctx)
        b = min(1.0, x1 + ctx)
        c = im.crop((int(W * a), 0, int(W * b), H))
        arr = np.asarray(c, np.float32)
        lo, hi = np.percentile(arr, 1), np.percentile(arr, 99)
        if hi - lo > 8:
            arr = (arr - lo) / (hi - lo) * 255.0
        c = Image.fromarray(np.uint8(np.clip(arr, 0, 255)))
        sc = max(1.0, 1500.0 / c.width)
        if sc > 1.05:
            c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS)
        c = c.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))
        p = os.path.join(outdir, f"{tag}_L{ln:02d}_m{i+1}.png")
        c.save(p, optimize=True)
        out.append({"m": i + 1, "x": [a, b], "file": p})
    return out


def run(tag, samples=5, workers=8, only=None):
    lj = json.load(open(os.path.join(WORK, tag, f"{tag}_lines.json")))
    outdir = os.path.join(WORK, tag, "measures")
    os.makedirs(outdir, exist_ok=True)
    jobs = []
    for s in lj["strips"]:
        ln = s["idx"]
        if tag == "p1" and ln == 1:
            continue
        if only and ln not in only:
            continue
        for mc in measure_crops(tag, ln, s["file"], outdir):
            for k in range(samples):
                jobs.append((ln, mc["m"], mc["file"], k))

    def call(j):
        ln, m, f, k = j
        temp = 0.0 if k == 0 else 0.85
        try:
            t, fr, u, r = ask(f, PROMPT, thinking="disabled",
                              max_tokens=1200, temperature=temp)
        except SystemExit as e:
            t = f"ERROR {e}"
        return ln, m, k, t

    res = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ln, m, k, t in ex.map(call, jobs):
            res.setdefault(ln, {}).setdefault(m, {})[k] = t
            done += 1
            if done % 20 == 0:
                print(f"   {tag}: {done}/{len(jobs)}")
    p = os.path.join(WORK, tag, f"{tag}_measure_answers.json")
    json.dump(res, open(p, "w"), indent=2, ensure_ascii=False)
    print(f"{tag}: {done} calls -> {p}")
    return p


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", default="p1,p2")
    a = ap.parse_args()
    for tag in a.pages.split(","):
        print(f"=== {tag} ===")
        run(tag, samples=a.samples, workers=a.workers)
