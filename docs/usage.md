# Run a comparison

## Prepare the audio

1. Use a **solo** line. The pitch tracker expects one note at a time.
2. In Dorico, export the **same musical phrase** as a WAV or FLAC file.
   OGG Vorbis also works, which suits recordings from Wikimedia Commons. MP3 is not supported.
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
| `--no-listening-copy` | off | Skip writing the two listening WAVs. |
| `--excerpts` | off | Write short level-matched clips for each flagged event shown in the report. See [Listen to flagged events](#listen-to-flagged-events). |
| `--event-map FILE` | none | A CSV or MIDI file of the render's written notes. Events are then located by bar, beat, part and voice. See [Locate events in the score](#locate-events-in-the-score). |
| `--event-map-offset SECONDS` | `0` | Added to every time in the event map, for example when the WAV starts later than the map. |
| `--midi` | off | Also write the reference's detected notes as `reference-notes.mid`. |
| `--midi-program N` | `73` (Flute) | General MIDI instrument for `--midi`, 0–127. |
| `--midi-min-confidence C` | none | Leave notes with tracker confidence below `C` (0–1) out of the MIDI file. |
| `--midi-skip-out-of-range` | off | Leave notes outside `--instrument-range` out of the MIDI file. |
| `--align sequence\|phrase` | `sequence` | How notes are paired. `phrase` follows local tempo changes and repeats. See [Follow tempo changes](#follow-tempo-changes). |
| `--max-drift SECONDS` | `1` | The largest local drift `--align phrase` follows, from the overall offset. |
| `--midi-tempo BPM` | none | Tempo written into the MIDI file. A beat is the `--midi-meter`'s lower note. |
| `--midi-meter N/D` | none | Time signature written into the MIDI file, for example `3/4` or `6/8`. |
| `--midi-quantize BEATS` | none | Move MIDI note starts and ends to this grid, in beats, for example `0.25` or `1/3`. Needs `--midi-tempo`. |
| `--instrument-range LOW HIGH` | none | The instrument's lowest and highest pitch, as note names or MIDI numbers, for example `C4 D7`. Notes outside it are flagged for review. They are never removed from the report. |

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
- `reference-clip.wav`: the selected reference range, unchanged.
- `render-level-matched.wav`: the selected render range, turned up or down so
  its loudness (LUFS) matches the reference. Both are 32-bit float WAVs.
- `notation-handoff.json` (only with `--midi`): the tempo, meter and
  quantization behind the MIDI file, and each note's performed time and
  cents. See [Hand the notes to Dorico](#hand-the-notes-to-dorico).
- `excerpts/` (only with `--excerpts`): `event-NNN-reference.wav` and
  `event-NNN-render.wav` for each flagged event in the report. `NNN` is the
  event number used in the report and the JSON.
- `reference-notes.mid` (only with `--midi`): the reference's notes as MIDI,
  starting at 0 s at the start of the selected range. Pitches are rounded to
  the nearest semitone and velocity follows each note's level. The rhythm is
  not quantized. Import it into a **new** Dorico project as a starting draft.
  Every detected note is included unless you add `--midi-min-confidence` or
  `--midi-skip-out-of-range`. The report says how many notes the filters left
  out, and the JSON lists each with its reason. Fragments shorter than 55 ms
  are never notes, so they are never written. They are listed as
  `candidates` in the JSON.

Earlier reports are never overwritten.

## Follow tempo changes

By default, notes are paired by their order and pitch, and timing uses one
constant offset. If the performer speeds up or slows down, the attack values
then grow steadily. If the render skips a repeat, the wrong copy can be paired.
Use phrase alignment:

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav --align phrase
```

It pairs notes by where they are played as well. It follows drift of up to
`--max-drift` seconds (default 1) and leaves notes that do not fit unmatched.
The raw times and the attack after the constant offset are kept. Each pair
also gets the attack after the local time map. The report's *What the note
match score reflects* section shows how much of the score is due to drift.
See [How it works](how-it-works.md#phrase-alignment).

## Hand the notes to Dorico

`--midi` writes the reference's notes as `reference-notes.mid`, with
`notation-handoff.json` next to it. By default the MIDI file keeps the
performed timing at 120 crotchets per minute, unquantized. To get readable
rhythms on import, give the tempo and meter you intend, and a grid:

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav --midi `
  --midi-tempo 72 --midi-meter 3/4 --midi-quantize 1/4
```

The start of the reference range is bar 1 beat 1, so start the range on a
downbeat. The tempo counts the meter's lower note: in 6/8, `--midi-tempo 120`
means 120 quavers per minute. The grid is in those beats: `0.5` is a
semiquaver in 3/4, and `1/3` is a triplet.

Quantization only changes the MIDI file. `comparison.json` and
`notation-handoff.json` keep every note's performed time in seconds and its
pitch in cents. The handoff also records the beat, the bar and how far each
note was moved. Every run writes a new folder. The handoff's `revision`
counts the earlier handoffs from the same reference audio and range in the
output folder, and `previous` names the last one. Import each revision into a
new Dorico project version.

## Locate events in the score

An **event map** lists the written notes of the render, so each detected
event can be traced to a bar, beat, part and voice in Dorico. It is optional.
Without one, comparisons work as before.

Pass a CSV file or a MIDI file:

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav --event-map dorico-notes.csv
```

**CSV.** One row per written note. `time_s` and `pitch` are required. The
other columns are optional and can be left blank:

| Column | Meaning |
|---|---|
| `time_s` | When the note starts, in seconds from the start of the **render file**. |
| `pitch` | A MIDI number (`69`, or `69.5` for a quarter tone) or a note name such as `A4`, `C#5` or `Bb3`. Middle C is `C4`. |
| `duration_s` | Written length in seconds. The detector check needs it to judge note ends. |
| `bar`, `beat` | Position in the score. Beats count from 1 and may be fractional (`2.5`). |
| `part`, `voice` | Text, for example `Flute` and `1`. |

```text
time_s,pitch,duration_s,bar,beat,part,voice
0.500,A4,0.400,1,1,Flute,1
1.000,A4,0.400,1,2,Flute,1
```

Column names are not case-sensitive. A file saved by Excel with a byte order
mark also works.

**MIDI.** A MIDI export of the same passage from Dorico (**File → Export →
MIDI**) supplies times, pitches and durations. The part name comes from each
track's name. Bars and beats are counted from the MIDI file's time signatures
and tempo, starting at bar 1 at the start of the file. With a pickup bar, or
when the exported passage does not start at bar 1, they will not match
Dorico's bar numbers. The beat follows
[pretty_midi](https://github.com/craffel/pretty-midi): compound meters such as
6/8 count dotted beats. MIDI has no voices, and drum tracks are skipped.

Check that the map and the WAV start at the same moment. If the WAV has
silence before the first note that the map does not, pass the difference with
`--event-map-offset`.

With a map, the report has a **Written** column, a written location for each
flagged event and a [detector check](report.md#detector-check). Each
unmatched event then says either that the note **is written but was not
detected in the render**, or that there is **no mapped written event** for it.

## Listen to flagged events

`--excerpts` writes a pair of short clips for each flagged event listed in
the report's *Flagged events in musical order* section:

```powershell
.\.venv\Scripts\python.exe compare.py take3.wav dorico.wav --excerpts
```

Each clip runs from the start of the previous matched note pair to the end of
the next one, plus 0.25 s on each side, so both clips cover the same notes. The
render clip gets the same gain as `render-level-matched.wav`. The report
links each clip and gives its time range in the source file and the gain
used. The JSON has the same details in each event's `excerpt` field.

## Check the detector

To find out what the note detector misses on a real Dorico export, run
`check` on a render whose written notes you know:

```powershell
.\.venv\Scripts\python.exe compare.py check dorico.wav dorico-notes.csv
```

It needs no reference recording. It prints the path of a new
`detector-check.md` with a `detector-check.json` next to it. The report lists
false negatives, false positives and boundary errors with their bar and beat.
`check` takes `--render-start`, `--render-end`, `--event-map-offset`,
`--cache` and `--output`. See [Validate the detector](validation.md) for a
test score to render.

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
range or event map, a missing or unreadable file, silence, or no stable notes.
In that case a one-line `Comparison failed: …` message (`Detector check
failed: …` for `check`) is printed and no report is written.
