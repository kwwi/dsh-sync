#!/usr/bin/env python3
"""Assemble the transcription into one score and render PDF + MIDI."""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jianpu2xml import build, parse_key, degree_to_midi, OCT_OFFSET, MAJOR_STEPS
import render as render_mod

BASE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(BASE, "work")
OUT = os.path.join(BASE, "out")

TITLE = "Chapter 1 - What Is"
COMPOSER = ""
KEY_LINE = "1=bB"
TIME = "4/4"
TEMPO = 84


def assemble(score_json):
    lines = []
    for tag in ("p1", "p2"):
        for line in score_json.get(tag, []):
            ms = []
            for m in line["measures"]:
                ms.append({"melody": m["melody"], "bass": m["bass"],
                           "chord": m.get("chord")})
            lines.append({"index": f"{tag}-{line['index']}", "measures": ms})
    return {"title": TITLE, "composer": COMPOSER, "key": KEY_LINE,
            "time": TIME, "tempo": TEMPO, "lines": lines}


def pitch_range(score_json, mel_base=4, bass_base=3):
    _, pc = parse_key(KEY_LINE)
    lo, hi = 999, -1
    for tag in ("p1", "p2"):
        for line in score_json.get(tag, []):
            for m in line["measures"]:
                for x in m["melody"]:
                    if x["n"]:
                        v = degree_to_midi(x["n"], x["oct"], pc, mel_base)
                        lo, hi = min(lo, v), max(hi, v)
    return lo, hi


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sj = json.load(open(os.path.join(WORK, "score_final.json")))
    spec = assemble(sj)
    json.dump(spec, open(os.path.join(WORK, "score_spec.json"), "w"),
              indent=2, ensure_ascii=False)

    lo, hi = pitch_range(sj)
    print(f"melody MIDI range: {lo}..{hi}")

    xml = os.path.join(OUT, "score.musicxml")
    mid = os.path.join(OUT, "score.mid")
    sc, kn = build(spec, xml, mid)
    print(f"MusicXML: {xml}\nMIDI: {mid}\nkey={kn}")

    pdf = os.path.join(OUT, "score.pdf")
    p, n = render_mod.render(xml, pdf)
    print(f"PDF: {p} ({n} pages)")
