# Audio-to-score roadmap

The tool supports reviewing transcriptions of any piece with one sounding note at a time. Use a solo recording or isolated part when the source contains overlapping pitches. Keep the comparison tool local and command-line driven. Dorico Maestro and Dorico remain responsible for score creation and rendering.

Bach's Sarabande is one validation example. Three audio-only renders scored 0.20, 0.15, and 0.28 under the current strict audio-event metric. An event reported as unmatched was already present in the written score. Use those findings to prioritize evidence and traceability.

## Epic 1 — Make each discrepancy reviewable

- **1.1 — Trace detections to score events.** As a reviewer, I want to locate a flagged event in both audio files and in Dorico. **Acceptance:** Show reference and render timestamps, detected pitch and confidence on both sides, and bar, beat, part, and voice when an optional event map is provided. Distinguish “no detected render event” from “no mapped written event.” Comparisons without a map still work.
- **1.2 — Audition a discrepancy.** As a reviewer, I want to hear the same musical context on both sides. **Acceptance:** Generate short, level-matched excerpts for selected flags. Include their source time ranges and applied gain. Link the clips from a chronological Markdown view and keep full event details in JSON.
- **1.3 — Validate against known rendered events.** As a maintainer, I want to know what the detector misses on real Dorico audio. **Acceptance:** Document a reproducible solo test score and render procedure, including repeated pitches, slurs, rests, and quiet notes. Compare against known note events and report false positives, false negatives, and boundary errors. Keep personal scores and recordings out of Git.

## Epic 2 — Improve pitch and note boundaries

- **2.1 — Flag suspect pitches.** As a transcriber, I want to review likely octave errors and out-of-range detections. **Acceptance:** Report the reason and supporting pitch evidence for each flag. An optional instrument range raises a review flag. It does not silently discard notes or alter the score.
- **2.2 — Separate attacks from fluctuations within a note.** As a transcriber, I want to distinguish a genuine reattack from vibrato, a brief voicing gap, or a breath. **Acceptance:** Evaluate pitch stability and attack evidence together. Add regression cases for false splits and legato same-pitch reattacks. Report split and merge errors against the existing detector.
- **2.3 — Preserve uncertain events for review.** As a reviewer, I want to see what the detector is unsure about before importing MIDI. **Acceptance:** Retain raw candidates and reasons in JSON. Make any MIDI filtering explicit and report what it excluded.

## Epic 3 — Align phrases and preserve timing

- **3.1 — Pair events despite local drift.** As a reviewer, I want corresponding notes to stay aligned when the performer speeds up or slows down. **Acceptance:** Add optional phrase-level alignment with bounded drift. Preserve raw timestamps and unwarped timing errors, and leave uncertain passages unmatched. Cover repeats, long pauses, and an extra or missing note in tests.
- **3.2 — Explain why a comparison score changed.** As a reviewer, I want to tell apart timing error, systematic tuning, and pitch disagreement. **Acceptance:** Keep the strict baseline F1 and report pitch, attack, duration, and tuning diagnostics separately. State any tuning correction, timing offset, or alignment applied.
- **3.3 — Preserve performance time during notation import.** As a transcriber, I want readable rhythms while retaining the measured performance. **Acceptance:** Preserve note times in seconds and cents in the analysis output. Keep meter, tempo, and quantization choices explicit in the notation handoff, and generate a new version for each revision.

## First milestone

Implement stories 1.1–1.3 first. Demonstrate one short solo phrase from original audio through a Dorico draft and WAV export. Account for each flagged discrepancy by checking the audio and the written note. Apply one evidence-backed edit in a new draft, re-export, and show whether the targeted discrepancy improves. Keep any published score out of the transcription and refinement loop. If used for evaluation, introduce it only after the audio-only draft is frozen.

Polyphonic detection and source separation are possible follow-on work outside these epics.
