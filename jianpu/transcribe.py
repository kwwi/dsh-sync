#!/usr/bin/env python3
"""
Transcribe each music line of a handwritten jianpu score.

Method: every line is cut into overlapping horizontal windows so each measure
appears at least twice at high magnification. Each window is sampled several
times at non-zero temperature and the readings are later voted on, so a single
misread digit does not survive into the result.
"""
import os, json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

PROMPT = """This image is a horizontal WINDOW cut out of ONE line of handwritten jianpu (numbered musical notation) from a Chinese manuscript. It may begin and/or end in the middle of a measure.

The line can contain a MELODY row of numbers and, underneath it, a row of BASS notes. There may also be chord letters written above.

Transcribe it left to right. Output ONE token per note, formatted exactly as:

[number|octave|beats]

number : 0 1 2 3 4 5 6 7   (0 = rest)
octave : up2 (two dots above) | up1 (one dot above) | mid (no dot) | dn1 (one dot below) | dn2 (two dots below)
beats  : how long the note lasts, counted from the underlines and dashes, using only:
         4   (whole: number + 3 dashes)
         3   (number + 2 dashes)
         2   (number + 1 dash)
         1.5 (number with a dot after it)
         1   (plain number, no underline)
         0.75(number with a dot AND one underline)
         0.5 (ONE underline = eighth)
         0.25(TWO underlines = sixteenth)
         0.125 (THREE underlines = thirty-second)

Separate tokens with a single space. Separate measures with ' | '.

Rules:
1. Read EVERY number from left to right. Never skip, never summarise, never invent.
2. A run like "06 16" means FOUR separate numbers 0, 6, 1, 6 - never merge digits.
3. Look carefully at each number: does it have a dot above, a dot below, or no dot?
4. Count the underlines below each number exactly (0, 1, 2 or 3).
5. A dash '-' after a number adds one beat to that number.
6. A curved line over numbers is a slur: wrap those tokens as ( ... ) and keep their own beat values.

Answer in exactly this form and nothing else:

MELODY: [..] [..] | [..] [..]
BASS: [..] | [..]
CHORDS: <any chord letters/roman numerals written above, in order, or "none">
NOTES: <anything you genuinely cannot read, or "none">
"""


def window(img, x0f, x1f, scale=2.2, pad=0.04):
    W, H = img.size
    x0 = max(0, int(W * (x0f - pad)))
    x1 = min(W, int(W * (x1f + pad)))
    c = img.crop((x0, 0, x1, H))
    a = np.asarray(c, np.float32)
    lo, hi = np.percentile(a, 1), np.percentile(a, 99)
    if hi - lo > 8:
        a = (a - lo) / (hi - lo) * 255.0
    c = Image.fromarray(np.uint8(np.clip(a, 0, 255)))
    if scale != 1.0:
        c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    c = c.filter(ImageFilter.UnsharpMask(radius=2, percent=90, threshold=3))
    return c, (x0, x1)


def raw_window(img, x0f, x1f):
    """Untouched pixels from the original photo (no enhancement)."""
    W, H = img.size
    return img.crop((max(0, int(W * x0f)), 0, min(W, int(W * x1f)), H))


def transcribe_line(tag, idx, line_png, src_img, samples=3, outdir=None):
    enh = Image.open(line_png).convert("L")
    enh = enh.convert("RGB")
    res = {"tag": tag, "line": idx, "windows": []}
    # split points in fractions of the line width
    wins = [(0.00, 0.56), (0.44, 0.88), (0.72, 1.00)]
    jobs = []
    for wi, (a, b) in enumerate(wins):
        e, xr = window(enh, a, b)
        ep = os.path.join(outdir, f"{tag}_L{idx:02d}_w{wi+1}.png")
        e.save(ep, optimize=True)
        # also a raw (unenhanced) crop from the source photo, matched in x
        jobs.append((wi, ep, a, b, "enh"))
    for wi, ep, a, b, kind in jobs:
        for s in range(samples):
            res["windows"].append({"win": wi + 1, "x": [a, b], "sample": s + 1,
                                   "file": ep, "kind": kind})
    return res


def run_page(tag, src, lines_json, samples=3, workers=6):
    meta = json.load(open(lines_json))
    src_img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    outdir = os.path.join(WORK, tag, "windows")
    os.makedirs(outdir, exist_ok=True)

    tasks = []
    for s in meta["strips"]:
        if tag == "p1" and s["idx"] == 1:
            continue                        # header only, not music
        tasks.append(s)

    results = {}

    def job(s):
        ln = s["idx"]
        enh = Image.open(s["file"]).convert("L").convert("RGB")
        out = []
        wins = [(0.00, 0.50), (0.25, 0.75), (0.50, 1.00)]
        for wi, (a, b) in enumerate(wins, 1):
            e, xr = window(enh, a, b)
            ep = os.path.join(outdir, f"{tag}_L{ln:02d}_w{wi}.png")
            e.save(ep, optimize=True)
            # raw counterpart from the untouched photo, same fraction of width
            H = src_img.height
            y0 = meta.get("src_y", {}).get(str(ln))
            out.append({"win": wi, "x": list(xr), "file": ep, "kind": "enh"})
        return ln, out

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ln, out in ex.map(job, tasks):
            results[ln] = out

    # sample every window `samples` times
    calls = []
    for ln, wins in sorted(results.items()):
        for w in wins:
            for s in range(samples):
                calls.append((ln, w["win"], w["file"], s))

    answers = {}

    def call(c):
        ln, wi, f, s = c
        temp = 0.0 if s == 0 else 0.9
        try:
            t, fr, u, r = ask(f, PROMPT, thinking="disabled",
                              max_tokens=1400, temperature=temp)
        except SystemExit as e:
            t = f"ERROR: {e}"
        return (ln, wi, s, t)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ln, wi, s, t in ex.map(call, calls):
            answers.setdefault(ln, {}).setdefault(wi, {})[s] = t
            print(f"  {tag} L{ln:02d} w{wi} s{s+1} -> {len(t)} chars")

    outp = os.path.join(WORK, tag, f"{tag}_raw_answers.json")
    json.dump(answers, open(outp, "w"), indent=2, ensure_ascii=False)
    return outp


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pages", default="p1,p2")
    a = ap.parse_args()
    for tag in a.pages.split(","):
        name = "sbd1.jpg" if tag == "p1" else "sbd2.jpg"
        lj = os.path.join(WORK, tag, f"{tag}_lines.json")
        if not os.path.exists(lj):
            print("missing", lj)
            continue
        print(f"=== {tag} ===")
        run_page(tag, os.path.join(BASE, "src", name), lj,
                 samples=a.samples, workers=a.workers)
