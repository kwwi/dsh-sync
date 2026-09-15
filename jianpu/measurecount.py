#!/usr/bin/env python3
"""
Recover the true measure count of every line.

The lower row of a jianpu system carries exactly one note per measure, so the
number of digits in that row is the number of measures. Counting that row is far
more reliable than asking a vision model to count bar lines, and it is what
decides where the measure crops must fall - a wrong count misaligns every crop
on the line and corrupts the whole transcription.
"""
import json, os, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

PROMPT = """This strip is the LOWER row of one system of handwritten Chinese jianpu (numbered notation) - the row written underneath the main row of numbers.

In this lower row there is normally ONE large digit per measure.

Answer with ONLY these two lines:
COUNT: <how many separate large digits are in this row>
DIGITS: <the digits in order, separated by spaces>
"""


def lower_row(src, band, out_png, frac=(0.42, 1.0)):
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    y0, y1 = band
    h = y1 - y0
    box = (0, int(y0 + h * frac[0]), im.width, int(y0 + h * frac[1]))
    c = im.crop(box)
    a = np.asarray(c, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    a = np.clip((a - lo) / max(hi - lo, 1e-6) * 255, 0, 255)
    c = Image.fromarray(np.uint8(a))
    sc = max(1.0, 2400.0 / c.width)
    c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS)
    c = c.filter(ImageFilter.UnsharpMask(radius=3, percent=140, threshold=3))
    c.save(out_png, optimize=True)
    return out_png


def job(a):
    tag, ln, png = a
    c = Counter()
    for k in range(4):
        try:
            t, fr, u, r = ask(png, PROMPT, thinking="disabled", max_tokens=120,
                              temperature=0.0 if k == 0 else 0.85)
        except SystemExit:
            continue
        m = re.search(r"COUNT\s*:\s*(\d+)", t)
        d = re.search(r"DIGITS\s*:\s*([\d\s]+)", t)
        c[((m.group(1) if m else "?"), (d.group(1).strip() if d else "?"))] += 1
    return tag, ln, c.most_common(3)


def main():
    outdir = os.path.join(WORK, "lowrow")
    os.makedirs(outdir, exist_ok=True)
    jobs, boxes = [], {}
    for tag, name in (("p1", "sbd1.jpg"), ("p2", "sbd2.jpg")):
        meta = json.load(open(os.path.join(WORK, tag, f"{tag}_lines.json")))
        for s in meta["strips"]:
            ln = s["idx"]
            if tag == "p1" and ln == 1:
                continue
            band = tuple(s["band"])
            png = os.path.join(outdir, f"{tag}_L{ln:02d}_low.png")
            lower_row(os.path.join(BASE, "src", name), band, png)
            jobs.append((tag, ln, png))
            boxes[(tag, ln)] = band
    res = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tag, ln, top in ex.map(job, jobs):
            best = top[0][0]
            res.setdefault(tag, {})[ln] = {"count": int(best[0]) if best[0].isdigit() else None,
                                           "digits": best[1],
                                           "votes": top}
            print(f'{tag} L{ln:02d}: measures={best[0]:>3}  bass=[{best[1]}]  '
                  + " | ".join(f'{a[0]}/{a[1]}x{b}' for a, b in top))
    json.dump(res, open(os.path.join(WORK, "measure_counts.json"), "w"),
              indent=2, ensure_ascii=False)
    print()
    for tag in ("p1", "p2"):
        print(tag, {ln: v["count"] for ln, v in sorted(res.get(tag, {}).items())})


if __name__ == "__main__":
    main()
