#!/usr/bin/env python3
"""Parse and cross-check the raw windowed readings of a jianpu manuscript."""
import json, os, re, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")

TOKEN = re.compile(r"\[([^\[\]]*?)\]")
OCT_OK = {"up2", "up1", "mid", "dn1", "dn2"}


def norm_oct(s):
    s = s.strip().lower()
    s = s.replace("up 2", "up2").replace("up 1", "up1").replace("dn 1", "dn1")
    s = s.replace("dn 2", "dn2")
    s = s.replace("+2", "up2").replace("+1", "up1").replace("++", "up2")
    s = s.replace("-2", "dn2").replace("-1", "dn1").replace("--", "dn2")
    s = s.replace("lower2", "dn2").replace("lower1", "dn1")
    s = s.replace("upper2", "up2").replace("upper1", "up1")
    s = s.replace("middle", "mid").replace("none", "mid")
    if s == "":
        s = "mid"
    if s in OCT_OK:
        return s
    if s.startswith("dn2") or s.startswith("-2"):
        return "dn2"
    if s.startswith("dn1"):
        return "dn1"
    if s.startswith("up2"):
        return "up2"
    if s.startswith("up1"):
        return "up1"
    return "mid"


def norm_beats(s):
    if isinstance(s, (int, float)):
        v = float(s)
    else:
        try:
            v = float(str(s).strip())
        except ValueError:
            return 1.0
    # snap to the allowed set
    allowed = [4, 3, 2, 1.5, 1, 0.75, 0.5, 0.375, 0.25, 0.125]
    return min(allowed, key=lambda a: abs(a - v))


def parse_line(line):
    """Return list of measures; each measure is a list of note dicts."""
    measures = []
    cur = []
    pos = 0
    # split the string into bracket tokens and separators
    for m in TOKEN.finditer(line):
        between = line[pos:m.start()]
        if "|" in between:
            if cur:
                measures.append(cur)
                cur = []
        pos = m.end()
        raw = m.group(1)
        parts = [p.strip() for p in re.split(r"[|/\s]+", raw) if p.strip()]
        if not parts:
            continue
        if len(parts) == 1:
            # maybe "0-6" or "6dn1" style
            s = parts[0]
            mm = re.match(r"^(\d)\s*([a-zA-Z0-9+]*)\s*([\d.]*)$", s)
            if not mm:
                continue
            parts = [mm.group(1), mm.group(2) or "mid", mm.group(3) or "1"]
        while len(parts) < 3:
            parts.append("1")
        d, o, b = parts[0], norm_oct(parts[1]), norm_beats(parts[2])
        if not d.isdigit():
            continue
        cur.append({"n": int(d), "oct": o, "beats": b})
    if cur:
        measures.append(cur)
    return measures


def extract(text):
    """Pull MELODY / BASS measure lists out of a raw model answer."""
    out = {}
    for field in ("MELODY", "BASS", "CHORDS", "NOTES"):
        m = re.search(rf"^{field}\s*:\s*(.*)$", text, re.M | re.I)
        if m:
            out[field] = m.group(1).strip()
    mel = out.get("MELODY", "")
    bas = out.get("BASS", "")
    return {"melody": parse_line(mel) if mel else [],
            "bass": parse_line(bas) if bas else [],
            "chords": out.get("CHORDS", ""),
            "notes": out.get("NOTES", "")}


def sig(measure):
    return " ".join(f"{n['n']}{n['oct'][:2]}{n['beats']}" for n in measure)


def load(tag):
    p = os.path.join(WORK, tag, f"{tag}_raw_answers.json")
    return json.load(open(p))


def analyse(tag):
    ans = load(tag)
    print(f"===== {tag} =====")
    for ln in sorted(ans, key=int):
        wins = ans[ln]
        print(f"-- line {ln} --")
        for wi in sorted(wins, key=int):
            sigs = []
            for s in sorted(wins[wi], key=int):
                d = extract(wins[wi][s])
                sigs.append([sig(m) for m in d["melody"]])
            # how many distinct readings of the whole window?
            uniq = Counter(" | ".join(x) for x in sigs)
            print(f"   w{wi}: {len(sigs)} samples, {len(uniq)} distinct")
            for k, c in uniq.most_common():
                print(f"      x{c}: {k[:150]}")
    return ans


if __name__ == "__main__":
    for tag in sys.argv[1:] or ["p1", "p2"]:
        analyse(tag)
