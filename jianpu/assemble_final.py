#!/usr/bin/env python3
"""
Assemble the definitive transcription.

The decomposed reading is preferred because each of its answers (which digits,
each digit's dot, each digit's underlines, what follows the last digit) is a
separate, easy question. Where it yields a measure that fills exactly one bar it
is adopted; where it does not, the earlier per-measure vote is kept. Octaves come
from the decomposed read, which reports them far more consistently. Finally the
bar length is enforced and repeated figures are made rhythmically identical.
"""
import json, os, re, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0
UL_BEATS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}


def build_from_simple(simple):
    """Return (notes, ok) for one measure from the decomposed read."""
    nums = simple.get("numbers") or []
    if not nums:
        return None, False
    dots = simple.get("dots") or []
    uls = simple.get("underlines") or []
    after = (simple.get("after") or "").strip().lower()
    dashes = after.count("-")

    # try every prefix; the measure is the prefix that fills exactly one bar
    best = None
    for k in range(1, len(nums) + 1):
        notes = []
        for i in range(k):
            ul = uls[i] if i < len(uls) else 1
            d = UL_BEATS.get(ul, 1.0)
            notes.append({"n": nums[i], "oct": "mid", "beats": d})
        if dots and len(dots) == len(nums):
            for i in range(k):
                notes[i]["oct"] = dots[i]
        # dashes extend the final note of the measure
        notes[-1]["beats"] += dashes
        tot = sum(x["beats"] for x in notes)
        if abs(tot - BAR) < 1e-6:
            best = notes
            break
    if best is not None:
        return best, True
    # no exact prefix: use the whole list and let the caller regularise
    notes = []
    for i, n in enumerate(nums):
        ul = uls[i] if i < len(uls) else 1
        notes.append({"n": n, "oct": dots[i] if i < len(dots) else "mid",
                      "beats": UL_BEATS.get(ul, 1.0)})
    if notes:
        notes[-1]["beats"] += dashes
    return notes, False


def simple_bass(simple):
    b = simple.get("bass") or []
    b = [n for n in b if n is not None]
    return b


def enforce_bar(notes):
    if not notes:
        return
    tot = sum(x["beats"] for x in notes)
    if abs(tot - BAR) < 1e-6:
        return
    units = [max(1, int(round(x["beats"] * 4))) for x in notes]
    target = int(BAR * 4)
    guard = 0
    while sum(units) != target and guard < 200:
        if sum(units) < target:
            i = max(range(len(units)), key=lambda k: units[k])
            units[i] += 1
        else:
            order = sorted(range(len(units)), key=lambda k: -units[k])
            for k in order:
                if units[k] > 1:
                    units[k] -= 1
                    break
            else:
                break
        guard += 1
    for x, u in zip(notes, units):
        x["beats"] = round(u / 4.0, 4)


def unify_figures(pages):
    """Identical number sequences get an identical rhythm (majority)."""
    groups = defaultdict(list)
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                seq = tuple(x["n"] for x in m["melody"])
                if seq:
                    groups[seq].append(tuple(x["beats"] for x in m["melody"]))
    canon = {}
    for seq, pats in groups.items():
        # only unify when every occurrence has the same length (it must)
        pats = [p for p in pats if len(p) == len(seq)]
        if pats:
            canon[seq] = Counter(pats).most_common(1)[0][0]
    n = 0
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                seq = tuple(x["n"] for x in m["melody"])
                if seq and seq in canon and len(canon[seq]) == len(m["melody"]):
                    for x, b in zip(m["melody"], canon[seq]):
                        if abs(x["beats"] - b) > 1e-9:
                            x["beats"] = b
                            n += 1
    return n


def main():
    pages = json.load(open(os.path.join(WORK, "score_final.json")))
    simple = json.load(open(os.path.join(WORK, "simple_read.json")))

    adopted = kept = 0
    for tag in ("p1", "p2"):
        for line in pages[tag]:
            ln = line["index"]
            for i, meas in enumerate(line["measures"]):
                s = simple.get(tag, {}).get(str(ln), {}).get(str(i + 1))
                if not s:
                    continue
                notes, ok = build_from_simple(s)
                if ok and notes:
                    meas["melody"] = notes
                    adopted += 1
                else:
                    kept += 1
                b = simple_bass(s)
                if b:
                    if len(b) == 1:
                        meas["bass"] = [{"n": b[0], "oct": "dn1", "beats": BAR}]
                    else:
                        meas["bass"] = [{"n": x, "oct": "dn1",
                                         "beats": round(BAR / len(b), 4)}
                                        for x in b]
                        enforce_bar(meas["bass"])

    for tag in ("p1", "p2"):
        for line in pages[tag]:
            for m in line["measures"]:
                enforce_bar(m["melody"])

    changed = unify_figures(pages)
    for tag in ("p1", "p2"):
        for line in pages[tag]:
            for m in line["measures"]:
                enforce_bar(m["melody"])

    json.dump(pages, open(os.path.join(WORK, "score_final.json"), "w"),
              indent=2, ensure_ascii=False)
    print(f"measures taken from the decomposed read: {adopted}")
    print(f"measures kept from the first vote:        {kept}")
    print(f"durations unified across repeated figures: {changed}")

    bad = 0
    for tag in ("p1", "p2"):
        for line in pages[tag]:
            for m in line["measures"]:
                if abs(sum(x["beats"] for x in m["melody"]) - BAR) > 1e-6:
                    bad += 1
    print(f"measures whose bar length is still wrong: {bad}")


if __name__ == "__main__":
    main()
