"""Generate synthetic sample WAV files for tests and for trying the tool.

The samples are harmonic tones with short fades, so the expected results are
known exactly. Run it directly to write a demo pair::

    python tests/sample_audio.py samples

which creates ``samples/reference.wav`` and ``samples/render.wav``.
"""

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


def midi_to_hz(midi):
    """Convert a (fractional) MIDI pitch to Hz with A4 = 440 Hz."""
    return 440 * 2 ** ((midi - 69) / 12)


def synth(notes, total_s, gain=1.0, rate=RATE):
    """Return float samples (about -1..1) containing ``notes``.

    Each note is a fundamental plus a quieter second harmonic with 10 ms
    linear fades to avoid clicks.
    """
    out = np.zeros(int(total_s * rate))
    for start, duration, midi, amp in notes:
        n = int(duration * rate)
        t = np.arange(n) / rate
        freq = midi_to_hz(midi)
        envelope = np.minimum(1, np.minimum(t / .01, (duration - t) / .01))
        first = int(start * rate)
        out[first:first + n] += amp * envelope * (
            np.sin(2 * np.pi * freq * t) + .3 * np.sin(4 * np.pi * freq * t))
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
    for path in make_pair(target):
        print(path)
