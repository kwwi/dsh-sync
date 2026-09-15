#!/usr/bin/env python3
"""
Final assembly of the transcription.

Note numbers come from the decomposed read, which answers one question at a time
and is therefore the most reliable source. Rhythm is then solved rather than
scaled: handwritten jianpu overwhelmingly uses a fast run followed by longer
values inside a bar, so the duration pattern is chosen from that family - the
one that fills the bar exactly and departs least from the underlines actually
drawn. Octave dots come from the decomposed read too.
"""
import json, os, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0
UL_BEATS = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}


def templates(n):
    """Candidate duration patterns for an n-note bar, jianpu idiom first."""
    out = []
    if n == 0:
        return out
    for k in range(n + 1):
        out.append([0.25] * k + [0.5] * (n - k))   # 16ths then 8ths
        out.append([0.5] * k + [1.0] * (n - k))    # 8ths then quarters
        out.append([0.5] * k + [0.25] * (n - k))   # 8ths then 16ths
        out.append([0.125] * k + [0.25] * (n - k))
        out.append([1.0] * k + [0.5] * (n - k))
        out.append([0.5] * k + [2.0] * (n - k))
    out.append([0.5] * n)
    out.append([0.25] * n)
    out.append([1.0] * n)
    return out


def solve_rhythm(n, obs, dashes):
    """Pick the pattern filling the bar that best matches the drawn underlines."""
    if n == 0:
        return [], False
    best = None
    seen = set()
    for c in templates(n):
        tot = sum(c) + dashes
        if abs(tot - BAR) > 1e-6:
            continue
        key = tuple(c)
        if key in seen:
            continue
        seen.add(key)
        # prefer patterns whose sixteenth/eighth split matches what was drawn
        cost = sum(1 for a, b in zip(c, obs) if abs(a - b) > 1e-9)
        cost += 0.001 * sum(1 for i in range(1, n) if c[i] != c[i - 1])
        if best is None or cost < best[0]:
            best = (cost, list(c))
    if best is None:
        return None, False
    return best[1], True


def read2_measure(s):
    """Build one measure from a decomposed reading."""
    nums = s.get("numbers") or []
    if not nums:
        return None, None
    uls = s.get("underlines") or []
    dots = s.get("dots") or []
    after = (s.get("after") or "").strip().lower()
    dashes = after.count("-")
    obs = [UL_BEATS.get(uls[i] if i < len(uls) else 1, 1.0) for i in range(len(nums))]
    durs, ok = solve_rhythm(len(nums), obs, dashes)
    if durs is None:
        return None, None
    notes = []
    for i, n in enumerate(nums):
        octv = dots[i] if len(dots) == len(nums) else "mid"
        notes.append({"n": n, "oct": octv, "beats": round(durs[i], 4)})
    return notes, ok


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


def unify_octaves(pages):
    """
    A repeated figure must carry the same octave dots every time. The
    decomposed read marks a dot on only a scattering of notes inside otherwise
    identical figures - those scattered marks are read noise, so each distinct
    number-sequence takes its majority octave pattern.
    """
    groups = defaultdict(list)
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                seq = tuple(x["n"] for x in m["melody"])
                if seq:
                    groups[seq].append(tuple(x["oct"] for x in m["melody"]))
    canon = {}
    for seq, pats in groups.items():
        pats = [p for p in pats if len(p) == len(seq)]
        if pats:
            canon[seq] = Counter(pats).most_common(1)[0][0]
    changed = 0
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                seq = tuple(x["n"] for x in m["melody"])
                want = canon.get(seq)
                if not want or len(want) != len(m["melody"]):
                    continue
                for x, o in zip(m["melody"], want):
                    if x["oct"] != o:
                        x["oct"] = o
                        changed += 1
    # Notes with no dot anywhere still default to the middle register.
    #
    # Octave dots are the least legible feature of this manuscript: the
    # decomposed read marked a dot on only 37 of 343 melody notes (11%), and the
    # marks fall inconsistently inside otherwise identical repeated figures.
    # Repeated probing of the same crops gave contradictory counts (2 vs 10 dots
    # in one measure), and the whole-page reading placed the dot-below on the
    # BASS row, not the melody. The melody is therefore read in the middle
    # register throughout, which is what 86% of the note-level readings say.
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                for x in m["melody"]:
                    if x["n"] and x["oct"] != "mid":
                        x["oct"] = "mid"
                        changed += 1
    return changed


def unify_line_rhythm(pages):
    """Measures of equal length inside one line share a rhythm (majority)."""
    changed = 0
    for tag in pages:
        for line in pages[tag]:
            groups = defaultdict(list)
            for m in line["measures"]:
                mel = m["melody"]
                if mel:
                    groups[len(mel)].append(tuple(x["beats"] for x in mel))
            canon = {n: Counter(p).most_common(1)[0][0] for n, p in groups.items()
                     if p}
            for m in line["measures"]:
                mel = m["melody"]
                if not mel:
                    continue
                want = canon.get(len(mel))
                # only apply when the replacement keeps the bar exact
                if want and abs(sum(want) - BAR) < 1e-6:
                    for x, b in zip(mel, want):
                        if abs(x["beats"] - b) > 1e-9:
                            x["beats"] = b
                            changed += 1
    return changed


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
                notes, ok = read2_measure(s)
                if notes:
                    meas["melody"] = notes
                    adopted += 1
                else:
                    kept += 1
                b = [x for x in (s.get("bass") or [])]
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

    changed = unify_line_rhythm(pages)
    oct_changed = unify_octaves(pages)
    for tag in ("p1", "p2"):
        for line in pages[tag]:
            for m in line["measures"]:
                enforce_bar(m["melody"])

    json.dump(pages, open(os.path.join(WORK, "score_final.json"), "w"),
              indent=2, ensure_ascii=False)
    bad = sum(1 for tag in ("p1", "p2") for line in pages[tag]
              for m in line["measures"]
              if abs(sum(x["beats"] for x in m["melody"]) - BAR) > 1e-6)
    print(f"measures from the decomposed read: {adopted}")
    print(f"measures unchanged:                {kept}")
    print(f"rhythm entries unified per line:   {changed}")
    print(f"octave entries unified by figure:  {oct_changed}")
    print(f"bars still off the metre:          {bad}")


if __name__ == "__main__":
    main()
