#!/usr/bin/env python3
"""
Re-transcribe every line from the ruling-dot-free images.

The printed dotted ruling was corrupting the readings: it sits between the
digits, and the vision model was reporting it as octave dots and even as digits
that do not exist in jianpu. With it removed the same prompt returns stable,
self-consistent answers, so every line is read again measure by measure, several
times, and the samples are voted.
"""
import json, os, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vision import ask

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

PROMPT = """This is ONE line of handwritten Chinese jianpu (numbered notation). The printed ruling dots of the paper have been removed, so only pen strokes remain.

Structure: an upper row of numbers (the melody) and a lower row of large numbers (one per measure). Vertical bar lines separate measures.

Read it measure by measure, strictly left to right.

Answer in exactly this format, one line per measure, nothing else:
MEASURES: <total number of measures>
M1: NUMBERS <every digit of measure 1, separated by spaces> | UNDERLINES <for each digit, how many short horizontal lines are drawn under it: 0, 1 or 2> | DASHES <how many dash "-" symbols follow the last digit, or 0> | BASS <the large digit written below measure 1>
M2: ...

Rules:
- NUMBERS and UNDERLINES must have the same number of entries.
- A written "16" is TWO digits: 1 then 6. Never merge digits.
- A digit with no underline is a quarter note; one underline makes it an eighth; two make it a sixteenth.
- A dash after the last digit means the last note is held for one extra beat; count them.
- Read every digit. Do not skip and do not invent.
"""


def parse(text):
    n = re.search(r"MEASURES\s*:\s*(\d+)", text)
    total = int(n.group(1)) if n else None
    measures = []
    for m in re.finditer(r"^M(\d+)\s*:\s*(.*)$", text, re.M):
        idx = int(m.group(1))
        rest = m.group(2)
        parts = {}
        for key in ("NUMBERS", "UNDERLINES", "DASHES", "BASS"):
            mm = re.search(rf"{key}\s*([^|]*?)(?=\||$)", rest, re.I)
            parts[key] = mm.group(1).strip() if mm else ""
        nums = [int(c) for c in re.findall(r"\d", parts["NUMBERS"])]
        uls = [int(c) for c in re.findall(r"\d", parts["UNDERLINES"])]
        dsh = re.findall(r"\d+", parts["DASHES"])
        dashes = int(dsh[0]) if dsh else 0
        bass = [int(c) for c in re.findall(r"\d", parts["BASS"])]
        measures.append({"idx": idx, "numbers": nums, "underlines": uls,
                         "dashes": dashes, "bass": bass})
    return {"total": total, "measures": measures}


def job(a):
    tag, ln, png, k = a
    try:
        t, fr, u, r = ask(png, PROMPT, thinking="disabled", max_tokens=900,
                          temperature=0.0 if k == 0 else 0.85)
    except SystemExit as e:
        return tag, ln, k, None, str(e)
    return tag, ln, k, parse(t), t


def main(samples=5, workers=6):
    meta = json.load(open(os.path.join(WORK, "clean_lines.json")))
    jobs = []
    for tag in ("p1", "p2"):
        for ln_s, info in meta[tag].items():
            for k in range(samples):
                jobs.append((tag, int(ln_s), info["file"], k))
    print(f"{len(jobs)} calls over {len(jobs)//samples} lines")
    out, raw = {}, {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for tag, ln, k, parsed, txt in ex.map(job, jobs):
            out.setdefault(tag, {}).setdefault(ln, {})[k] = parsed
            raw.setdefault(tag, {}).setdefault(ln, {})[k] = txt
            done += 1
            if done % 20 == 0:
                print(f"  {done}/{len(jobs)}")
    json.dump(out, open(os.path.join(WORK, "recline.json"), "w"),
              indent=2, ensure_ascii=False)
    json.dump(raw, open(os.path.join(WORK, "recline_raw.json"), "w"),
              indent=2, ensure_ascii=False)

    for tag in ("p1", "p2"):
        for ln in sorted(out.get(tag, {})):
            counts = Counter()
            for k, p in out[tag][ln].items():
                if p:
                    counts[(p["total"], len(p["measures"]))] += 1
            print(f"  {tag} L{ln:02d}: (declared total, measures parsed) "
                  f"{counts.most_common(3)}")


if __name__ == "__main__":
    main()
