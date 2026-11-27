# Dorico Audio Compare

Compare a solo reference recording with a WAV exported from Dorico. The tool
runs locally and needs Python 3.10 or later. It can run on a machine without
Dorico, and it never opens or edits a score.

## Windows setup

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Use PCM or floating-point WAV files. Export the same musical phrase from
Dorico, or pass separate time ranges for the two recordings.

```powershell
.\.venv\Scripts\python.exe compare.py reference.wav dorico-export.wav --reference-end 8 --render-end 10
```

Each run prints the path to a new Markdown report under `outputs/` and saves
all note matches and unmatched events as JSON alongside it. For a spoken
request through Codex, ask it to run the command against the two WAVs and
read the Markdown report. The full JSON is available for follow-up questions.
The cache in `work/cache/` stores the full pitch and RMS tracks keyed by
audio content and selected time range.

## Reading the report

- Positive timing values mean the render is late after aligning the first
  pitch-matched attack. The matching step pairs events without stretching audio.
- Pitch differences are in cents. Note pitches in the JSON are fractional MIDI
  numbers relative to A440. Historical temperaments can produce real cents
  differences without implying an incorrect note.
- Level differences use the RMS gain needed to match the selected clips. Peak
  and RMS values before adjustment are also reported. Audio files stay intact.
- The pitch tracker assumes one sounding note at a time. Legato repeated
  pitches, breath noise, ornaments, and tails can affect event boundaries.
  Review flags are heuristic. The report is intended to guide listening and
  score review.

This version compares rendered audio. It does not transcribe editable notation,
export from Dorico, or invoke Maestro. Use a short phrase first.
