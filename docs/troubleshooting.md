# Troubleshooting

## Error messages

All errors start with `Comparison failed:` and exit with status 2.

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
| File or permission errors | Check the path. In PowerShell, put quotes around paths that contain spaces. |

Supported formats are those libsndfile reads, including WAV, FLAC and OGG
Vorbis. MP3 is not supported, so convert it to WAV or FLAC first.

## Results look wrong

**Many unmatched or extra events.**
Check that both files contain the same phrase. Use the range options to
trim count-ins, silence and anything outside the phrase.

**Every note reads about 100 or 1200 cents off.**
The render may be transposed (for example, a transposing instrument exported
at written pitch), or the tracker may have picked the wrong octave on a very
low or very high note. The tracker covers about 120–2400 Hz.

**Repeated notes are merged or flagged for review.**
Legato repeated notes at the same pitch can merge into one long note. Look at
the attacks in `comparison.json` and listen to that passage.

**Breath noise, ornaments or long reverb tails.**
These can split or extend notes. Trim the range, or treat duration values near
the ends of phrases with caution.

## Limitations

- **Solo only:** chords and overlapping notes are not supported.
- The tool compares **rendered audio**. It does not transcribe notation, export
  from Dorico or edit the score.
- Timing uses one fixed offset. There is no tempo warping.
- So far it has been checked on synthetic tones only. Validation on real Dorico
  exports is still pending.
