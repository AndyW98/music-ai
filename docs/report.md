# Read the report

All differences are **render minus reference**:

- Positive pitch means the render is **sharp**.
- Positive attack means the render is **late**.
- Positive duration means the render note is **longer**.
- Positive level means the render note is **louder**.

## `comparison.md`

The header lists:

Reference cache hit
:   Whether the reference analysis came from the cache.

Render offset at first pitch-matched attack
:   The constant time shift between the files, in seconds. All attack values
    are measured after removing this shift.

Render gain for RMS comparison
:   The gain, in dB, that would make the render's overall RMS equal the
    reference's. Note levels are compared after applying it, so a quieter
    export does not make every note look quiet.

Reference / Render peak/RMS
:   The peak and RMS of each selected range before any adjustment, in full
    scale units (1.0 is the maximum).

Note match F1
:   The standard note-transcription score from
    [mir_eval](https://github.com/mir-evaluation/mir_eval), from 0 to 1. A
    render note counts as correct if its attack is within 50 ms and its pitch
    is within 50 cents of a reference note, after removing the constant
    offset. "With note ends" also requires the note to end within 20% of the
    reference note's length (at least 50 ms). Use it to compare successive
    drafts: higher is better.

Event map
:   Only with `--event-map`: the map file, its number of written events and
    the offset added to its times.

Listening copies
:   The two listening files and the gain applied to the render copy. The gain
    normally matches integrated loudness (LUFS, ITU-R BS.1770). For clips
    under 0.4 s or near silence, it falls back to the RMS gain above. A peak
    above 1.00 means the copy is louder than full scale, so lower the playback
    volume.

The table shows the `--limit` rows with the **largest differences first**.
Unmatched events always come first. Matched notes are ranked by whichever is
largest relative to these steps: 50 cents, 100 ms of attack, 100 ms of duration
or 6 dB.

| Column | Meaning |
|---|---|
| # | Event number, counting in musical order. The same number is used in the flagged-events section, the excerpt file names and the JSON `id`. |
| Reference s / Render s | Note start in each file, in seconds from the start of the file. |
| Reference note / Render note | The detected pitch on each side, as a note name and cents from it. `A4 +12¢` is A4 12 cents sharp. |
| Pitch cents | Pitch difference. 100 cents is one semitone. |
| Attack ms | Attack difference after removing the constant offset. |
| Duration ms | Difference in note length. |
| Level dB | Note level difference after the overall RMS gain. |
| Written | Only with an event map: the written event's bar, beat, part and voice, or `no mapped written event`. |
| Status | See below, plus `· review` when flagged. |

The status is one of:

`matched`
:   A reference note and a render note were paired.

`unmatched reference event`
:   The reference has a note with no paired render note. With an event map,
    the Written column says whether the note is **written but not detected
    in the render**, or whether there is **no mapped written event** at that
    point.

`extra render event`
:   The render has a note with no paired reference note.

`undetected written event`
:   Only with an event map: a written note that neither file's detection
    accounts for, for example the second of two slurred repeated notes.

### The review flag

A matched note is marked `review` when any of these is true:

- A neighbouring note in either file has nearly the same pitch, within 50
  cents. With repeated notes, the pairing may have slipped by one note.
- The pitch difference is 60 cents or more. That is more likely a different
  note than an intonation difference.
- Tracker confidence for either note is below 0.85.

With an event map, a matched note is also flagged when its render
detection matches no written event.

The flag is a heuristic hint to listen closely. It does not mean the note is
wrong. Each flagged event lists its reasons.

### Flagged events in musical order

After the table, the report lists the flagged events in musical order. These
are the unpaired and `review` events, up to `--limit` of them, chosen by the
same largest-difference ranking. For each it shows:

- the detected start and end, pitch and confidence on **both** sides, or
  `no detected render event` with the position where the render note was
  expected;
- with an event map, the written location and pitch, and where it came from
  (a CSV line number or a MIDI track and note number);
- why it was flagged;
- with `--excerpts`, links to the two clips, their time ranges in the source
  files and the gain applied to the render clip.

### Detector check

With an event map, the report ends with a check of the render's detected
notes against the written notes. A detected note is the written note when its
attack is within 100 ms and its pitch within 50 cents.

| Kind | Meaning |
|---|---|
| `missed` | A written note with no detection. A false negative. |
| `merged` | A written note that falls inside a detection already matched to another written note, for example a slurred repeated note. A false negative. |
| `extra` | A detection with no written note. A false positive. |
| `split` | A detection that starts inside a written note already matched, for example a note broken in two. A false positive. |
| `boundary` | A matched detection whose attack is more than 30 ms, or whose end is more than 100 ms, away from the written note. |

The summary also gives precision, recall, F1 and the median attack and end
differences. Sample libraries add attack and release time, so a constant
median difference is expected and is not a detector error.

## `comparison.json`

The JSON has the same information plus everything the Markdown leaves out.

```json
{
  "render_minus_reference_offset_s": 0.2,
  "render_gain_for_rms_match_db": 5.8,
  "events": [
    {
      "reference_s": 1.29, "render_s": 1.53, "status": "matched",
      "pitch_cents": 25.0, "onset_ms": 40.0, "duration_ms": 50.0,
      "relative_level_db": 1.9, "review": false
    }
  ],
  "note_match": {
    "onset_pitch": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
    "onset_pitch_offset": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
    "tolerances": {"onset_s": 0.05, "pitch_cents": 50.0, "offset_ratio": 0.2, "render_shift_s": 0.2}
  },
  "listening": {
    "files": ["reference-clip.wav", "render-level-matched.wav"], "method": "LUFS",
    "gain_db": 5.2, "reference_lufs": -11.6, "render_lufs": -16.7, "matched_peak": 0.62
  },
  "reference_cache_hit": false,
  "reference": {"file": "ref.wav", "range": [0.0, 3.2], "peak": 0.68, "rms": 0.25, "notes": ["…"]},
  "render":    {"file": "render.wav", "range": [0.0, 3.4], "peak": 0.34, "rms": 0.13, "notes": ["…"]}
}
```

- `events` is in **musical order**, unlike the Markdown table. Unmatched
  events have `null` for the missing side and no measurement fields.
- Each event has an `id` and, for both sides, `reference_s`/`render_s`,
  `*_end_s`, `*_pitch`, `*_confidence` and `*_note` (the index into that
  side's `notes` list). `reasons` explains the status or review flag.
- An unmatched reference event has `expected_render_s`, where its render
  note would be, estimated from the previous matched pair.
- `written` is the matching written event (with `time_s`, `end_s`, `pitch`,
  `bar`, `beat`, `part`, `voice` and `source`) or `null`. `written_status` is
  `mapped`, `no mapped written event` or `no event map`.
- With `--excerpts`, flagged events have an `excerpt` with the two files,
  their `range_s` in each source file, `render_gain_db` and `gain_method`.
- With an event map, `event_map` holds the written events and
  `detector_check` the check summary and its `issues`.
- `onset_ms` is `null` if no pitch-matched pair was found to align on.
- Each entry in `notes` has `start`, `end` (seconds), `pitch`, `confidence`
  (0 to 1) and `rms`. `pitch` is a fractional MIDI number relative to
  A440. For example, `69.25` is A4 25 cents sharp.

## Interpreting the numbers

- **Temperament:** if the render uses a historical temperament, some notes
  will show real cents differences that are intentional.
- **Timing** uses one fixed offset for the whole range. A gradual tempo
  difference shows up as attack values that drift steadily in one direction.
- **Level** compares RMS over each detected note. Reverb, room noise and
  sample release tails all affect it.


## Audio-to-score review workflow

Use this workflow with any piece or genre. The current pitch detector expects
one sounding note at a time, so use a solo performance or an isolated melody
or instrument part when the source has overlapping notes. Ensure the reference
and Dorico render contain the same musical passage.

1. Make an audio-only draft in a separate Dorico project. The optional MIDI
   export can supply initial note events for import.
2. Export the same short passage as a new WAV. Compare the two files and
   check the measured levels. Use the loudness-matched listening copies for
   A/B review.
3. Review ambiguous events in musical order in the JSON. Check the detected
   pitches and attacks against the audio and locate the notes in Dorico
   before treating an unmatched event as a written-note error.
4. Make a supported correction in a new project version. Export another WAV
   and rerun the same passage. Keep earlier drafts and reports for comparison.
5. Keep the raw F1 for comparison. Systematic tuning and tempo drift can
   suppress it. Separate pitch, timing, and level when deciding what to change.

### Example: Bach Sarabande

The opening (roughly 13 seconds) of Alex Murray's solo traverso recording was
compared with a Dorico WAV rendered from a separate audio-only draft. The
baseline run needed +31.7 dB for RMS matching and scored 0.09 F1. A rerun on
the loudness-matched copy needed only +0.3 dB more for RMS matching, with
the same F1. Comparing the original to itself gave 1.00 F1, a consistency
check on identical input.

The old alignment paired events over two octaves apart. Its pitch cost
was capped, so such a pair could be cheaper than two gaps. The current
alignment excludes pairs more than three semitones apart. That threshold
is a guardrail. It does not establish which nearby pairs are correct.

One reference event around 1.35 seconds was unmatched even though its
pitch was already in the draft notation. Use the report to locate the
passage, then check the detection, the render, and the written note before
changing the score.

[Recording: Alex Murray, CC BY-SA 2.0](https://commons.wikimedia.org/wiki/File:Bach_-_Partita_For_Solo_Flute_-_Traverso_-_3._Sarabande.ogg)

With that guardrail, the same excerpt produced 13 paired events, down from
16, with three implausible pairs left unmatched on both sides. The strict
note-match F1 stayed at 0.09.

This example verified the level correction. A report-driven score correction
followed by a fresh Dorico render remains to be validated.
