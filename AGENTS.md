# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

Dorico Audio Compare is a single-file Python CLI (`compare.py`). It compares a
solo reference recording with an audio export from Dorico (WAV, FLAC or OGG)
and reports per-note pitch (cents), attack offset (ms), duration (ms) and
RMS-adjusted level (dB), plus a mir_eval note match score. It also writes
loudness-matched listening copies, optional per-event excerpts and, with
`--midi`, the reference's notes as MIDI. An optional event map (CSV or MIDI)
traces events to bar, beat, part and voice, and `compare.py check` scores the
detector on a render with known notes. Dependencies: NumPy, SciPy, soundfile, pyloudnorm, mir_eval and
pretty_midi; prefer these established libraries over new hand-written code.
Dorico is not required. Windows is the main target platform. Python 3.12 is
the minimum supported version.

## Commands

Windows (as in the README):

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.\.venv\Scripts\python.exe compare.py reference.wav dorico-export.wav --reference-end 8 --render-end 10
```

Tests (`pytest.ini` puts the repo root on `sys.path` and sets `testpaths = tests`):

```bash
python -m pytest                                              # whole suite
python -m pytest tests/test_compare.py::TestAlign             # one class
python -m pytest tests/test_compare.py::TestCompare::test_measurements  # one test
python -m pytest -k cache                                     # by keyword
```

Demo audio with known differences, for manual runs:

```bash
python tests/sample_audio.py samples
python compare.py samples/reference.wav samples/render.wav
```

Docs site (Zensical 0.1.3, which needs Python 3.11 or later; config in `zensical.toml`, pages in `docs/`):

```bash
pip install zensical==0.1.3
zensical build --clean --strict   # what CI runs; warnings fail the build
zensical serve                    # local preview on localhost:8000
```

There is no linter or formatter configured.

## Architecture

`compare.py` is a linear pipeline. Each input file goes through
`read_audio` → `track` → `segment`, all wrapped by `analyze`. Then the two
note lists go through `align` → `compare` → `markdown`, and `main` writes the
outputs.

- **`track`** is a YIN-style pitch tracker: 10 ms hop, 40 ms window, about
  120–2400 Hz. It returns frames `[time_s, pitch|None, confidence, rms]`.
  Times are absolute seconds in the file, not relative to the selected range.
- **`segment`** splits notes on unpitched frames or a jump of more than 65 cents.
  It bridges up to 3 audible unpitched frames (confidence > 0) at the same
  pitch, and splits stable notes at `reattacks` (RMS dip and rise of 6 dB or
  more at confidence 0.85 or more). Notes shorter than 55 ms are kept as
  `candidates`, not notes. Each `Note` has `start_reason` and `gaps`. Pitches
  are fractional MIDI numbers (A4 = 69).
- **`read_audio`** uses soundfile (libsndfile) and raises `ValueError` for
  unreadable files, so the CLI reports them as `Comparison failed`.
- **`analyze`** caches its result as JSON in `work/cache/`. The cache key is a
  SHA-256 of `"{CACHE_VERSION}:{start}:{end}"` plus the file's bytes. **Bump
  `CACHE_VERSION` whenever you change `read_audio`, `track`, `segment` or the
  cached data's shape.** Otherwise stale cache entries will be returned silently. Cache files
  are written with exclusive create (`"x"`), and a corrupt entry is recomputed
  rather than trusted.
- **`align`** is an edit-distance dynamic program. A pair is free within 35
  cents, rising to a cost of 1.75, plus up to 0.35 for a duration ratio.
  Pairs more than 300 cents apart are excluded. Skipping a note costs 1.
  Unmatched notes become `None` on one side.
- **`compare`** reports all deltas as *render minus reference*. Timing subtracts
  one constant offset, taken from the first aligned pair within 60 cents.
  Levels add the gain that matches the two clips' overall RMS. The `review`
  flag is heuristic: a neighbouring note at the same pitch, 60 cents or more,
  or confidence below 0.85. `note_scores` adds mir_eval precision, recall and
  F1 (onset ±50 ms, pitch ±50 cents, then also offsets within 20%) after
  removing the same constant offset.
- **`read_event_map`** reads `--event-map` (CSV with `time_s` and `pitch`,
  optional `duration_s`, `bar`, `beat`, `part`, `voice`; or MIDI via
  pretty_midi). **`match_written`** pairs render notes with written events
  using `mir_eval.transcription.match_notes` (onset ±100 ms, pitch ±50 cents,
  no offsets). **`trace`** attaches `written`/`written_status` to each row,
  searches for written-but-undetected render notes between neighbouring
  render detections and inserts `undetected written event` rows.
  **`check_detector`** reports missed, merged, extra, split and boundary
  (onset > 30 ms or end > 100 ms) issues. `compare.py check RENDER EVENTS`
  (`check_main`) runs it without a reference.
- **`flag_pitches`** adds `pitch_flags` (octave_leap, octave_counterpart,
  octave_written, instrument_range, tracker_limit) with evidence. It only
  flags rows; it never removes notes. `--instrument-range LOW HIGH` sets the range.
- **`write_midi`** writes every note unless `--midi-min-confidence` or
  `--midi-skip-out-of-range` is given, and returns the excluded notes for the
  report (`midi_selection` checks them before the output folder is made).
- Every event row has an `id`, both sides' `*_s`, `*_end_s`, `*_pitch`,
  `*_confidence` and `*_note` index, and `reasons`.
- **`write_excerpts`** (with `--excerpts`) writes `excerpts/event-NNN-*.wav`
  for the flagged events that `selected_flags` picks for the report, using
  `excerpt_windows` (previous to next matched pair, ±0.25 s) and the
  `level_match` gain.
- **`listening_copies`** writes `reference-clip.wav` and
  `render-level-matched.wav` (32-bit float). The gain comes from pyloudnorm LUFS,
  falling back to the RMS gain for clips under 0.4 s or near silence.
  **`write_midi`** (with `--midi`) writes `reference-notes.mid` via pretty_midi,
  with times relative to the range start and pitches rounded to semitones.
- **`main`** creates a new `outputs/comparison-*/` folder per run (`mkdtemp`)
  containing `comparison.md` (top `--limit` rows by largest difference, then
  the flagged events in musical order and the detector check),
  `comparison.json` (every event plus the detected notes) and the optional
  audio and MIDI files above. It prints the `.md`
  path. On invalid input it exits with status 2 and prints
  `Comparison failed: …`. `compare.py check` writes
  `outputs/detector-check-*/detector-check.{md,json}` and fails with
  `Detector check failed: …`.

## Conventions and constraints

- **Input audio and Dorico projects are read-only.** Never write to the user's
  audio files or `.dorico` projects. Every output is a new file. Tests assert inputs are byte-for-byte unchanged.
- Recordings, Dorico projects, caches, reports and samples are git-ignored
  (`*.wav`, `*.ogg`, `*.flac`, `*.dorico`, `/work/`, `/outputs/`, `/samples/`,
  `/site/`). Do not commit them. Tests generate their audio at run time with
  `tests/sample_audio.py`.
- When reviewing results, read `comparison.md` first. Open `comparison.json`
  only when the detail is needed, because it is much larger.
- The numeric thresholds above are also documented in `docs/how-it-works.md`,
  `docs/report.md`, `docs/troubleshooting.md`, `docs/testing.md`, `docs/usage.md`
and `docs/validation.md`. Update
  those pages when you change a threshold.
- `tests/sample_audio.py` defines `REFERENCE_NOTES`, `RENDER_NOTES` and
  `RENDER_OFFSET_S`, which the end-to-end tests use as expected values. Timing
  assertions allow about ±10 ms because of the 10 ms hop.
- CI: `.github/workflows/tests.yml` runs pytest on Windows and Ubuntu with
  Python 3.12 and 3.14. `.github/workflows/docs.yml` builds the docs on every
  PR and deploys to GitHub Pages (https://andyw98.github.io/music-ai/) on
  pushes to `main`.
- The Sarabande case study in [the report guide](docs/report.md) describes the
  real-audio check and its remaining limitations.
