#!/usr/bin/env python3
"""
Convert a transcribed jianpu score (JSON) into MusicXML and MIDI.

Score JSON shape
----------------
{
  "title": "...", "composer": "...",
  "key": "1=bB",            # jianpu key line -> major key
  "time": "4/4",
  "tempo": 88,
  "octaveShift": 0,          # extra octaves applied to the melody, if needed
  "bassOctaveShift": 0,
  "lines": [
     {"index": 1,
      "measures": [
         {"melody": [{"n":0,"oct":"mid","beats":0.5}, ...],
          "bass":   [{"n":6,"oct":"dn1","beats":4}],
          "chord":  "Bbmaj7"        # optional
         }, ... ]}, ... ]
}
"""
import json, sys, os
from music21 import (stream, note, chord, meter, key, tempo, clef, harmony,
                     metadata, instrument, layout, roman, duration)

# semitone offset of each scale degree above the tonic, for a major key
MAJOR_STEPS = {1: 0, 2: 2, 3: 4, 4: 5, 5: 7, 6: 9, 7: 11}
OCT_OFFSET = {"dn2": -2, "dn1": -1, "mid": 0, "up1": 1, "up2": 2}

PITCH_CLASS = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
               "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
               "A#": 10, "Bb": 10, "B": 11}

KEY_NAMES = {0: "C", 1: "C#", 2: "D", 3: "Eb", 4: "E", 5: "F", 6: "F#",
             7: "G", 8: "Ab", 9: "A", 10: "Bb", 11: "B"}

NAME_TO_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def parse_key(s):
    """'1=bB' / '1=Bb' / '1 = bB' -> ('Bb', 10)."""
    if not s:
        return "C", 0
    t = s.split("=")[-1].strip()
    t = t.replace("♭", "b").replace("♯", "#")
    if t.lower().startswith("b") and len(t) > 1:
        t = t[0].upper() + t[1:]      # 'bB' -> 'Bb'
    t = t[0].upper() + t[1:]          # 'bb' -> 'Bb'
    if len(t) == 2 and t[1] in "b#":
        t = t[0] + t[1]
    if t not in PITCH_CLASS:
        # tolerate odd spellings
        t = t.replace("B#", "C").replace("Cb", "B").replace("E#", "F").replace("Fb", "E")
    return t, PITCH_CLASS.get(t, 0)


def degree_to_midi(deg, octv, tonic_pc, base_octave=4, extra_shift=0):
    """jianpu degree -> MIDI number. Plain octave keeps the tonic in `base_octave`."""
    step = MAJOR_STEPS.get(deg)
    if step is None:
        return None
    midi = (base_octave + 1) * 12 + tonic_pc + step
    midi += 12 * OCT_OFFSET.get(octv, 0) + 12 * extra_shift
    return midi


def midi_to_name(m):
    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{names[m % 12]}{m // 12 - 1}"


def note_or_rest(tok, tonic_pc, base_octave, shift, key_name):
    beats = float(tok.get("beats", 1.0) or 1.0)
    if beats <= 0:
        beats = 0.25
    n = int(tok.get("n", 0))
    if n == 0:
        return note.Rest(quarterLength=beats), None
    m = degree_to_midi(n, tok.get("oct", "mid"), tonic_pc, base_octave, shift)
    nm = midi_to_name(m)
    nt = note.Note(nm, quarterLength=beats)
    return nt, nm


def chord_symbol(text, key_name):
    if not text:
        return None
    t = text.strip()
    if t.lower() in ("none", "无", "-", ""):
        return None
    try:
        return harmony.ChordSymbol(t)
    except Exception:
        pass
    try:
        return roman.RomanNumeral(t, key.Key(key_name))
    except Exception:
        return None


def build(score_json, out_xml, out_mid=None, base_octave=4, bass_base_octave=3):
    key_name, tonic_pc = parse_key(score_json.get("key", "1=C"))
    ts = score_json.get("time", "4/4")
    tempo_val = int(score_json.get("tempo", 84))
    mel_shift = int(score_json.get("octaveShift", 0))
    bass_shift = int(score_json.get("bassOctaveShift", 0))

    sc = stream.Score()
    md = metadata.Metadata()
    md.title = score_json.get("title", "简谱转五线谱")
    md.composer = score_json.get("composer", "")
    sc.insert(0, md)

    mel = stream.Part(id="melody")
    mel.partName = "旋律 Melody"
    mel.insert(0, instrument.Piano())
    mel.insert(0, clef.TrebleClef())
    mel.insert(0, key.Key(key_name))
    mel.insert(0, meter.TimeSignature(ts))
    mel.insert(0, tempo.MetronomeMark(number=tempo_val))

    bass = stream.Part(id="bass")
    bass.partName = "低音 Bass"
    bass.insert(0, instrument.Piano())
    bass.insert(0, clef.BassClef())
    bass.insert(0, key.Key(key_name))
    bass.insert(0, meter.TimeSignature(ts))

    ts_num, ts_den = (int(x) for x in ts.split("/"))
    bar_len = ts_num * (4.0 / ts_den)

    for line in score_json.get("lines", []):
        for meas in line.get("measures", []):
            mm = stream.Measure()
            sym = chord_symbol(meas.get("chord"), key_name)
            if sym is not None:
                mm.insert(0, sym)
            total = 0.0
            for tok in meas.get("melody", []):
                nt, nm = note_or_rest(tok, tonic_pc, base_octave, mel_shift, key_name)
                if not isinstance(nt, note.Rest):
                    props = {}
                    if tok.get("slur"):
                        props["slur"] = "start"
                    if tok.get("slur_end"):
                        props["slur"] = "stop"
                mm.append(nt)
                total += nt.quarterLength
            # pad a short measure to the metre
            if 0 < total < bar_len - 1e-6:
                mm.append(note.Rest(quarterLength=bar_len - total))
            mel.append(mm)

            bm = stream.Measure()
            btotal = 0.0
            for tok in meas.get("bass", []):
                nt, nm = note_or_rest(tok, tonic_pc, bass_base_octave, bass_shift, key_name)
                bm.append(nt)
                btotal += nt.quarterLength
            if 0 < btotal < bar_len - 1e-6:
                bm.append(note.Rest(quarterLength=bar_len - btotal))
            bass.append(bm)

    sc.insert(0, mel)
    sc.insert(0, bass)

    sc.write("musicxml", fp=out_xml)
    if out_mid:
        sc.write("midi", fp=out_mid)
    return sc, key_name


if __name__ == "__main__":
    src = sys.argv[1]
    xml = sys.argv[2]
    mid = sys.argv[3] if len(sys.argv) > 3 else None
    data = json.load(open(src))
    sc, kn = build(data, xml, mid)
    print(f"key={kn} parts={len(sc.parts)} xml={xml} midi={mid}")
