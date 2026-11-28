"""Generate synthetic sample WAV files for tests and for trying the tool.

The samples are harmonic tones with short fades, so the expected results are
known exactly. Run it directly to write a demo pair::

    python tests/sample_audio.py samples

which creates ``samples/reference.wav`` and ``samples/render.wav``, plus
``samples/validation-render.wav`` and ``samples/validation-events.csv`` for
``compare.py check`` (see ``VALIDATION_NOTES``).
"""

import csv
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

RATE = 44100

# (start_s, duration_s, midi_pitch, amplitude) for the reference "recording".
REFERENCE_NOTES = [(0.50, .60, 69, 1.0), (1.30, .60, 72, .7), (2.10, .60, 76, .5)]

# The "Dorico render": 0.2 s later overall and 6 dB quieter. Note 2 is 25 cents
# sharp, 40 ms late and 50 ms long. Note 3 is 18 cents flat, 30 ms early and
# 40 ms short. Per-note levels relative to the reference are 0, +2.2 and
# -4.4 dB before the overall gain is removed.
RENDER_OFFSET_S = .20
RENDER_NOTES = [
    (0.50 + RENDER_OFFSET_S, .60, 69, 1.0),
    (1.30 + RENDER_OFFSET_S + .040, .60 + .050, 72 + .25, .9),
    (2.10 + RENDER_OFFSET_S - .030, .60 - .040, 76 - .18, .3),
]

# A synthetic stand-in for the detector test score in docs/validation.md:
# 4/4 at 120 bpm (0.5 s per beat) after a 0.5 s lead-in, one part, one voice.
# (bar, beat, beats_long, midi_pitch, amplitude, sounding_fraction, fade_s). A
# sounding fraction of 1 is slurred (no gap before the next note). The fade is
# each note's attack and release ramp; 40 ms on the slurred repeated E5 models
# the brief level dip a sample library plays when it re-articulates a note.
VALIDATION_BEAT_S = .5
VALIDATION_LEAD_IN_S = .5
VALIDATION_SCORE = [
    # Bar 1: four detached repeated A4 crotchets.
    (1, 1, 1, 69, 1.0, .8, .01), (1, 2, 1, 69, 1.0, .8, .01), (1, 3, 1, 69, 1.0, .8, .01),
    (1, 4, 1, 69, 1.0, .8, .01),
    # Bar 2: four slurred quavers, a crotchet rest, then a crotchet.
    (2, 1, .5, 72, .8, 1., .01), (2, 1.5, .5, 74, .8, 1., .01), (2, 2, .5, 76, .8, 1., .01),
    (2, 2.5, .5, 77, .8, .9, .01), (2, 4, 1, 79, .8, .9, .01),
    # Bar 3: a slurred repeated E5 (no gap, only a level dip), then two quiet
    # notes at about -20 and -26 dB.
    (3, 1, 1, 76, .8, 1., .04), (3, 2, 1, 76, .8, .9, .04), (3, 3, 1, 74, .1, .9, .01),
    (3, 4, 1, 72, .05, .9, .01),
    # Bar 4: a minim with a 60 ms breath-like noise dropout at beat 2, then a
    # minim rest.
    (4, 1, 2, 69, .8, .95, .01),
]
# (start_s, duration_s, noise_rms) bursts that replace the tone.
VALIDATION_DROPOUTS = [(VALIDATION_LEAD_IN_S + 13 * VALIDATION_BEAT_S, .06, .05)]


def validation_notes():
    """``(start_s, duration_s, midi_pitch, amplitude, fade_s)`` for ``VALIDATION_SCORE``."""
    notes = []
    for bar, beat, beats, pitch, amp, fraction, fade in VALIDATION_SCORE:
        start = VALIDATION_LEAD_IN_S + ((bar - 1) * 4 + beat - 1) * VALIDATION_BEAT_S
        notes.append((start, beats * VALIDATION_BEAT_S * fraction, pitch, amp, fade))
    return notes


def make_validation(folder):
    """Write ``validation-render.wav`` and its known ``validation-events.csv``."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    notes = validation_notes()
    total = notes[-1][0] + notes[-1][1] + 1.
    audio = write_wav(folder / "validation-render.wav",
                      synth(notes, total, dropouts=VALIDATION_DROPOUTS))
    events = folder / "validation-events.csv"
    with events.open("w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["time_s", "duration_s", "pitch", "bar", "beat", "part", "voice"])
        for (start, duration, pitch, *_), (bar, beat, *_) in zip(notes, VALIDATION_SCORE):
            writer.writerow([f"{start:.3f}", f"{duration:.3f}", pitch, bar, f"{beat:g}", "Flute", 1])
    return audio, events


def midi_to_hz(midi):
    """Convert a (fractional) MIDI pitch to Hz with A4 = 440 Hz."""
    return 440 * 2 ** ((midi - 69) / 12)


def synth(notes, total_s, gain=1.0, rate=RATE, dropouts=()):
    """Return float samples (about -1..1) containing ``notes``.

    Each note is ``(start_s, duration_s, midi_pitch, amplitude)`` with an
    optional fifth ``fade_s`` (default 10 ms). It is a fundamental plus a
    quieter second harmonic with linear fades to avoid clicks. Each
    ``(start_s, duration_s, noise_rms)`` in ``dropouts`` replaces the signal
    with seeded white noise, like a breath.
    """
    out = np.zeros(int(total_s * rate))
    for start, duration, midi, amp, *fade in notes:
        fade = fade[0] if fade else .01
        n = int(duration * rate)
        t = np.arange(n) / rate
        freq = midi_to_hz(midi)
        envelope = np.minimum(1, np.minimum(t / fade, (duration - t) / fade))
        first = int(start * rate)
        out[first:first + n] += amp * envelope * (
            np.sin(2 * np.pi * freq * t) + .3 * np.sin(4 * np.pi * freq * t))
    noise = np.random.default_rng(0)
    for start, duration, level in dropouts:
        first, n = int(start * rate), int(duration * rate)
        out[first:first + n] = noise.normal(0, level / .6, n)
    return out * gain * .6


def write_wav(path, samples, dtype="int16", rate=RATE):
    """Write float ``samples`` to ``path`` as int16, int32, uint8 or float32."""
    samples = np.asarray(samples, dtype=float)
    if dtype == "int16":
        data = np.round(samples * 32767).astype(np.int16)
    elif dtype == "int32":
        data = np.round(samples * 2147483647).astype(np.int32)
    elif dtype == "uint8":
        data = np.round(samples * 127 + 128).astype(np.uint8)
    elif dtype == "float32":
        data = samples.astype(np.float32)
    else:
        raise ValueError(f"Unsupported dtype {dtype}")
    wavfile.write(path, rate, data)
    return Path(path)


def make_pair(folder):
    """Write ``reference.wav`` and ``render.wav`` into ``folder``; return both paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    reference = write_wav(folder / "reference.wav", synth(REFERENCE_NOTES, 3.2))
    render = write_wav(folder / "render.wav", synth(RENDER_NOTES, 3.4, gain=.5))
    return reference, render


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    for path in (*make_pair(target), *make_validation(target)):
        print(path)
