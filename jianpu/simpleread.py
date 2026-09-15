#!/usr/bin/env python3
"""
Second, independent reading of every measure using a decomposed format.

Asking one question at a time - which digits, then the dot of each digit, then
the underline count of each digit, then what follows - is far more reliable than
asking for a packed token per note, and it yields a second opinion that can be
compared with the first pass.
"""
import json, os, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

PROMPT = """This is a magnified crop of ONE measure of handwritten jianpu (Chinese numbered notation). A vertical bar line separates it from the neighbouring measures, which may be partly visible at the edges.

Answer by filling in these five lines. Work through the measure strictly left to right.

NUMBERS: every digit written as a note, in order, as SINGLE digits separated by spaces. A written "06" is two numbers: 0 then 6. Do NOT include numbers that lie beyond a bar line.
DOTS: for each number in NUMBERS, in the same order, write one of: above (a dot above the number), below (a dot below it), none (no dot). 
UNDERLINES: for each number in NUMBERS, in the same order, write how many short lines are drawn UNDERNEATH it: 0, 1, 2 or 3.
AFTER: what is written AFTER the last number, before the bar line: write "-" for each dash, "0" for each written digit zero, or "none" if the measure ends with the last number.
BASS: the notes of the lower row of this measure, as digits separated by spaces, with "none" if there is no lower row.

Rules:
- NUMBERS, DOTS and UNDERLINES must all have exactly the same number of entries.
- Read every digit. Do not stop early and do not invent digits.
- The lower row (BASS) is a separate line of bigger, more widely spaced digits written underneath.

Example of a valid answer:
NUMBERS: 0 6 1 6 0 6 1 6
DOTS: none none below none none below none none
UNDERLINES: 1 1 1 1 1 1 1 1
AFTER: none
BASS: 6
"""


def parse(text):
    def grab(name):
        m = re.search(rf"^{name}\s*:\s*(.*)$", text, re.M | re.I)
        return m.group(1).strip() if m else ""
    nums = [int(c) for c in re.findall(r"\d", grab("NUMBERS"))]
    dots_raw = grab("DOTS").lower()
    dots = []
    for w in re.split(r"[,\s]+", dots_raw):
        w = w.strip()
        if not w:
            continue
        if "abov" in w or w.startswith("up"):
            dots.append("up1")
        elif "bel" in w or w.startswith("dn"):
            dots.append("dn1")
        elif "none" in w or "no" == w:
            dots.append("mid")
    uls = [int(c) for c in re.findall(r"\d", grab("UNDERLINES"))]
    after = grab("AFTER").lower()
    bass = [int(c) for c in re.findall(r"\d", grab("BASS"))]
    return {"numbers": nums, "dots": dots, "underlines": uls,
            "after": after, "bass": bass}


def beats_from(ul, afters):
    """Mirror the jianpu convention: underline count -> note value, dashes hold."""
    base = {0: 1.0, 1: 0.5, 2: 0.25, 3: 0.125}.get(ul, 1.0)
    return base


def one(args):
    tag, ln, mi, f = args
    try:
        t, fr, u, r = ask(f, PROMPT, thinking="disabled", max_tokens=700,
                          temperature=0.0)
    except SystemExit as e:
        return tag, ln, mi, None, str(e)
    return tag, ln, mi, parse(t), t


def main():
    score = json.load(open(os.path.join(WORK, "score_final.json")))
    jobs = []
    for tag in ("p1", "p2"):
        for line in score[tag]:
            for i in range(len(line["measures"])):
                f = os.path.join(WORK, tag, "measures",
                                 f"{tag}_L{line['index']:02d}_m{i+1}.png")
                if os.path.exists(f):
                    jobs.append((tag, line["index"], i + 1, f))
    print(f"{len(jobs)} measures")
    out = {}
    raw = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for tag, ln, mi, parsed, txt in ex.map(one, jobs):
            out.setdefault(tag, {}).setdefault(ln, {})[mi] = parsed
            raw.setdefault(tag, {}).setdefault(ln, {})[mi] = txt
    json.dump(out, open(os.path.join(WORK, "simple_read.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(raw, open(os.path.join(WORK, "simple_read_raw.json"), "w"),
              indent=2, ensure_ascii=False)

    # compare with the first pass
    ok = bad = 0
    for tag in ("p1", "p2"):
        for line in score[tag]:
            for i, m in enumerate(line["measures"]):
                r = out.get(tag, {}).get(line["index"], {}).get(i + 1)
                if not r:
                    continue
                mine = [x["n"] for x in m["melody"]]
                ind = r["numbers"]
                core = list(mine)
                while core and core[-1] == 0:
                    core.pop()
                hit = any(ind[j:j + len(core)] == core
                          for j in range(len(ind) - len(core) + 1)) if core else False
                if hit:
                    ok += 1
                else:
                    bad += 1
                    print(f'{tag} L{line["index"]:02d}m{i+1}: '
                          f'mine=[{" ".join(map(str, mine))}] '
                          f'read2=[{" ".join(map(str, ind))}] '
                          f'dots=[{" ".join(r["dots"])}] '
                          f'ul=[{" ".join(map(str, r["underlines"]))}] '
                          f'after=[{r["after"]}] bass=[{" ".join(map(str, r["bass"]))}]')
    print(f"\nsecond read confirms {ok} measures, disagrees on {bad}")


if __name__ == "__main__":
    main()
