# Troubleshooting

## Error messages

All errors start with `Comparison failed:` (`Detector check failed:` for
`compare.py check`) and exit with status 2.

| Message | What to do |
|---|---|
| `Ranges require finite seconds with 0 <= start < end` | Check `--*-start` and `--*-end`. Each end must be after its start. |
| `Range starts outside <file>` | The start time is past the end of that file. |
| `Selected range is silent or shorter than 40 ms` | Pick a longer range, or check that the export is not silent. |
| `No stable solo notes detected in <file>` | The range has no notes the tracker can follow. See *Limitations*. |
| `Empty or invalid audio in <file>` | The file has no samples or contains invalid values. Export it again. |
| `Cannot read audio in <file>: …` | The file is not a format libsndfile can read (for example MP3, or a damaged file). Export as WAV or FLAC. |
| `--midi-program must be between 0 and 127` | Use a General MIDI program number from 0 to 127. |
| `--limit must be positive` | Use `--limit 1` or more. |
| `Event map <file> needs time_s and pitch columns` | The CSV's first line must name the columns. See [Locate events in the score](usage.md#locate-events-in-the-score). |
| `Event map <file> line N: …` | That line has an invalid time, pitch or duration. Times must be 0 or more, durations more than 0 and pitches 0–127 or a note name such as `C#5`. |
| `No note events in event map <file>` | The CSV has no rows, or the MIDI file has only drum tracks. |
| `Cannot read MIDI event map <file>: …` | The file is not a readable MIDI file. Export it from Dorico again. |
| `--event-map-offset must be a finite number of seconds` | Use a number such as `0.5` or `-0.25`. |
| `--instrument-range needs two pitches such as C4 D7` | Give the lowest and highest pitch as note names or MIDI numbers. |
| `--instrument-range LOW must be below HIGH` | Put the lowest pitch first. |
| `--midi-skip-out-of-range needs --instrument-range` | Add `--instrument-range`, or drop the option. |
| `--midi-min-confidence must be between 0 and 1` | Use a value such as `0.85`. |
| `--max-drift must be more than 0 seconds` | Use a value such as `0.5` or `2`. |
| `--midi-tempo must be more than 0` | Give the tempo in beats per minute. |
| `--midi-meter must look like 3/4, with a power of 2 below` | Use a time signature such as `4/4`, `3/4` or `6/8`. |
| `--midi-quantize must be a number of beats such as 0.25 or 1/3` | Give the grid in beats, as a decimal or a fraction. |
| `--midi-quantize needs --midi-tempo` | Add the tempo the grid is counted in. |
| `--midi filters excluded every note` | Lower `--midi-min-confidence`, or widen `--instrument-range`. |
| File or permission errors | Check the path. In PowerShell, put quotes around paths that contain spaces. |

Supported formats are those libsndfile reads, including WAV, FLAC and OGG
Vorbis. MP3 is not supported, so convert it to WAV or FLAC first.

## Results look wrong

**Many unmatched or extra events.**
Check that both files contain the same phrase. Use the range options to
trim count-ins, silence and anything outside the phrase. If the attack values
grow steadily or a repeat is paired with the wrong copy, try `--align phrase`.
If phrase alignment leaves the end of a long passage unmatched, raise
`--max-drift`.

**Every note reads about 100 or 1200 cents off.**
The render may be transposed (for example, a transposing instrument exported
at written pitch), or the tracker may have picked the wrong octave on a very
low or very high note. The tracker covers about 120–2400 Hz.

**Repeated notes are merged or flagged for review.**
A slurred repeated note is split only when its level dips by 6 dB or more
while the pitch stays clear. A very smooth reattack can still merge into one
long note. Look at each note's `start_reason` in `comparison.json` and
listen to that passage.

**A note an octave off is flagged.**
Check the `pitch_flags` evidence and listen. The tracker sometimes locks onto
the octave above or below, especially near its 120–2400 Hz limits. Pass
`--instrument-range` so notes the instrument cannot play are flagged as well.

**Breath noise, ornaments or long reverb tails.**
These can split or extend notes. Trim the range, or treat duration values near
the ends of phrases with caution.

**Every event shows `no mapped written event`.**
The map's times probably do not line up with the WAV. Compare the first
note's `time_s` with the first `render_s` in the report and pass the
difference with `--event-map-offset`. A MIDI file must cover the same passage
as the WAV.

**The bar numbers are off by one or more.**
Bars from a MIDI map count from the start of the MIDI file. Pickup bars and
passages that do not start at bar 1 shift them. Use a CSV with your own
`bar` column when the numbers matter.

## Limitations

- **Solo only:** chords and overlapping notes are not supported.
- The tool compares **rendered audio**. It does not transcribe notation, export
  from Dorico or edit the score.
- Timing uses one fixed offset unless you pass `--align phrase`, which follows
  local drift up to `--max-drift`. Audio is never stretched.
- The automated tests use synthetic tones only. Use
  [Validate the detector](validation.md) to measure it on a real Dorico export.
