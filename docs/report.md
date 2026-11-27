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

The table shows the `--limit` rows with the **largest differences first**.
Unmatched events always come first. Matched notes are ranked by whichever is
largest relative to these steps: 50 cents, 100 ms of attack, 100 ms of duration
or 6 dB.

| Column | Meaning |
|---|---|
| Reference s / Render s | Note start in each file, in seconds from the start of the file. |
| Pitch cents | Pitch difference. 100 cents is one semitone. |
| Attack ms | Attack difference after removing the constant offset. |
| Duration ms | Difference in note length. |
| Level dB | Note level difference after the overall RMS gain. |
| Status | `matched`, `unmatched reference event` or `extra render event`, plus `· review` when flagged. |

### The review flag

A matched note is marked `review` when any of these is true:

- A neighbouring note in either file has nearly the same pitch, within 50
  cents. With repeated notes, the pairing may have slipped by one note.
- The pitch difference is 60 cents or more. That is more likely a different
  note than an intonation difference.
- Tracker confidence for either note is below 0.85.

The flag is a heuristic hint to listen closely. It does not mean the note is
wrong.

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
  "reference_cache_hit": false,
  "reference": {"file": "ref.wav", "range": [0.0, 3.2], "peak": 0.68, "rms": 0.25, "notes": ["…"]},
  "render":    {"file": "render.wav", "range": [0.0, 3.4], "peak": 0.34, "rms": 0.13, "notes": ["…"]}
}
```

- `events` is in **musical order**, unlike the Markdown table. Unmatched
  events have `null` for the missing side and no measurement fields.
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
