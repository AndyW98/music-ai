# Validate the detector

The note detector is tested on synthetic tones. A real Dorico export adds
sample attacks, release tails, vibrato and reverb. This page describes a short
test score to render in Dorico, so you can measure what the detector misses on
your own instrument and sounds. Repeat it whenever the detector or your
playback template changes.

Keep the test project, its exports and the reports on your own computer. Do
not commit them: `*.dorico`, `*.wav`, `*.flac`, `*.ogg`, `outputs/` and
`samples/` are git-ignored.

## 1. Write the test score

Make a new Dorico project with one solo instrument, for example a flute. Use
4/4 at crotchet = 120, so a beat is 0.5 s. Start with one empty bar so the
export has a lead-in, then write four bars:

| Bar | Content | What it tests |
|---|---|---|
| 1 | Four detached crotchets on the same pitch (A4), each played a little short (staccato or tenuto) | Repeated pitches separated by short gaps |
| 2 | Four slurred quavers (C5 D5 E5 F5), a crotchet rest, then a crotchet G5 | Slurs, where one note runs into the next, and a rest |
| 3 | Two slurred crotchets on the same pitch (E5 E5), then D5 *pp* and C5 *ppp* | A legato repeated note, and quiet notes |
| 4 | A minim A4, then a minim rest | A long note and its release |

Choose pitches inside your instrument's range and inside the detector's range
(about 120–2400 Hz). Leave the rest of the playback settings at their
defaults, or note what you changed.

## 2. Export the audio and the known notes

1. Export the audio of the whole flow as a WAV (**File → Export → Audio**).
2. Export the same flow as MIDI (**File → Export → MIDI**). This is the
   event map of known notes.
3. Write down the Dorico version, the playback template and the sound used.

Both exports start at the beginning of the flow, so their times line up. If
the WAV turns out to start later or earlier, pass the difference with
`--event-map-offset`.

Instead of MIDI, you can write the known notes as a CSV with `time_s`,
`pitch`, `duration_s`, `bar`, `beat`, `part` and `voice` columns. See
[Locate events in the score](usage.md#locate-events-in-the-score). With the
empty first bar, the written notes start in bar 2 of the MIDI file. A CSV lets
you number the bars as you wrote them.

## 3. Run the check

```powershell
.\.venv\Scripts\python.exe compare.py check test-score.wav test-score.mid
```

The command prints the path of a new `detector-check.md`. It gives:

- **Precision, recall and F1** of the detected notes against the written
  notes (attack within 100 ms, pitch within 50 cents).
- **False negatives:** `missed` written notes, and `merged` ones that run into
  the previous detection.
- **False positives:** `extra` detections with no written note, and `split`
  ones that break a written note in two.
- **Boundary errors:** matched notes whose attack is more than 30 ms, or whose
  end is more than 100 ms, from the written note. The median attack and end
  differences show any constant offset from the samples' attack and release.

`detector-check.json` has every detected note and written event for a closer
look.

## What to expect

`tests/sample_audio.py` has a synthetic version of this score
(`VALIDATION_SCORE`). Its slurred repeated E5 has a brief level dip where it
is played again. Its bar 4 minim has a 60 ms breath-like noise dropout, a
known cause of false splits in recordings. The current detector finds every
written note exactly once, including the *ppp* note. The earlier detector,
which split notes only at unpitched frames and pitch jumps, made one error of
each kind on the same file:

| Detector | Matched | Merged | Split | Boundary errors | F1 |
|---|--:|--:|--:|--:|--:|
| Earlier (unpitched frame or 65-cent jump only) | 13 of 14 | 1 (bar 3 beat 2) | 1 (bar 4 beat 1) | 2 | 0.93 |
| Current (with gap bridging and reattacks) | 14 of 14 | 0 | 0 | 0 | 1.00 |

Try it with:

```powershell
.\.venv\Scripts\python.exe tests\sample_audio.py samples
.\.venv\Scripts\python.exe compare.py check samples\validation-render.wav samples\validation-events.csv
```

A real render can differ: reverb can join detached notes, a soft attack can
start late, and vibrato or breath can split a long note. Use the issues to
decide which detector improvement matters most, and keep the report next to
the export it came from.
