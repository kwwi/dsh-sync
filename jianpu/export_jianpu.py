#!/usr/bin/env python3
"""Write the recognised jianpu back out in conventional numbered notation."""
import json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
OUT = os.path.join(BASE, "out")

DOT = {"mid": "", "up1": "\u0307", "up2": "\u0308", "dn1": ".", "dn2": ".."}


def num(x):
    if x["n"] == 0:
        return "0"
    d = {0: "", "mid": "", "up1": "\u2191", "up2": "\u2191\u2191",
         "dn1": "\u2193", "dn2": "\u2193\u2193"}.get(x["oct"], "")
    return f"{x['n']}{d}"


def beats_mark(b):
    table = {4.0: "- - -", 3.0: "- -", 2.0: "-", 1.5: "\u00b7", 1.0: "",
             0.75: "\u00b7", 0.5: "_", 0.375: "_", 0.25: "__", 0.125: "___"}
    return table.get(round(b, 4), f"[{b}]")


def underline(x):
    """Underline marker drawn after the number in this plain-text rendering."""
    b = round(x["beats"], 4)
    if b in (0.5,):
        return ""
    if b in (0.25,):
        return ""
    if b in (0.125,):
        return ""
    return ""


def render_line(line):
    mel_parts, bas_parts = [], []
    for m in line["measures"]:
        toks = []
        for x in m["melody"]:
            t = num(x)
            mk = beats_mark(x["beats"])
            if x["beats"] in (0.5, 0.25, 0.125):
                # underlines are drawn beneath; show the beam count in brackets
                n = {0.5: 1, 0.25: 2, 0.125: 3}[round(x["beats"], 4)]
                t = f"{t}/{n}"
            elif mk:
                t = f"{t} {mk}"
            toks.append(t)
        mel_parts.append(" ".join(toks))
        b = " ".join(f"{num(x)} {beats_mark(x['beats'])}".strip()
                     for x in m["bass"])
        bas_parts.append(b or "-")
    return mel_parts, bas_parts


def main():
    d = json.load(open(os.path.join(WORK, "score_final.json")))
    os.makedirs(OUT, exist_ok=True)
    L = []
    L.append("Jianpu transcription recovered from the handwritten photographs")
    L.append("Title : Chapter 1 - What Is")
    L.append("Key   : 1 = bB  (B flat major)")
    L.append("Metre : 4/4")
    L.append("")
    L.append("Notation key:")
    L.append("  n        scale degree  (1..7, 0 = rest), read against 1 = bB")
    L.append("  n/1      one underline  = eighth note")
    L.append("  n/2      two underlines = sixteenth note")
    L.append("  n/3      three underlines = thirty-second note")
    L.append("  n -      a dash after the number adds one beat (hold)")
    L.append("  n .      a dot after the number makes it dotted (x1.5)")
    L.append("  ^n / vn  octave dot above / below the number")
    L.append("")
    L.append("Each line of the manuscript is written as: MELODY row, then BASS row.")
    L.append("")
    for tag, title in (("p1", "PAGE 1 (sbd1.jpg)"), ("p2", "PAGE 2 (sbd2.jpg)")):
        L.append("=" * 72)
        L.append(title)
        L.append("=" * 72)
        for line in d[tag]:
            mel, bas = render_line(line)
            L.append("")
            L.append(f"Line {line['index']}")
            for i, (a, b) in enumerate(zip(mel, bas), 1):
                L.append(f"  m{i}: M | {a}")
                L.append(f"       B | {b}")
    txt = "\n".join(L) + "\n"
    p = os.path.join(OUT, "jianpu_transcription.txt")
    open(p, "w").write(txt)
    print("wrote", p)
    print(txt[:1500])


if __name__ == "__main__":
    main()
