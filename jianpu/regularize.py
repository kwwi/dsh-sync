#!/usr/bin/env python3
"""
Regularise the transcribed score.

Two musical facts drive this pass:
  1. A figure that repeats should carry the same octave dots every time it
     appears, so the octave of each distinct number-sequence is unified by
     majority vote across the whole piece.
  2. Every bar of a 4/4 jianpu line must contain exactly four beats, so any
     measure that does not is re-timed, preferring an even subdivision.
"""
import json, os, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0
ALLOWED = [4, 3, 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.125]


def snap(v, lo=0.125):
    v = max(lo, float(v))
    return min(ALLOWED, key=lambda a: abs(a - v))


def num_seq(meas):
    return tuple(x["n"] for x in meas["melody"])


def unify_octaves(pages):
    """One octave pattern per distinct melody number-sequence."""
    groups = defaultdict(list)
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                if m["melody"]:
                    groups[num_seq(m)].append(tuple(x["oct"] for x in m["melody"]))
    canon = {}
    for seq, pats in groups.items():
        canon[seq] = Counter(pats).most_common(1)[0][0]
    changed = 0
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                if not m["melody"]:
                    continue
                want = canon[num_seq(m)]
                for i, x in enumerate(m["melody"]):
                    if i < len(want) and x["oct"] != want[i]:
                        x["oct"] = want[i]
                        changed += 1
    return canon, changed


def unify_bass_octaves(pages):
    groups = defaultdict(list)
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                if m["bass"]:
                    groups[tuple(x["n"] for x in m["bass"])].append(
                        tuple(x["oct"] for x in m["bass"]))
    canon = {k: Counter(v).most_common(1)[0][0] for k, v in groups.items()}
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                if not m["bass"]:
                    continue
                want = canon[tuple(x["n"] for x in m["bass"])]
                for i, x in enumerate(m["bass"]):
                    if i < len(want):
                        x["oct"] = want[i]
    return canon


def retime(meas, log):
    """Make the melody of one measure fill exactly one bar."""
    mel = meas["melody"]
    if not mel:
        return
    durs = [x["beats"] for x in mel]
    tot = sum(durs)
    if abs(tot - BAR) < 1e-9:
        log.append(("ok", tot))
        return

    n = len(mel)
    # 1) a single even subdivision is the common case in this manuscript
    if n and abs(BAR / n * n - BAR) < 1e-9:
        even = BAR / n
        snapped = snap(even)
        if abs(snapped * n - BAR) < 1e-9:
            for x in mel:
                x["beats"] = snapped
            log.append(("even", tot))
            return

    # 2) drop trailing rests that overflow the bar
    if tot > BAR:
        while mel and sum(x["beats"] for x in mel) > BAR and mel[-1]["n"] == 0:
            mel.pop()
            if not mel:
                break
        tot = sum(x["beats"] for x in mel)
        if abs(tot - BAR) < 1e-9:
            log.append(("trim-rest", tot))
            return

    # 3) scale proportionally, then settle the residual on the longest note so
    #    the whole bar lands exactly on a sixteenth-note grid
    if tot > 0 and mel:
        units = [max(1, int(round(x["beats"] * BAR / tot * 4))) for x in mel]
        target = int(round(BAR * 4))
        guard = 0
        while sum(units) != target and guard < 100:
            diff = target - sum(units)
            i = max(range(len(units)), key=lambda k: units[k])
            if diff > 0:
                units[i] += 1
            else:
                # remove from the longest note that can spare a sixteenth
                order = sorted(range(len(units)), key=lambda k: -units[k])
                for k in order:
                    if units[k] > 1:
                        units[k] -= 1
                        break
                else:
                    break
            guard += 1
        for x, u in zip(mel, units):
            x["beats"] = round(u / 4.0, 4)
        log.append(("scaled", tot))


def clean_grid(meas):
    """Snap every melody duration to a conventional value, keeping the bar exact."""
    mel = meas["melody"]
    if not mel:
        return
    for x in mel:
        x["beats"] = snap(x["beats"])
    guard = 0
    while abs(sum(x["beats"] for x in mel) - BAR) > 1e-9 and guard < 50:
        diff = BAR - sum(x["beats"] for x in mel)
        i = max(range(len(mel)), key=lambda k: mel[k]["beats"])
        mel[i]["beats"] = max(0.125, round(mel[i]["beats"] + diff, 4))
        guard += 1
    for x in mel:
        x["beats"] = round(x["beats"], 4)


def retime_bass(meas):
    bas = meas["bass"]
    if not bas:
        return
    if len(bas) == 1:
        bas[0]["beats"] = BAR
        return
    each = BAR / len(bas)
    s = snap(each)
    durs = [s] * len(bas)
    guard = 0
    while abs(sum(durs) - BAR) > 1e-9 and guard < 100:
        diff = BAR - sum(durs)
        durs[-1] = max(0.125, snap(durs[-1] + diff * (1 if diff > 0 else 1)))
        if abs(sum(durs) - BAR) < 1e-9:
            break
        durs[-1] = round(BAR - sum(durs[:-1]), 4)
        guard += 1
    for x, d in zip(bas, durs):
        x["beats"] = round(max(0.125, d), 4)


def main():
    pages = json.load(open(os.path.join(WORK, "score_jianpu.json")))
    canon_m, ch_m = unify_octaves(pages)
    canon_b = unify_bass_octaves(pages)
    log = []
    for tag in pages:
        for line in pages[tag]:
            for m in line["measures"]:
                retime(m, log)
                clean_grid(m)
                retime_bass(m)
    json.dump(pages, open(os.path.join(WORK, "score_final.json"), "w"),
              indent=2, ensure_ascii=False)

    bad = 0
    total = 0
    for tag in ("p1", "p2"):
        for line in pages[tag]:
            for m in line["measures"]:
                total += 1
                b = sum(x["beats"] for x in m["melody"])
                if abs(b - BAR) > 1e-6:
                    bad += 1
                    print(f'  !! {tag} L{line["index"]:02d} bar={b} '
                          f'{[(x["n"], x["beats"]) for x in m["melody"]]}')
    print(f"octave corrections: melody {ch_m}, "
          f"distinct melody figures {len(canon_m)}, "
          f"distinct bass figures {len(canon_b)}")
    print(f"retime classes: {Counter(c for c, _ in log)}")
    print(f"{total} measures, {bad} still off the bar length")


if __name__ == "__main__":
    main()
