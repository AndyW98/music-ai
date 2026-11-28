# Dorico Audio Compare

Compare a solo reference recording with an audio export from Dorico. The tool
runs locally and needs Python 3.12 or later. It can run on a machine without
Dorico, and it never opens or edits a score.

Full documentation: <https://andyw98.github.io/music-ai/>. New users should
start with the [first-time setup guide](docs/getting-started.md).

## Windows setup

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Use WAV (PCM or floating point), FLAC or OGG files. Export the same musical phrase from
Dorico, or pass separate time ranges for the two recordings.

```powershell
.\.venv\Scripts\python.exe compare.py reference.wav dorico-export.wav --reference-end 8 --render-end 10
```

Each run prints the path to a new Markdown report under `outputs/` and saves
all note matches and unmatched events as JSON alongside it. The same folder
gets `reference-clip.wav` and `render-level-matched.wav`, loudness-matched
copies for A/B listening (skip them with `--no-listening-copy`). Add `--midi`
to also write the reference's detected notes as `reference-notes.mid`, which
can be imported into Dorico as a first draft. Add `--event-map` with a CSV
or a Dorico MIDI export of the render's notes to locate each event by bar,
beat, part and voice, and `--excerpts` to write short level-matched clips
of each flagged event. `compare.py check render.wav notes.mid` measures what
the note detector misses on a render with known notes. `--instrument-range C4 D7`
flags notes the instrument cannot play, and suspected octave errors are flagged
automatically. Flagged notes are never removed. `--align phrase` follows
local tempo changes and repeats. The report explains the note match score by
tuning, pitch, timing and drift. With `--midi`, `--midi-tempo`, `--midi-meter`
and `--midi-quantize` set the notation handoff, recorded with every note's
performed time in `notation-handoff.json`. For a spoken
request through Codex, ask it to run the command against the two WAVs and
read the Markdown report. The full JSON is available for follow-up questions.
The cache in `work/cache/` stores the full pitch and RMS tracks keyed by
audio content and selected time range.

### Try it on sample audio

```powershell
.\.venv\Scripts\python.exe tests\sample_audio.py samples
.\.venv\Scripts\python.exe compare.py samples\reference.wav samples\render.wav
```

The render is altered by about +25 and −18 cents, +40 and −30 ms attack, and
+50 and −40 ms duration on notes 2 and 3. The script also writes
`validation-render.wav` and `validation-events.csv` for `compare.py check`.

## Reading the report

- Positive timing values mean the render is late after aligning the first
  pitch-matched attack. The matching step pairs events without stretching audio.
- Pitch differences are in cents. Note pitches in the JSON are fractional MIDI
  numbers relative to A440. Historical temperaments can produce real cents
  differences without implying an incorrect note.
- Level differences use the RMS gain needed to match the selected clips. Peak
  and RMS values before adjustment are also reported. The listening copy is
  matched by integrated loudness (LUFS) instead, and the report states the gain
  used. Audio files stay intact.
- The note match F1 score (from mir_eval) summarises how many notes agree
  within 50 ms and 50 cents. Use it to check that a new draft is better overall
  than the previous one.
- The pitch tracker assumes one sounding note at a time. Legato repeated
  pitches, breath noise, ornaments, and tails can affect event boundaries.
  Review flags are heuristic. The report is intended to guide listening and
  score review.

This version compares rendered audio. It does not transcribe editable notation,
export from Dorico, or invoke Maestro. Use a short phrase first.

## Tests

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

The tests generate synthetic sample audio and cover every function plus the
command line. The `Tests` workflow runs them on Windows and Linux with Python
3.12 and 3.14. See [docs/testing.md](docs/testing.md).

## Dependencies

- Runtime: [NumPy](https://github.com/numpy/numpy), [SciPy](https://github.com/scipy/scipy),
  [soundfile](https://github.com/bastibe/python-soundfile) (audio files),
  [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) (loudness matching),
  [mir_eval](https://github.com/mir-evaluation/mir_eval) (note match scores) and
  [pretty_midi](https://github.com/craffel/pretty-midi) (MIDI export)
- [pytest](https://github.com/pytest-dev/pytest) for tests
- [Zensical](https://github.com/zensical/zensical) for the documentation site
- Optional: [uv](https://github.com/astral-sh/uv)

Full list with versions: [docs/dependencies.md](docs/dependencies.md).

## Documentation site

The `docs/` folder is a [Zensical](https://zensical.org) site. The
`Documentation` workflow builds it on every pull request and publishes it to
GitHub Pages on pushes to `main`. GitHub Pages must be set to
**Settings → Pages → Source: GitHub Actions** once. To preview it locally (Zensical needs Python 3.11 or later):

```powershell
uv pip install --python .venv\Scripts\python.exe zensical==0.1.3
.\.venv\Scripts\zensical.exe serve
```
