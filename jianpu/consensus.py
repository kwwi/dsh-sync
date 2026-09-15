#!/usr/bin/env python3
"""
Build a consensus transcription from the windowed readings.

Each window covers a known fraction of the line width. Because the measures of a
jianpu line are laid out left to right in roughly equal widths, a measure read
inside a window can be mapped back to its global measure slot from the position
it occupies in that window. Every global slot therefore collects several
independent readings, which are then voted on note by note.
"""
import json, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse import extract, norm_oct, norm_beats

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

# window x-ranges used by transcribe.py
WINDOWS = {1: (0.00, 0.50), 2: (0.25, 0.75), 3: (0.50, 1.00)}

# measure counts / edges per line, from the bounds query (fractions of width)
LINE_GEOM = {
    "p1": {2: (4, 0.04, 0.96), 3: (4, 0.04, 0.96), 4: (4, 0.05, 0.96),
           5: (4, 0.04, 0.96), 6: (4, 0.06, 0.97), 7: (3, 0.06, 0.94),
           8: (3, 0.07, 0.90), 9: (3, 0.04, 0.99)},
    "p2": {1: (3, 0.07, 0.99), 2: (2, 0.04, 0.96), 3: (2, 0.05, 0.95),
           4: (3, 0.08, 0.99), 5: (3, 0.07, 0.95), 6: (2, 0.08, 0.98),
           7: (4, 0.03, 0.97), 8: (4, 0.08, 0.97)},
}


def note_key(nt):
    return (nt["n"], norm_oct(nt["oct"]))


def collect(tag):
    ans = json.load(open(os.path.join(WORK, tag, f"{tag}_raw_answers.json")))
    slots = defaultdict(lambda: {"mel": defaultdict(list), "bas": defaultdict(list)})

    for ln in ans:
        ln = int(ln)
        M, xs, xe = LINE_GEOM[tag].get(ln, (4, 0.04, 0.96))
        for wi in ans[str(ln)]:
            wi = int(wi)
            a, b = WINDOWS[wi]
            for si in ans[str(ln)][str(wi)]:
                d = extract(ans[str(ln)][str(wi)][si])
                for field, key in (("melody", "mel"), ("bass", "bas")):
                    ms = d[field]
                    k = len(ms)
                    if k == 0:
                        continue
                    for j, m in enumerate(ms):
                        xc = a + (b - a) * (j + 0.5) / k
                        g = int((xc - xs) / max(xe - xs, 1e-6) * M)
                        g = max(0, min(M - 1, g))
                        slots[(ln, g)][key][wi].append(m)
    return slots


def vote_measure(readings, n_slots=1):
    """
    readings: list of note lists (each a candidate reading of the same measure).
    Returns (consensus_notes, agreement, nitems, nsamples).
    """
    if not readings:
        return [], 0.0, 0, 0
    # vote on the note count first
    lens = Counter(len(r) for r in readings)
    n = lens.most_common(1)[0][0]
    if n == 0:
        return [], 0.0, 0, len(readings)
    cand = [r for r in readings if len(r) == n]
    out = []
    agree = []
    for i in range(n):
        nums = Counter(r[i]["n"] for r in cand)
        nv, nc = nums.most_common(1)[0]
        octs = Counter(norm_oct(r[i]["oct"]) for r in cand if r[i]["n"] == nv)
        ov, oc = octs.most_common(1)[0]
        bts = Counter(round(float(r[i]["beats"]), 3) for r in cand if r[i]["n"] == nv)
        bv, bc = bts.most_common(1)[0]
        out.append({"n": nv, "oct": ov, "beats": bv})
        agree.append((nc / len(cand), oc / max(len(cand), 1), bc / max(len(cand), 1)))
    # combined agreement
    a_num = sum(a[0] for a in agree) / len(agree)
    a_oct = sum(a[1] for a in agree) / len(agree)
    a_bt = sum(a[2] for a in agree) / len(agree)
    return out, (a_num + a_oct + a_bt) / 3, len(cand), len(readings)


def build(tag):
    slots = collect(tag)
    lines = []
    report = []
    for ln in sorted({k[0] for k in slots}):
        M, xs, xe = LINE_GEOM[tag].get(ln, (4, 0.04, 0.96))
        measures = []
        for g in range(M):
            s = slots.get((ln, g))
            if s is None:
                continue
            mel_reads = [m for wi in s["mel"] for m in s["mel"][wi]]
            bas_reads = [m for wi in s["bas"] for m in s["bas"][wi]]
            mel, ma, mn, mt = vote_measure(mel_reads)
            bas, ba, bn, bt = vote_measure(bas_reads)
            measures.append({"melody": mel, "bass": bas})
            report.append({"line": ln, "measure": g + 1,
                           "mel_agree": round(ma, 3), "mel_n": mn, "mel_samples": mt,
                           "bas_agree": round(ba, 3), "bas_n": bn,
                           "mel": " ".join(f"{x['n']}{x['oct']}{x['beats']}" for x in mel),
                           "bas": " ".join(f"{x['n']}{x['oct']}{x['beats']}" for x in bas)})
        lines.append({"index": ln, "measures": measures})
    return lines, report


if __name__ == "__main__":
    allrep = []
    out = {}
    for tag in ("p1", "p2"):
        lines, report = build(tag)
        out[tag] = lines
        allrep += [dict(r, page=tag) for r in report]
    json.dump(out, open(os.path.join(WORK, "consensus.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(allrep, open(os.path.join(WORK, "consensus_report.json"), "w"),
              indent=2, ensure_ascii=False)
    for r in allrep:
        flag = "  " if r["mel_agree"] > 0.8 else ("! " if r["mel_agree"] > 0.5 else "!!")
        print(f'{flag}{r["page"]} L{r["line"]:02d}m{r["measure"]} '
              f'mel={r["mel_agree"]:.2f}({r["mel_n"]}/{r["mel_samples"]}) '
              f'bas={r["bas_agree"]:.2f} | {r["mel"][:70]}')
