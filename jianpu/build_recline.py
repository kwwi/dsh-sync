#!/usr/bin/env python3
"""
Build the final score from the ruling-dot-free re-reading.

Order of operations matters here. The digits are recovered first, because they
are what the vision model reads most reliably; the rhythm is solved afterwards,
because the underline counts that come back are frequently garbled.

  1. Vote the digit sequence of each measure across the samples.
  2. Leading-rest repair: the model drops the rest that opens a measure, so the
     first measure of a line returns one digit short while its identical repeat
     later in the line is complete. A reading that equals another plus a leading
     rest is replaced by the complete form.
  3. Repeat unification: measures with the same digit sequence share a reading.
  4. Rhythm is solved from the family of patterns jianpu actually uses - a fast
     run followed by longer values - choosing the one that fills the bar and
     departs least from the underlines that were reported.
"""
import json, os, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0
UL_BEATS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}


def templates(n):
    out = []
    if n == 0:
        return out
    for k in range(n + 1):
        out.append([0.25] * k + [0.5] * (n - k))
        out.append([0.5] * k + [1.0] * (n - k))
        out.append([0.5] * k + [0.25] * (n - k))
        out.append([0.125] * k + [0.25] * (n - k))
        out.append([1.0] * k + [0.5] * (n - k))
        out.append([0.25] * k + [1.0] * (n - k))
    out += [[0.5] * n, [0.25] * n, [1.0] * n, [0.5] * n]
    return out


def solve_rhythm(n, obs, dashes):
    if n == 0:
        return None
    best, seen = None, set()
    for c in templates(n):
        if abs(sum(c) + dashes - BAR) > 1e-9:
            continue
        key = tuple(c)
        if key in seen:
            continue
        seen.add(key)
        cost = sum(1 for a, b in zip(c, obs) if abs(a - b) > 1e-9)
        cost += 0.001 * sum(1 for i in range(1, n) if c[i] != c[i - 1])
        if best is None or cost < best[0]:
            best = (cost, list(c))
    return best[1] if best else None


def vote_digits(samples):
    """Majority digit sequence, preferring the one that can fill a bar."""
    seqs = Counter(tuple(s["numbers"]) for s in samples
                   if s and s["numbers"])
    if not seqs:
        return None
    top = seqs.most_common()
    for seq, cnt in top:
        if solve_rhythm(len(seq), [1.0] * len(seq), 0):
            return {"numbers": list(seq), "count": cnt,
                    "underlines": _major_ul(samples, seq),
                    "dashes": _major_dash(samples, seq),
                    "bass": _major_bass(samples, seq)}
    seq, cnt = top[0]
    return {"numbers": list(seq), "count": cnt,
            "underlines": _major_ul(samples, seq),
            "dashes": _major_dash(samples, seq),
            "bass": _major_bass(samples, seq)}


def _same(samples, seq):
    return [s for s in samples if s and tuple(s["numbers"]) == tuple(seq)]


def _major_ul(samples, seq):
    same = _same(samples, seq)
    c = Counter(tuple(s["underlines"][:len(seq)]) for s in same
                if len(s["underlines"]) >= len(seq))
    return list(c.most_common(1)[0][0]) if c else [1] * len(seq)


def _major_dash(samples, seq):
    same = _same(samples, seq)
    c = Counter(s["dashes"] for s in same)
    return c.most_common(1)[0][0] if c else 0


def _major_bass(samples, seq):
    same = _same(samples, seq)
    c = Counter(tuple(s["bass"]) for s in same if s["bass"])
    return list(c.most_common(1)[0][0]) if c else []


MELODY_FIELDS = ("numbers", "underlines", "dashes")


def repair_leading_rest(measures):
    """
    Adopt the complete form when a reading is another plus a leading rest.

    Only the melody is copied: measures of this piece repeat their melody while
    changing the bass note under it, so the bass always stays with its own
    measure.
    """
    fixed = 0
    for i, a in enumerate(measures):
        if not a:
            continue
        for j, b in enumerate(measures):
            if i == j or not b or not b["numbers"]:
                continue
            if b["numbers"][0] != 0:
                continue
            if (b["numbers"][1:] == a["numbers"]
                    and len(b["numbers"]) == len(a["numbers"]) + 1):
                for f in MELODY_FIELDS:
                    measures[i][f] = list(b[f]) if isinstance(b[f], list) else b[f]
                fixed += 1
                break
    return fixed


