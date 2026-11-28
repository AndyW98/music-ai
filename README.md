# Dorico Audio Compare

Compare a solo reference recording with an audio export from Dorico. The tool
runs locally and needs Python 3.12 or later. It can run on a machine without
Dorico, and it never opens or edits a score.

Full documentation: <https://andyw98.github.io/music-ai/>. New users should
start with the [first-time setup guide](docs/getting-started.md).

## Audio-to-Dorico skill in ChatGPT desktop (Windows)

The repository includes the [Dorico audio transcription skill](.agents/skills/dorico-audio-transcription/SKILL.md). It guides Codex through an audio-only draft, a readable Dorico score, repeated Dorico WAV exports, and review with this CLI. It creates one new Dorico project for a run, then revises that project; it does not edit projects that existed before the run. Hindsight memory is optional. The skill does not turn this CLI into an automatic polyphonic transcriber: its pitch detector follows one dominant note at a time.

1. Install the [ChatGPT desktop app for Windows](https://learn.chatgpt.com/docs/app/windows), [Dorico](https://www.steinberg.net/dorico/), [Git for Windows](https://git-scm.com/download/win), Python 3.12 or later, and [uv](https://docs.astral.sh/uv/getting-started/installation/) (or use standard `venv`). Sign in to the desktop app. Use its Windows-native agent so it can reach Dorico on the same PC. Check your Dorico version against the integration's supported versions.
2. Clone this repository with the command below. In ChatGPT desktop, switch to **Codex**, add the cloned `music-ai` folder as a local project, and start a new task there. Codex discovers the checked-in skill from `.agents/skills/`; open **Skills** in the sidebar to confirm it appears. If it does not, restart the app or start a new task. The standalone skill is available in the desktop app's Codex environment; merely pasting the repository URL into an ordinary Chat does not install it.

   ```powershell
   git clone https://github.com/AndyW98/music-ai.git
   cd music-ai
   uv venv .venv
   uv pip install --python .venv\Scripts\python.exe -r requirements.txt
   .\.venv\Scripts\python.exe compare.py --help
   ```

3. Install [Dorico Maestro](https://github.com/romanstark/dorico-maestro) if you want MCP control of Dorico. Its current quick start supports Dorico 4, 5, and 6 and uses `uv tool install git+https://github.com/romanstark/dorico-maestro.git`. Register the installed `dorico-maestro` command as a **local stdio MCP server** for Codex. One option is `codex mcp add dorico-maestro -- dorico-maestro`; alternatively, use the desktop app's MCP settings or add the TOML entry below to `%USERPROFILE%\.codex\config.toml`. Restart the task, open a disposable Dorico project, authorize Dorico's first-connection prompt, and ask for a read-only status check before attempting edits. [Codex MCP setup](https://learn.chatgpt.com/docs/extend/mcp) and [Maestro's README](https://github.com/romanstark/dorico-maestro#quick-start) have the current details.

   ```toml
   [mcp_servers.dorico-maestro]
   command = "dorico-maestro"
   ```

4. In a new Codex task with an audio file available locally, select **Dorico Audio Transcription** from Skills or ask: “Use `$dorico-audio-transcription` on this recording. Create a new Dorico project, estimate tempo and meter, make a readable draft, export WAV, compare it with the source, and revise the same project. Keep older projects and the source audio unchanged.” Review the proposed score and each reported uncertainty. The agent needs local file, CLI, and Dorico access; permission prompts and the first Dorico authorization may need your input.

To use the skill in a *different* repository, ask Codex's `$skill-installer` to install the skill from `AndyW98/music-ai` at `.agents/skills/dorico-audio-transcription`. Start a new task in that repository afterward. Keep this `music-ai` checkout available to run `compare.py`, and give the agent its path. The skill by itself supplies workflow instructions, not the CLI, Dorico, or Maestro.

You can start or steer a **Codex task with Voice** in the ChatGPT desktop app when Voice is available for your account and workspace. Voice follows that task's tools and permissions. Plain Chat, Work, and Codex have different tool environments; the local repository skill and a local Maestro MCP registration should be tested in the Codex task that will do the work. See [ChatGPT Voice](https://learn.chatgpt.com/docs/features/voice) and [skill discovery](https://learn.chatgpt.com/docs/build-skills). Do not expose the local Dorico MCP connection to the public internet.

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
