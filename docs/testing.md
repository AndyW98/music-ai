# Testing

The tests in `tests/` use **synthetic sample audio**: harmonic tones generated
by `tests/sample_audio.py`, with known pitch, timing and level changes. No
recordings are stored in the repository.

## Run the tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

The **Tests** GitHub workflow runs the same suite on every pull request, on
Windows and Linux, with Python 3.12 and 3.14.

## What is covered

| Area | Checks |
|---|---|
| `read_audio` | 8-bit, 16-bit, 32-bit integer and float WAV scaling; FLAC and OGG input; stereo shape; empty, NaN, infinite and unreadable audio rejected |
| `track` | Pure tones from 131 Hz to 1760 Hz within 2 cents; a quarter-tone-sharp harmonic tone; frame timing; quiet frames unpitched; silent and too-short ranges rejected |
| `segment` | Splitting on pitch changes and gaps; dropping notes under 55 ms; vibrato kept as one note; median and RMS values |
| `analyze` | Sample notes detected; OGG input; cache hit, renamed-copy hit, range, content and cache-version misses; corrupt cache recovery; input file unchanged; range clamping; stereo; all sample formats; no-notes error |
| `align` | Identical, extra, missing and substituted notes; empty render |
| `compare` | Offset, cents, attack, duration and RMS-adjusted level; unmatched and extra events; no-anchor case; every review-flag rule; mir_eval note match scores |
| `listening_copies` | LUFS match within 0.1 LU; clip covers the selected range; RMS fallback for short clips; float output; inputs unchanged |
| `write_midi` | Note times relative to the range start, rounded pitches, velocity from level, program number |
| `markdown` | Ordering by largest difference; `--limit`; header and missing values |
| Command line | Full run on the sample pair with expected results and output files; `--midi` and `--no-listening-copy`; cache reuse and new folder per run; custom cache, output and limit; every argument and unreadable-file error exits with status 2; `--help` |

## Sample audio

`tests/sample_audio.py` doubles as a demo generator:

```powershell
.\.venv\Scripts\python.exe tests\sample_audio.py samples
```

It writes `samples\reference.wav` and `samples\render.wav`. The `samples/`
folder and all `*.wav` files are git-ignored.

!!! note
    Passing tests show the analysis is correct on clean synthetic tones.
    Real instruments and Dorico sample libraries add vibrato, noise and
    reverb, so validation on real exports is still pending.
