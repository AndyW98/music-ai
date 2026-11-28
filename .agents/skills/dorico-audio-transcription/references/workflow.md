# Workflow commands and checks

This reference describes the current `music-ai` CLI, not a fully automatic multi-instrument transcriber. Verify options against the checked-out version before running. Work in the repository root and use its existing Python environment; do not install packages during an ordinary transcription run.

## Audio and first handoff

`compare.py` documents WAV, FLAC, and OGG inputs. If a supplied MP3 is not accepted by the installed audio library, convert a **copy** to a supported format using an already available local converter. Keep the original unchanged and record the conversion path. Choose a short phrase for the first calibration and establish the downbeat before quantizing.

For a **solo** phrase, the CLI can emit its detected notes as an initial MIDI. A self-comparison is only a way to invoke that extractor; its comparison score has no meaning:

```powershell
# Set $py, $source, $bpm, $meter, $grid, $start, $end, and $runFolder first.
& $py compare.py $source $source --midi --midi-tempo $bpm --midi-meter $meter --midi-quantize $grid --reference-start $start --reference-end $end --output $runFolder
```

The resulting `reference-notes.mid` and `notation-handoff.json` preserve the proposed grid and performed times. `--midi-quantize` is in beats of the supplied meter: e.g., `0.25` is a sixteenth of a quarter-note beat in 4/4. Review candidates, low-confidence notes, octave jumps, and range flags. The current detector expects one sounding pitch at a time, so this MIDI is not a complete transcription of chords or multiple instruments.

For a whole mixed recording, work phrase by phrase and explicitly separate confirmed notes from uncertain ones. A manually or locally analyzed multi-voice MIDI can be imported, but identify how each voice was obtained. Do not use a published score or earlier score-derived MIDI during an audio-only pass.

## Dorico handoff

Create one new Dorico project at the start of the run, even if another project is open. Work only in this new project for all later passes. `File > Import > MIDI` opens MIDI Import Options; inspect track-to-instrument assignments and quantization. Turn off remembered/General MIDI guesses when they create wrong instruments. Select neutral non-transposing treble or bass staves, or suitable real instruments, and verify written versus sounding octave. Imported MIDI may create a second flow beside an empty first flow; remove only the empty flow in the workflow-created project after checking. Inspect first-bar beat position and clefs visually. Dorico can also import MusicXML, but test its playback against the source.

For revision tracking, open `File > Project Info` (`Ctrl+I`), select the **Project** entry, and put `Version 1` in **Other information** before saving the first draft. Change only that version label to `Version 2`, `Version 3`, and so on for each accepted saved revision; preserve any unrelated text already in that field. Dorico has no dedicated automatically incrementing project-version field. Keep the project title and filename stable and save the same project file on each iteration. If resuming, confirm that the file was created by this workflow; otherwise start a new project. Updating this metadata does not place it on the printed score unless a page template uses the corresponding token.

The installed Dorico 6 UI used `File > Export > Audio` with WAV selected. Export a fresh WAV to a unique directory for each version; reports and renders remain additive even though the workflow-created project file is updated in place. Export MIDI from the **same Dorico revision** if an event map is needed; a pre-import MIDI is not guaranteed to represent Dorico's final notation or timing. Match the map's time zero to the WAV, using `--event-map-offset` if needed.

## Comparison loop

```powershell
# Set $py, $source, $render, $eventMap, and $runFolder first.
& $py compare.py $source $render --event-map $eventMap --align phrase --excerpts --output $runFolder
```

Use `--reference-start`, `--reference-end`, `--render-start`, and `--render-end` for matching passages. Phrase alignment handles gradual drift and repeats; compare its local timing fields with unwarped timing. The report's pitch, timing, duration, and level differences are **render minus reference**. Open `comparison.md` first; `comparison.json` has every row. `--excerpts` creates short level-matched clips. `compare.py check <render.wav> <dorico-export.mid>` measures how many known written notes the detector itself missed. On polyphonic renders, this detector check is essential before interpreting low F1 or "missing note" claims. Any additional pitch-spectrum or waveform comparison is diagnostic and can respond strongly to different instrument samples.

Past polyphonic tests showed that a plausible overall sound can coexist with a low monophonic note score. Such scores do not establish an exact transcription; inspect the source, written notes, and actual Dorico render before changing a passage.

## Why these checks matter

- [Steinberg MIDI Import Options](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/project_file_handling/project_file_handling_midi_import_options_dialog_r.html) documents track memory, General MIDI interpretation, instrument mapping, and separate notation/performance settings.
- [Steinberg quantization guidance](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/project_file_handling/project_file_handling_quantize_options_r.html) describes the beat unit, tuplets, and gap filling used for readable import.
- [Steinberg audio export](https://www.steinberg.help/r/dorico-se/6.2/en/dorico/topics/project_file_handling/project_file_handling_audio_exporting_t.html) describes WAV export from the actual project.
- [Steinberg Project Info](https://www.steinberg.help/r/dorico-pro/6.2/en/dorico/topics/project_file_handling/project_file_handling_project_info_dialog_r.html) documents project-level and flow-level information fields, including Other information.
- [Shibata et al.](https://arxiv.org/abs/2008.12710) found that tempo scale, meter, and barline placement can be wrong even when note-level transcription is strong.
- [Berendes et al.](https://www.audiolabs-erlangen.de/content/05_fau/professor/00_mueller/03_publications/2026_BerendesAMM_UnisonNotes_DAGA_ePrint.pdf) explains ambiguity in assigning simultaneous or near-simultaneous ensemble notes to individual score events.
