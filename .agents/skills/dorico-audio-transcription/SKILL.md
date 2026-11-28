---
name: dorico-audio-transcription
description: Transcribe a supplied audio recording into a new editable Dorico score, then iteratively compare Dorico exports with the recording using the local music-ai tool. Use for audio-to-score work, including readability and fidelity checks; not for score-only critique.
---

# Dorico audio transcription

Produce a new Dorico project whose notes, voices, rhythm, and staff layout are defensible from the supplied audio. For an audio-only task, keep published scores out of the drafting loop and consult them only afterward if the user requests an independent check. Prefer this repository's `compare.py` CLI and an available Dorico integration; do not add services or transcription software as part of an ordinary run.

## Hindsight long-term memory

Use Hindsight by default when it is configured and reachable. At the start of each run, check for Hindsight MCP `recall`/`retain` tools. If they are not exposed, check a configured endpoint through an available MCP client. Use the configured music bank; the original setup used case-sensitive `Music`. Read [Hindsight connection and memory use](references/hindsight.md) when the tools are absent or when recording a new finding.

Recall relevant project preferences, current workflow state, prior failure modes, and transcription-method references before planning a pass. Query for the recording or texture at hand, and distinguish verified past results from hypotheses. Memory is a lead for research, not proof: check current CLI/Dorico behavior and authoritative source links before relying on it. A previous score, reference edition, or score-derived transcription recalled from memory must **not** supply pitches or rhythms to an audio-only draft.

After a meaningful verified revision or research finding, retain a concise record in the configured music bank: the workflow-created project path and Project Info version, audio-only provenance, settings, render/report paths, measured result with its limits, unresolved discrepancies, and source links for researched methods. Update or qualify stale findings instead of repeating unverified claims. If Hindsight cannot be reached, continue the transcription and state that the run's new findings were not saved to long-term memory. Do not install or reconfigure Hindsight as part of a transcription run.

## Start the run

1. Resolve the source recording and locate this `music-ai` checkout ([repository](https://github.com/AndyW98/music-ai)); verify its current commands from `compare.py --help` and `docs/usage.md`. Inspect available Dorico/Maestro tools; Maestro is optional and may not be connected in a new chat. Use an available Windows computer-use capability for Dorico GUI work when needed.
2. Treat original audio and all Dorico projects that predate this workflow as read-only, including an already-open blank project. At the start of a run, create one new run folder and one new Dorico project. Edit only that workflow-created project through subsequent iterations; do not create a new project for each pass. If resuming a prior run, verify which project this workflow created before editing it. Keep each exported WAV and comparison report in a new location. Never overwrite or delete the input audio or any pre-existing project.
3. Keep sheet music and other transcriptions out of the inference loop. Document the audio source, any conversion, and which drafts were derived solely from audio. A score reference can be used afterward for an independent accuracy check only.

## Build a musically readable first draft

Inspect the recording's length, sections, texture, likely instruments, and whether it is a solo line or overlapping parts. The current `compare.py` pitch tracker follows one dominant pitch at a time; a multi-part score requires additional careful listening and available local analysis. Do not claim that the CLI alone separated instruments.

Estimate tempo, beat phase/downbeat, meter, pickups, and repetitions from the recording *before* quantizing note times. Compare plausible half/double-time interpretations; do not force the first audible sound onto beat one if the music has a pickup. Keep expressive timing separate from the notated grid. For a solo line, `compare.py` can generate a provisional MIDI from the recording; see [workflow commands](references/workflow.md). For polyphony, mark uncertain voices and notes rather than inventing a complete transcription.

Import into the project created for this run. Verify track order, instrument transposition, clefs, first measure, rests, ties, and a representative later passage visually. Check Dorico's import choices rather than trusting automatic track memory or General MIDI guesses. Put bass material on a bottom bass-clef staff when that is the intended layout.

## Render, compare, revise

In File > Project Info, select the **Project** entry and record `Version 1` in **Other information** before the first save. Dorico does not provide a dedicated automatically incrementing version field. Save this one new project under a unique name and export its actual Dorico WAV. Run `compare.py` with original audio first, Dorico export second. Use a MIDI/CSV event map from the **current Dorico score** when possible, select matching ranges, and use phrase alignment when timing drifts or repeats confuse pairings. Read `comparison.md` first; inspect JSON and level-matched excerpts only for specific discrepancies. Compare note identity, attack, duration, and score location, then listen to the source and render before changing notation. Treat loudness, timbre, reverb, and tuning separately from note errors. A flagged "missing" pitch may already be written but missed by the detector.

Revise a short passage **in the same workflow-created Dorico project**. For each accepted revision, increment the version label in Project Info (`Version 2`, `Version 3`, ...), save the same project file, export a **new** WAV, and compare again. Do not increment for a rejected experiment or an analysis-only pass. Keep a change only when the score becomes more readable or evidence supports a musical correction; a single F1 or spectrum score is not proof of accuracy on polyphonic audio. Stop when the requested scope is covered and remaining discrepancies are documented, or when further passes lack a defensible improvement. Report the project path and current Project Info version, render/report files, what changed, what was checked, and unresolved uncertainty. Do not describe a draft as exact merely because its render sounds similar.

Read [workflow commands](references/workflow.md) for the CLI handoff, Dorico import/export checks, and sources behind these decisions.
