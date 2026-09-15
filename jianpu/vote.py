#!/usr/bin/env python3
"""
Vote the per-measure samples into one final jianpu transcription.

For every measure the samples are compared note by note. The most common
reading of the number, of its octave dot, and of its duration wins
independently, so a single bad sample cannot corrupt a note. Measures whose
samples disagree strongly are listed in the report so they can be re-checked.
"""
import json, os, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse import extract, norm_oct, norm_beats
from permeasure import GEOM

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")


def vote_notes(readings):
    """readings: list of note lists. Returns (notes, agreement)."""
    readings = [r for r in readings if r]
    if not readings:
        return [], 0.0, 0
    n = Counter(len(r) for r in readings).most_common(1)[0][0]
    if n == 0:
        return [], 0.0, 0
    cand = [r for r in readings if len(r) == n]
    notes, agree = [], []
    for i in range(n):
        nums = Counter(int(r[i]["n"]) for r in cand)
        nv, nc = nums.most_common(1)[0]
        same = [r[i] for r in cand if int(r[i]["n"]) == nv]
        octs = Counter(norm_oct(x["oct"]) for x in same)
        ov, oc = octs.most_common(1)[0]
        bts = Counter(norm_beats(x["beats"]) for x in same)
        bv, bc = bts.most_common(1)[0]
        notes.append({"n": nv, "oct": ov, "beats": bv})
        agree.append((nc / len(cand), oc / len(same), bc / len(same)))
    score = sum((a[0] + a[1] + a[2]) / 3 for a in agree) / len(agree)
    return notes, score, len(cand)


def build(tag):
    ans = json.load(open(os.path.join(WORK, tag, f"{tag}_measure_answers.json")))
    lines, report = [], []
    for ln_s in sorted(ans, key=int):
        ln = int(ln_s)
        M = GEOM[tag][ln][0]
        measures = []
        for m_s in sorted(ans[ln_s], key=int):
            m = int(m_s)
            samples = [extract(t) for t in ans[ln_s][m_s].values()]
            mel, ms, mn = vote_notes([s["melody"][0] if s["melody"] else []
                                      for s in samples])
            # a measure reading may come back as several measures; keep the first
            bas, bs, bn = vote_notes([s["bass"][0] if s["bass"] else []
                                      for s in samples])
            chords = Counter(s["chords"].strip() for s in samples
                             if s["chords"] and s["chords"].strip().lower()
                             not in ("none", "", "-"))
            chord = chords.most_common(1)[0][0] if chords else None
            measures.append({"melody": mel, "bass": bas, "chord": chord,
                             "beats": sum(x["beats"] for x in mel)})
            report.append({"page": tag, "line": ln, "measure": m,
                           "mel_agree": round(ms, 3), "mel_notes": len(mel),
                           "mel_samples": mn,
                           "bas_agree": round(bs, 3), "bas_notes": len(bas),
                           "beats": round(sum(x["beats"] for x in mel), 3),
                           "mel": " ".join(f"{x['n']}{x['oct']}:{x['beats']}"
                                           for x in mel),
                           "bas": " ".join(f"{x['n']}{x['oct']}:{x['beats']}"
                                           for x in bas)})
        lines.append({"index": ln, "measures": measures})
    return lines, report


if __name__ == "__main__":
    out, rep = {}, []
    for tag in ("p1", "p2"):
        p = os.path.join(WORK, tag, f"{tag}_measure_answers.json")
        if not os.path.exists(p):
            print("missing", p)
            continue
        lines, report = build(tag)
        out[tag] = lines
        rep += report
    json.dump(out, open(os.path.join(WORK, "measures_voted.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(rep, open(os.path.join(WORK, "measures_report.json"), "w"),
              indent=2, ensure_ascii=False)
    bad = 0
    for r in rep:
        flag = "  " if r["mel_agree"] >= 0.85 else ("? " if r["mel_agree"] >= 0.6 else "!!")
        if r["mel_agree"] < 0.6:
            bad += 1
        ok = "ok" if abs(r["beats"] - 4.0) < 1e-6 else f'BEATS={r["beats"]}'
        print(f'{flag}{r["page"]} L{r["line"]:02d}m{r["measure"]} '
              f'{r["mel_agree"]:.2f} [{r["mel_notes"]}] {ok:10s} | {r["mel"][:72]} | B:{r["bas"][:24]}')
    print(f"\n{bad} measures below 0.60 agreement "
          f"(of {len(rep)})")
