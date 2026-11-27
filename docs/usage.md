# Run a comparison

## Prepare the audio

1. Use a **solo** line. The pitch tracker expects one note at a time.
2. In Dorico, export the **same musical phrase** as a WAV file
   (PCM or floating-point).
3. Keep it short at first. A few bars is enough to check that notes are matched correctly.

The two files do not need to start at the same moment. The tool removes a
constant offset by lining up the first notes whose pitches match. If the
phrase sits at different places in the two files, select it with time ranges
(see below).

## Basic command

```powershell
.\.venv\Scripts\python.exe compare.py reference.wav dorico-export.wav
```

The first argument is always the **reference** (your recording) and the
second is the **render** (Dorico export). All differences are reported as
*render minus reference*.

On success the command prints one line, the path of the new Markdown report:

```text
outputs\comparison-ab12cd34\comparison.md
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `--reference-start SECONDS` | `0` | Start of the selected range in the reference file. |
| `--reference-end SECONDS` | end of file | End of the selected range in the reference file. |
| `--render-start SECONDS` | `0` | Start of the selected range in the render. |
| `--render-end SECONDS` | end of file | End of the selected range in the render. |
| `--limit N` | `12` | Number of rows shown in `comparison.md`. The JSON always has every row. |
| `--cache DIR` | `work/cache` | Folder for cached analysis. |
| `--output DIR` | `outputs` | Folder in which each run creates a new report folder. |

Times are in seconds and may be fractional, for example `--reference-start 2.5`.
Starts must be 0 or more, and each end must be later than its start.

### Example: different ranges in each file

The phrase runs from 1.2 s to 9 s in the recording and from 0 s to 8.4 s in the
export:

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav `
  --reference-start 1.2 --reference-end 9 --render-end 8.4
```

### Example: show more rows

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav --limit 40
```

## Output folders

Each run creates a **new** folder such as `outputs\comparison-ab12cd34\`
containing:

- `comparison.md`: a short summary table of the largest differences.
- `comparison.json`: every matched and unmatched event, plus the detected
  notes for both files.

Earlier reports are never overwritten.

## Caching

Analysing a file is the slow part, so the results are stored in `work/cache/`.
The cache key combines the **file's contents** and the **selected time range**:

- Running the same comparison again reuses both analyses. The report shows
  `Reference cache hit: True`.
- Re-exporting from Dorico changes the file's contents, so only the render is
  analysed again.
- Renaming or moving a file still uses the cache.
- Changing `--reference-start` or `--reference-end` means the reference is
  analysed again.

You can delete `work/cache/` at any time. It will be rebuilt on the next run.

## Using it with an assistant

For routine revisions, ask the assistant to run the command and read only
`comparison.md`. Ask it to open `comparison.json` only for detailed follow-up
questions. This keeps the conversation short.

## Exit status

`0` means a report was written. `2` means bad input, for example an invalid
range, a missing or unreadable file, silence, or no stable notes. In that case a
one-line `Comparison failed: …` message is printed and no report is written.
