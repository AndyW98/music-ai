# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

Dorico Audio Compare is a single-file Python CLI (`compare.py`). It compares a
solo reference WAV with a WAV exported from Dorico and reports per-note pitch
(cents), attack offset (ms), duration (ms) and RMS-adjusted level (dB). It
uses only NumPy and SciPy. Dorico is not required. Windows is the main target
platform. Python 3.10 is the minimum supported version.

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
  It drops notes shorter than 55 ms. Pitches are fractional MIDI numbers
  (A4 = 69).
- **`analyze`** caches its result as JSON in `work/cache/`. The cache key is a
  SHA-256 of `"v1:{start}:{end}"` plus the file's bytes. **Bump the `v1`
  version tag whenever you change `track`, `segment` or the cached data's
  shape.** Otherwise stale cache entries will be returned silently. Cache files
  are written with exclusive create (`"x"`), and a corrupt entry is recomputed
  rather than trusted.
- **`align`** is an edit-distance dynamic program. A pair is free within 35
  cents, rising to a cost of 1.75, plus up to 0.35 for a duration ratio.
  Skipping a note costs 1. Unmatched notes become `None` on one side.
- **`compare`** reports all deltas as *render minus reference*. Timing subtracts
  one constant offset, taken from the first aligned pair within 60 cents.
  Levels add the gain that matches the two clips' overall RMS. The `review`
  flag is heuristic: a neighbouring note at the same pitch, 60 cents or more,
  or confidence below 0.85.
- **`main`** creates a new `outputs/comparison-*/` folder per run (`mkdtemp`)
  containing `comparison.md` (top `--limit` rows by largest difference) and
  `comparison.json` (every event plus the detected notes). It prints the `.md`
  path. On invalid input it exits with status 2 and prints
  `Comparison failed: …`.

## Conventions and constraints

- **Input audio and Dorico projects are read-only.** Never write to the user's
  WAV files or `.dorico` projects. Tests assert inputs are byte-for-byte unchanged.
- Recordings, Dorico projects, caches, reports and samples are git-ignored
  (`*.wav`, `*.ogg`, `*.dorico`, `/work/`, `/outputs/`, `/samples/`,
  `/site/`). Do not commit them. Tests generate their audio at run time with
  `tests/sample_audio.py`.
- When reviewing results, read `comparison.md` first. Open `comparison.json`
  only when the detail is needed, because it is much larger.
- The numeric thresholds above are also documented in `docs/how-it-works.md`,
  `docs/report.md`, `docs/troubleshooting.md` and `docs/testing.md`. Update
  those pages when you change a threshold.
- `tests/sample_audio.py` defines `REFERENCE_NOTES`, `RENDER_NOTES` and
  `RENDER_OFFSET_S`, which the end-to-end tests use as expected values. Timing
  assertions allow about ±10 ms because of the 10 ms hop.
- CI: `.github/workflows/tests.yml` runs pytest on Windows and Ubuntu with
  Python 3.10 and 3.13. `.github/workflows/docs.yml` builds the docs on every
  PR and deploys to GitHub Pages (https://andyw98.github.io/music-ai/) on
  pushes to `main`.
- Validation on real Dorico exports is still pending. So far, results have
  only been verified on synthetic tones.
