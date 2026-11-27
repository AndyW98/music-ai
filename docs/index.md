# Dorico Audio Compare

Dorico Audio Compare is a small command-line tool. It compares a **solo
reference recording** with a **WAV exported from Dorico** and shows how the
render differs, note by note:

- **Pitch** in cents
- **Attack timing** in milliseconds, after lining up the first matching note
- **Duration** in milliseconds
- **Level** in dB, after matching the overall loudness of the two clips

It runs locally with Python, NumPy and SciPy. It does **not** need Dorico,
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

- [Install on Windows](install.md) explains how to set up Python and the dependencies.
- [Run a comparison](usage.md) covers every command-line option, time ranges and caching.
- [Read the report](report.md) explains each column and JSON field.
- [How it works](how-it-works.md) describes pitch tracking, note matching and the measurements.
- [Troubleshooting](troubleshooting.md) covers common errors and limitations.

!!! note "Status"
    The tool has passed synthetic tests with generated tones. It has not yet
    been validated on real Dorico exports, so treat the results as a guide
    for listening rather than a final verdict.
