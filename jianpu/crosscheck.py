#!/usr/bin/env python3
"""
Cross-check the finished transcription against an independent read of the same
measure crops, and repair trailing rests.

The zero/hold check produced, for every measure, an independent list of the
digit numbers visible in that crop, plus what is written after the final number.
A measure's melody should appear as a contiguous run inside that list; where it
does not, the two readings disagree and the measure is reported. Where the
measure's own trailing rests are contradicted by dashes in the image, the rests
become holds on the preceding note.
"""
import json, os, re, sys
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
BAR = 4.0


def seq_of_reading(s):
    out = []
    for tok in re.findall(r"\d+", s or ""):
        if len(tok) == 1:
            out.append(int(tok))
        else:
            # a merged pair such as '06' means two numbers
            out.extend(int(c) for c in tok)
    return out


def find_run(hay, needle):
    """All start indices where needle occurs in hay."""
    if not needle:
        return []
    hits = []
    for i in range(len(hay) - len(needle) + 1):
        if hay[i:i + len(needle)] == needle:
            hits.append(i)
    return hits


def main():
    score = json.load(open(os.path.join(WORK, "score_final.json")))
    checks = {(c["page"], c["line"], c["m"]): c
              for c in json.load(open(os.path.join(WORK, "zero_check.json")))}

    agree = disagree = nomatch = 0
    fixed = 0
    problems = []
    for tag in ("p1", "p2"):
        for line in score[tag]:
            for i, meas in enumerate(line["measures"]):
                key = (tag, line["index"], i + 1)
                chk = checks.get(key)
                mel = meas["melody"]
                seq = [x["n"] for x in mel]
                if chk is None:
                    continue
                nums = seq_of_reading(chk["numbers"])

                if seq and find_run(nums, seq):
                    agree += 1
                    continue
                # try without trailing rests (the crop often shows the next bar too)
                core = list(seq)
                while core and core[-1] == 0:
                    core.pop()
                if core and find_run(nums, core):
                    agree += 1
                    # the trailing rests may really be holds
                    last = chk["last"]
                    if "-" in last and "0" not in last:
                        while mel and mel[-1]["n"] == 0:
                            held = mel.pop()
                            if mel:
                                mel[-1]["beats"] = round(
                                    mel[-1]["beats"] + held["beats"], 4)
                        fixed += 1
                    continue
                if not nums or nums == [0] and not seq:
                    nomatch += 1
                    continue
                disagree += 1
                problems.append({
                    "page": tag, "line": line["index"], "measure": i + 1,
                    "mine": " ".join(map(str, seq)),
                    "independent": " ".join(map(str, nums)),
                    "last": chk["last"],
                })

    # re-balance any measure whose total changed after the repair
    for tag in ("p1", "p2"):
        for line in score[tag]:
            for meas in line["measures"]:
                mel = meas["melody"]
                if not mel:
                    continue
                tot = sum(x["beats"] for x in mel)
                if abs(tot - BAR) > 1e-6:
                    # put the residual on the longest note
                    i = max(range(len(mel)), key=lambda k: mel[k]["beats"])
                    mel[i]["beats"] = round(
                        max(0.125, mel[i]["beats"] + (BAR - tot)), 4)

    json.dump(score, open(os.path.join(WORK, "score_final.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(problems, open(os.path.join(WORK, "crosscheck.json"), "w"),
              indent=2, ensure_ascii=False)

    print(f"measures whose numbers appear verbatim in the independent read: {agree}")
    print(f"measures in disagreement: {disagree}")
    print(f"measures ending in holds repaired from rests: {fixed}")
    print()
    for p in problems:
        print(f'  {p["page"]} L{p["line"]:02d}m{p["measure"]}: '
              f'mine=[{p["mine"]}]  independent=[{p["independent"]}]  last=[{p["last"]}]')


if __name__ == "__main__":
    main()