def unify_repeats(measures):
    """Only the melody is shared; each measure keeps its own bass note."""
    groups = defaultdict(list)
    for i, m in enumerate(measures):
        if m:
            groups[tuple(m["numbers"])].append(i)
    for seq, idxs in groups.items():
        if len(idxs) < 2:
            continue
        best = max((measures[i] for i in idxs), key=lambda m: m["count"])
        for i in idxs:
            for f in MELODY_FIELDS:
                measures[i][f] = list(best[f]) if isinstance(best[f], list) else best[f]


def to_notes(m):
    n = len(m["numbers"])
    obs = [UL_BEATS.get(u, 1.0) for u in m["underlines"]]
    durs = solve_rhythm(n, obs, m["dashes"])
    if durs is None:
        durs = [BAR / n] * n if n else []
    notes = [{"n": x, "oct": "mid", "beats": round(d, 4)}
             for x, d in zip(m["numbers"], durs)]
    return notes


def enforce_bar(notes):
    if not notes:
        return
    tot = sum(x["beats"] for x in notes)
    if abs(tot - BAR) < 1e-6:
        return
    units = [max(1, int(round(x["beats"] * 4))) for x in notes]
    target = int(BAR * 4)
    guard = 0
    while sum(units) != target and guard < 400:
        if sum(units) < target:
            i = max(range(len(units)), key=lambda k: units[k])
            units[i] += 1
        else:
            for k in sorted(range(len(units)), key=lambda k: -units[k]):
                if units[k] > 1:
                    units[k] -= 1
                    break
            else:
                break
        guard += 1
    for x, u in zip(notes, units):
        x["beats"] = round(u / 4.0, 4)


def main():
    data = json.load(open(os.path.join(WORK, "recline.json")))
    pages, report = {}, []
    fixes = 0
    for tag in ("p1", "p2"):
        lines = []
        for ln_s in sorted(data.get(tag, {}), key=int):
            ln = int(ln_s)
            by_idx = defaultdict(list)
            for k, p in data[tag][ln_s].items():
                if not p:
                    continue
                for m in p["measures"]:
                    by_idx[m["idx"]].append(m)
            voted = [vote_digits(by_idx[i]) for i in sorted(by_idx)]
            fixes += repair_leading_rest(voted)
            unify_repeats(voted)
            measures = []
            for m in voted:
                if m is None:
                    continue
                notes = to_notes(m)
                enforce_bar(notes)
                bass = [{"n": b, "oct": "dn1", "beats": BAR} for b in m["bass"]]
                if len(bass) > 1:
                    for x in bass:
                        x["beats"] = round(BAR / len(bass), 4)
                    enforce_bar(bass)
                measures.append({"melody": notes, "bass": bass, "chord": None})
                report.append({"page": tag, "line": ln,
                               "measure": len(measures),
                               "count": m["count"],
                               "mel": " ".join(map(str, m["numbers"])),
                               "bass": " ".join(map(str, m["bass"])),
                               "bar": round(sum(x["beats"] for x in notes), 3)})
            lines.append({"index": ln, "measures": measures})
        pages[tag] = lines

    json.dump(pages, open(os.path.join(WORK, "score_final.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(report, open(os.path.join(WORK, "recline_report.json"), "w"),
              indent=2, ensure_ascii=False)

    bad = 0
    for tag in ("p1", "p2"):
        print(f"##### {tag} #####")
        for line in pages[tag]:
            for i, m in enumerate(line["measures"]):
                b = sum(x["beats"] for x in m["melody"])
                if abs(b - BAR) > 1e-6:
                    bad += 1
                marks = []
                for x in m["melody"]:
                    s = str(x["n"])
                    if abs(x["beats"] - 0.5) < 1e-9:
                        s += "_"
                    elif abs(x["beats"] - 0.25) < 1e-9:
                        s += "__"
                    elif abs(x["beats"] - 1.0) > 1e-9:
                        s += f"[{x['beats']}]"
                    marks.append(s)
                print(f"  L{line['index']:02d}m{i+1}: " + " ".join(marks)
                      + "  | B: " + " ".join(str(x["n"]) for x in m["bass"]))
    print(f"\nleading-rest repairs: {fixes}")
    print(f"bars off the metre:   {bad}")


if __name__ == "__main__":
    main()
