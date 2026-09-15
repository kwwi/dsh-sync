#!/usr/bin/env python3
"""Check whether trailing symbols in a measure are rests (0) or holds (dashes)."""
import json, os, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

PROMPT = """Look at this single measure of handwritten jianpu (numbered notation).

I need to know whether the symbol(s) written after the last NUMBER are the digit ZERO (0, a rest) or a DASH (-, which holds the previous note).

Reply with ONLY these two lines, nothing else:
LAST_SYMBOLS: <the exact symbols after the final number, 0 for the digit zero and - for a dash, space separated; write NONE if nothing follows>
NUMBERS: <every digit number in the measure, in order, space separated, ignoring dots/underlines/dashes>
"""


def check(args):
    tag, ln, mi, f = args
    c = Counter()
    for k in range(3):
        try:
            t, fr, u, r = ask(f, PROMPT, thinking="disabled", max_tokens=160,
                              temperature=0.0 if k == 0 else 0.9)
        except SystemExit:
            continue
        m = re.search(r"LAST_SYMBOLS\s*:\s*(.*)", t)
        mm = re.search(r"NUMBERS\s*:\s*(.*)", t)
        c[((m.group(1).strip() if m else "?")[:48],
           (mm.group(1).strip() if mm else "?")[:70])] += 1
    if not c:
        return tag, ln, mi, f, "?", "?", 0
    (last, nums), v = c.most_common(1)[0]
    return tag, ln, mi, f, last, nums, v


def main():
    d = json.load(open(os.path.join(WORK, "score_final.json")))
    targets = []
    for tag in ("p1", "p2"):
        for line in d[tag]:
            for i, m in enumerate(line["measures"]):
                f = os.path.join(WORK, tag, "measures",
                                 f"{tag}_L{line['index']:02d}_m{i+1}.png")
                if os.path.exists(f):
                    targets.append((tag, line["index"], i + 1, f))
    print(f"{len(targets)} measures to check")
    res = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tag, ln, mi, f, last, nums, v in ex.map(check, targets):
            res.append({"page": tag, "line": ln, "m": mi, "file": f,
                        "last": last, "numbers": nums, "votes": v})
            print(f"{tag} L{ln:02d}m{mi}: last=[{last}] nums=[{nums}] x{v}")
    json.dump(res, open(os.path.join(WORK, "zero_check.json"), "w"),
              indent=2, ensure_ascii=False)
    dashes = [r for r in res if "-" in r["last"]]
    print(f"\n{len(dashes)}/{len(res)} measures end with dashes (holds)")


if __name__ == "__main__":
    main()
