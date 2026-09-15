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
                     metadata, instrument, layout, roman, duration, tie, bar)

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
    if len(t) >= 2 and t[0] in "b#" and t[1].isalpha():
        # accidental written first: 'bB' -> 'Bb', '#F' -> 'F#'
        t = t[1].upper() + t[0]
    else:
        t = t[0].upper() + t[1:]
        if len(t) == 2 and t[1] not in "b#":
            t = t[0] + t[1].lower()
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


def decompose_duration(q):
    """Split a quarterLength into standard note values (longest first)."""
    VALUES = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125, 0.0625]
    out = []
    rest = round(q, 6)
    guard = 0
    while rest > 1e-6 and guard < 12:
        pick = None
        for v in VALUES:
            if v <= rest + 1e-9:
                pick = v
                break
        if pick is None:
            break
        out.append(pick)
        rest = round(rest - pick, 6)
        guard += 1
    if rest > 1e-6:
        out.append(round(rest, 6))
    return out or [q]


def append_note(container, nm, q, tie_chain):
    """Append a note, splitting it into tied standard values when necessary."""
    parts = decompose_duration(q)
    prev = None
    for i, p in enumerate(parts):
        nt = note.Note(nm, quarterLength=p)
        if i > 0 or tie_chain:
            nt.tie = tie.Tie("continue" if i < len(parts) - 1 else "stop")
        elif len(parts) > 1:
            nt.tie = tie.Tie("start")
        container.append(nt)
        prev = nt
    return prev


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
    mel.partName = "Melody"
    mel.partAbbreviation = ""
    mel.insert(0, clef.TrebleClef())
    mel.insert(0, key.Key(key_name))
    mel.insert(0, meter.TimeSignature(ts))
    mel.insert(0, tempo.MetronomeMark(number=tempo_val))

    bass = stream.Part(id="bass")
    bass.partName = "Bass"
    bass.partAbbreviation = ""
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
                if nm is None:
                    mm.append(nt)
                else:
                    # split unconventional durations into tied standard values
                    append_note(mm, nm, nt.quarterLength, False)
                total += nt.quarterLength
            # pad a short measure to the metre
            if 0 < total < bar_len - 1e-6:
                mm.append(note.Rest(quarterLength=bar_len - total))
            mel.append(mm)

            bm = stream.Measure()
            btotal = 0.0
            for tok in meas.get("bass", []):
                nt, nm = note_or_rest(tok, tonic_pc, bass_base_octave, bass_shift, key_name)
                if nm is None:
                    bm.append(nt)
                else:
                    append_note(bm, nm, nt.quarterLength, False)
                btotal += nt.quarterLength
            if 0 < btotal < bar_len - 1e-6:
                bm.append(note.Rest(quarterLength=bar_len - btotal))
            bass.append(bm)

    # close the piece with a final double barline
    for part in (mel, bass):
        ms = part.getElementsByClass(stream.Measure)
        if len(ms):
            try:
                ms[-1].rightBarline = bar.Barline("final")
            except Exception:
                pass

    # a metronome mark only survives the MusicXML writer inside a measure
    mms = mel.getElementsByClass(stream.Measure)
    if len(mms):
        try:
            mms[0].insert(0, tempo.MetronomeMark(number=tempo_val))
        except Exception:
            pass

    # A flat that the key signature already carries must not be reprinted on
    # every note; music21 displays the accidental of the pitch object by
    # default, which would clutter a two-flat key with redundant signs.
    FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
    SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
    sig = key.Key(key_name).sharps
    if sig >= 0:
        keyed = {st: 1 for st in SHARP_ORDER[:sig]}
    else:
        keyed = {st: -1 for st in FLAT_ORDER[:-sig]}
    for part in (mel, bass):
        for nt in part.recurse().notes:
            acc = nt.pitch.accidental
            if acc is None:
                continue
            want = keyed.get(nt.pitch.step)
            acc.displayStatus = not (want is not None and want == acc.alter)

    sc.insert(0, mel)
    sc.insert(0, bass)
    # brace the two staves together as one piano system
    try:
        sg = layout.StaffGroup([mel, bass], name="Piano", abbreviation="",
                               symbol="brace", barTogether=True)
        sc.insert(0, sg)
    except Exception:
        pass

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
