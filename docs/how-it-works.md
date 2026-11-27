# How it works

`compare.py` runs the same analysis on both files and then compares the two
note lists.

```mermaid
flowchart LR
  A[Audio file] --> B[read_audio]
  B --> C[track: pitch every 10 ms]
  C --> D[segment: frames into notes]
  D --> E[(cache)]
  E --> F[align reference and render notes]
  F --> G[compare: cents, ms, dB]
  G --> H[comparison.json and comparison.md]
  G --> I[listening copies and MIDI]
```

## 1. Reading audio

Files are read with [soundfile](https://github.com/bastibe/python-soundfile)
(libsndfile), so WAV in any PCM or float format, FLAC and OGG Vorbis all work.
Samples are scaled to about −1 to 1. Stereo is mixed to mono for pitch tracking. Peak and RMS are
measured on all channels within the selected range.

## 2. Pitch tracking

The tracker uses the **YIN** method. Every **10 ms** it examines a
**40 ms** window and looks for the repeating period of the waveform between
about **120 Hz and 2400 Hz**. Then:

- Frames quieter than 0.8% of the clip's peak are treated as silence.
- Frames with confidence below 0.70 are treated as unpitched.
- The period is refined between samples, so the estimate is finer than one sample.

## 3. Segmenting into notes

Consecutive pitched frames form a note. A note ends when a frame is unpitched,
or when the pitch moves more than **65 cents** away from the median of the
previous five frames. Notes shorter than **55 ms** are discarded. Each note's
pitch is the median of its frames, so vibrato averages out.

## 4. Caching

The analysis (frames and notes) is stored as JSON in the cache folder. The
file is named by a SHA-256 hash of the analysis version, the requested time
range and the audio file's bytes. See [Caching](usage.md#caching).

## 5. Matching notes

The two note lists are aligned with dynamic programming, much like an edit
distance:

- Pairing two notes is free if their pitches are within 35 cents. The cost
  then rises by 1 per 100 cents, up to 1.75. A difference in duration adds up
  to 0.35.
- A pair more than 300 cents apart is excluded. Leaving a note unmatched on either side costs 1.

The report describes detected events. A missed detection, an ornament, or a written
note error can all produce an unmatched event. Audio is never stretched.

## 6. Measuring

- **Offset:** the start difference of the first matched pair whose pitches
  are within 60 cents. It is subtracted from every attack difference.
- **Pitch:** `(render − reference) × 100` cents.
- **Duration:** the difference in note length, in ms.
- **Level:** `20·log10(render note RMS / reference note RMS)` plus the gain
  that matches the two clips' overall RMS.
- **Note match score:** [mir_eval](https://github.com/mir-evaluation/mir_eval)'s
  `transcription.precision_recall_f1_overlap`, with onsets within 50 ms and
  pitch within 50 cents after removing the offset. It is calculated a second
  time with note ends required within 20%.

## 7. Listening copies and MIDI

- [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) measures each clip's
  integrated loudness (ITU-R BS.1770). The render copy gets the gain that makes
  the two equal. Clips too short to measure (under 0.4 s) use the RMS gain instead.
- With `--midi`, [pretty_midi](https://github.com/craffel/pretty-midi) writes
  the reference's detected notes to a MIDI file. MIDI velocity is 100 for the
  loudest note, minus 2 per dB quieter, with a minimum of 20.
