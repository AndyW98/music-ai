# Dorico Audio Compare

Dorico Audio Compare is a small command-line tool. It compares a **solo
reference recording** with **audio exported from Dorico** (WAV, FLAC or OGG) and shows how the
render differs, note by note:

- **Pitch** in cents
- **Attack timing** in milliseconds, after lining up the first matching note
- **Duration** in milliseconds
- **Level** in dB, after matching the overall loudness of the two clips

It also scores how many notes match, writes loudness-matched copies for A/B
listening, and can export the recording's notes as MIDI for a first Dorico
draft.

It runs locally with Python and a few well-known audio libraries. It does **not** need Dorico,
and it never opens or edits a score. Your audio files are only read.

## Quick start (Windows)

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\python.exe compare.py reference.wav dorico-export.wav --reference-end 8 --render-end 10
```

The command prints the path to a new `comparison.md` report. A detailed
`comparison.json` is saved next to it.

## Where to go next

- **New here?** Start with the [first-time setup guide](getting-started.md).
- [Install on Windows](install.md) explains how to set up Python and the dependencies.
- [Run a comparison](usage.md) covers every command-line option, time ranges and caching.
- [Read the report](report.md) explains each column and JSON field.
- [How it works](how-it-works.md) describes pitch tracking, note matching and the measurements.
- [Troubleshooting](troubleshooting.md) covers common errors and limitations.
- [Validate the detector](validation.md) measures what the detector misses on a real Dorico export.
- [Testing](testing.md) explains how to run the unit tests.
- [Dependencies](dependencies.md) links to every project the tool relies on.

!!! note "Status"
    The tool passes its unit tests on synthetic tones. Use
    [Validate the detector](validation.md) to measure it on your own Dorico
    exports, and treat the results as a guide for listening rather than a
    final verdict.
