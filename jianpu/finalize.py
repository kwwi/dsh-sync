#!/usr/bin/env python3
"""
Turn the voted measure readings into a final, metrically consistent score.

Pitch (number + octave dot) is voted note by note, which is the reliable part.
Durations are then resolved against the metre: among the samples that agree with
the winning pitch sequence, the duration pattern that best fills one 4/4 bar is
chosen, so the internal rhythm of a reading is preserved instead of being
averaged away note by note.
"""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse import extract, norm_oct, norm_beats
from permeasure import GEOM

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0
ALLOWED = [4, 3, 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.125]


def snap(v):
    return min(ALLOWED, key=lambda a: abs(a - v))


def vote_pitch(readings):
    readings = [r for r in readings if r]
    if not readings:
        return [], 0
    n = Counter(len(r) for r in readings).most_common(1)[0][0]
    cand = [r for r in readings if len(r) == n]
    if n == 0:
        return [], 0
    out = []
    for i in range(n):
        nums = Counter(int(r[i]["n"]) for r in cand)
        nv, nc = nums.most_common(1)[0]
        same = [r[i] for r in cand if int(r[i]["n"]) == nv]
        ov = Counter(norm_oct(x["oct"]) for x in same).most_common(1)[0][0]
        out.append({"n": nv, "oct": ov})
    return out, len(cand)


def resolve_durations(dur_vectors):
    """Pick the duration pattern that best fills one bar."""
    if not dur_vectors:
        return None, 0.0
    scored = []
    for dv in dur_vectors:
        tot = sum(dv)
        scored.append((abs(tot - BAR), -len(dv), dv, tot))
    # prefer patterns that fill the bar exactly, then the most common one
    exact = [s for s in scored if s[0] < 1e-6]
    if exact:
        cnt = Counter(tuple(s[2]) for s in exact)
        best = cnt.most_common(1)[0][0]
        return list(best), 1.0
    cnt = Counter(tuple(s[2]) for s in scored)
    best_tuple, freq = cnt.most_common(1)[0]
    tot = sum(best_tuple)
    return list(best_tuple), _fit(list(best_tuple), tot)


def _fit(durs, tot):
    """Nudge a duration pattern to the bar length, flagging how far it moved."""
    if abs(tot - BAR) < 1e-6:
        return 1.0
    if tot <= 0:
        return 0.0
    # scale, then repair with the smallest edits
    scaled = [snap(max(0.125, d * BAR / tot)) for d in durs]
    for _ in range(60):
        s = sum(scaled)
        if abs(s - BAR) < 1e-6:
            break
        diff = BAR - s
        # apply the correction to the note whose rounding error is largest
        best_i, best_err = None, None
        for i, (orig, sc) in enumerate(zip(durs, scaled)):
            target = orig * BAR / tot
            err = abs(sc - target)
            if best_err is None or err > best_err:
                best_i, best_err = i, err
        step = 0.125 if diff > 0 else -0.125
        nv = snap(scaled[best_i] + step)
        if nv == scaled[best_i]:
            nv = scaled[best_i] + step
        scaled[best_i] = max(0.0625, nv)
    return max(0.0, 1.0 - abs(sum(scaled) - BAR) / BAR)


def build(tag):
    ans = json.load(open(os.path.join(WORK, tag, f"{tag}_measure_answers.json")))
    lines, report = [], []
    for ln_s in sorted(ans, key=int):
        ln = int(ln_s)
        measures = []
        for m_s in sorted(ans[ln_s], key=int):
            m = int(m_s)
            samples = [extract(t) for t in ans[ln_s][m_s].values()]
            mel_samples = [s["melody"][0] for s in samples if s["melody"]]
            bas_samples = [s["bass"][0] for s in samples if s["bass"]]

            mel, nmel = vote_pitch(mel_samples)
            dvs = []
            for r in mel_samples:
                if len(r) != len(mel):
                    continue
                if any(int(a["n"]) != b["n"] for a, b in zip(r, mel)):
                    continue
                dvs.append([norm_beats(a["beats"]) for a in r])
            durs, fit = resolve_durations(dvs)
            if durs is None:
                durs = [0.5] * len(mel)
                if mel:
                    durs = [BAR / len(mel)] * len(mel)
                fit = 0.0
            for nt, d in zip(mel, durs):
                nt["beats"] = d
            if durs and abs(sum(durs) - BAR) > 1e-6:
                # force the bar length by adjusting the longest note
                idx = max(range(len(durs)), key=lambda i: durs[i])
                durs[idx] = max(0.125, snap(durs[idx] + (BAR - sum(durs))))
                for nt, d in zip(mel, durs):
                    nt["beats"] = d

            bas, nbas = vote_pitch(bas_samples)
            bdurs = []
            for r in bas_samples:
                if len(r) == len(bas):
                    bdurs.append([norm_beats(a["beats"]) for a in r])
            if bas:
                # the bass of a measure normally holds the whole bar
                tot = Counter(sum(d) for d in bdurs).most_common(1)[0][0] if bdurs else BAR
                if len(bas) == 1:
                    bas[0]["beats"] = BAR
                else:
                    d = [round(BAR / len(bas), 3)] * len(bas)
                    d = [snap(x) for x in d]
                    fix = BAR - sum(d)
                    d[-1] = max(0.125, snap(d[-1] + fix))
                    for nt, dd in zip(bas, d):
                        nt["beats"] = dd

            chords = Counter(s["chords"].strip() for s in samples
                             if s["chords"] and s["chords"].strip().lower()
                             not in ("none", "", "-"))
            chord = chords.most_common(1)[0][0] if chords else None

            measures.append({"melody": mel, "bass": bas, "chord": chord})
            report.append({"page": tag, "line": ln, "measure": m,
                           "n_mel": len(mel), "n_bas": len(bas),
                           "dur_fit": round(fit, 3),
                           "mel": " ".join(f"{x['n']}{x['oct']}:{x['beats']}" for x in mel),
                           "bas": " ".join(f"{x['n']}{x['oct']}:{x['beats']}" for x in bas),
                           "bar": round(sum(x["beats"] for x in mel), 3)})
        lines.append({"index": ln, "measures": measures})
    return lines, report


if __name__ == "__main__":
    out, rep = {}, []
    for tag in ("p1", "p2"):
        p = os.path.join(WORK, tag, f"{tag}_measure_answers.json")
        if not os.path.exists(p):
            continue
        lines, report = build(tag)
        out[tag] = lines
        rep += report
    json.dump(out, open(os.path.join(WORK, "score_jianpu.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(rep, open(os.path.join(WORK, "score_report.json"), "w"),
              indent=2, ensure_ascii=False)
    bad = 0
    for r in rep:
        ok = abs(r["bar"] - 4.0) < 1e-6
        if not ok:
            bad += 1
        print(f'{"  " if ok else "!!"}{r["page"]} L{r["line"]:02d}m{r["measure"]} '
              f'fit={r["dur_fit"]:.2f} bar={r["bar"]} | {r["mel"][:78]} | B:{r["bas"][:26]}')
    print(f"\n{len(rep)} measures, {bad} not filling a 4/4 bar")
