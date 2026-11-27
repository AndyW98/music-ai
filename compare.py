"""Compare a solo recording with a notation render.

Pipeline, for each of the two audio files (WAV, FLAC, OGG and other formats
that libsndfile reads):

1. ``read_audio`` loads the file and scales it to floating point full scale.
2. ``track`` estimates pitch every 10 ms with a YIN-style difference function.
3. ``segment`` groups consecutive pitched frames into notes.
4. ``analyze`` wraps steps 1-3 and caches the result by file content and range.

The two note lists are then paired by ``align`` (an edit-distance alignment
that tolerates missing and extra notes), measured by ``compare`` and scored
with mir_eval's note-matching metrics. ``main`` writes ``comparison.json``,
a short ``comparison.md``, level-matched listening copies and, on request, a
MIDI file of the reference notes.

Input files are only ever opened for reading. Every output is a new file.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import tempfile

import mir_eval
import numpy as np
import pretty_midi
import pyloudnorm
from scipy import signal
import soundfile

# Bump when ``read_audio``, ``track``, ``segment`` or the cached data changes,
# so that stale cache entries are never reused.
CACHE_VERSION = "v2"

# mir_eval note matching: onsets within 50 ms and pitch within 50 cents count
# as the same note. The offset score also needs the note end within 20% of the
# reference duration (or 50 ms, whichever is larger).
ONSET_TOLERANCE_S = .05
PITCH_TOLERANCE_CENTS = 50.
OFFSET_RATIO = .2

# General MIDI program for --midi (0-based; 73 is "Flute").
DEFAULT_MIDI_PROGRAM = 73


@dataclass
class Note:
    """One detected note event.

    Times are seconds from the start of the file (not the selected range).
    ``pitch`` is a fractional MIDI number relative to A440, so 69.25 is A4
    25 cents sharp. ``confidence`` is the median per-frame tracker confidence
    (0-1) and ``rms`` is the note's RMS level in full-scale units.
    """

    start: float
    end: float
    pitch: float
    confidence: float
    rms: float


def read_audio(path):
    """Return ``(sample_rate, samples)`` with samples scaled to about -1..1.

    Uses soundfile (libsndfile), so WAV in any PCM or float format, FLAC and
    OGG Vorbis all work. Integer PCM is scaled by the magnitude of its most
    negative value (e.g. 32768 for 16-bit). Multichannel audio keeps its
    channel axis; ``analyze`` mixes it to mono later.
    """
    try:
        samples, rate = soundfile.read(path, dtype="float64")
    except soundfile.SoundFileError as error:
        # libsndfile errors are RuntimeErrors; report them like bad input.
        raise ValueError(f"Cannot read audio in {path}: {error}") from error
    if not samples.size or not np.all(np.isfinite(samples)):
        raise ValueError(f"Empty or invalid audio in {path}")
    return rate, samples


def track(mono, rate, start, stop):
    """Estimate pitch for each 10 ms hop of ``mono[start:stop]`` (seconds).

    Uses 40 ms analysis windows and searches roughly 120-2400 Hz. Returns
    ``(frames, hop_seconds)`` where each frame is
    ``[time_s, pitch_or_None, confidence, rms]``. Frames quieter than 0.8% of
    the clip's peak, or with confidence below 0.70, get ``None`` for pitch.
    """
    hop = round(rate * .01)
    width = round(rate * .04)
    # Lag range in samples: short lags = high pitch (2400 Hz), long = low (120 Hz).
    min_lag, max_lag = max(2, int(rate / 2400)), int(rate / 120)
    clip = mono[round(start * rate):round(stop * rate)]
    if len(clip) < width or not np.any(clip):
        raise ValueError("Selected range is silent or shorter than 40 ms")
    # Pad so each window is centred on its frame time.
    padded = np.pad(clip, width // 2)
    gate = np.max(np.abs(clip)) * .008
    frames = []
    for index in range(0, len(clip), hop):
        frame = padded[index:index + width]
        rms = float(np.sqrt(np.mean(frame**2)))
        pitch, confidence = None, 0.
        if rms >= gate:
            centered = frame - frame.mean()
            ac = signal.correlate(centered, centered, method="fft")[width - 1:]
            # YIN difference function d(lag) computed from the autocorrelation
            # and running energy, then the cumulative mean normalised form.
            power = np.r_[0, np.cumsum(centered**2)]
            lags = np.arange(1, max_lag + 2)
            difference = np.maximum(0, power[width - lags] + power[width] -
                                    power[lags] - 2 * ac[lags])
            curve = np.r_[1., difference * lags / np.maximum(np.cumsum(difference), 1e-15)]
            candidates = signal.find_peaks(-curve)[0]
            candidates = candidates[(candidates >= min_lag) & (candidates <= max_lag)]
            if len(candidates):
                # Prefer the first dip below the 0.15 threshold (avoids octave
                # errors); otherwise fall back to the deepest dip.
                good = candidates[curve[candidates] < .15]
                lag = good[0] if len(good) else candidates[np.argmin(curve[candidates])]
                confidence = float(np.clip(1 - curve[lag], 0, 1))
                if confidence >= .70:
                    # Parabolic interpolation for a sub-sample lag estimate.
                    left, center, right = curve[lag - 1:lag + 2]
                    delta = .5 * (left - right) / (left - 2 * center + right)
                    pitch = float(69 + 12 * np.log2(rate / (lag + delta) / 440))
        frames.append([start + index / rate, pitch, confidence, rms])
    return frames, hop / rate


def segment(frames, hop, stop):
    """Group pitched frames into ``Note`` objects.

    A note ends at an unpitched frame or when the pitch moves more than 65
    cents from the median of the previous five frames. Notes shorter than
    55 ms are dropped. ``stop`` closes any note still open at the range end.
    """
    notes = []
    group = []
    # The sentinel frame at ``stop`` flushes the final group.
    for frame in [*frames, [stop, None, 0., 0.]]:
        time, pitch, _, _ = frame
        if group and (pitch is None or abs(pitch - np.median([f[1] for f in group[-5:]])) > .65):
            if len(group) * hop >= .055:
                values = np.asarray(group)
                _, pitches, confidence, rms = values.T
                notes.append(Note(group[0][0], time, float(np.median(pitches)),
                                  float(np.median(confidence)), float(np.sqrt(np.mean(rms**2)))))
            group = []
        if pitch is not None:
            group.append(frame)
    return notes


def analyze(path, start, end, cache):
    """Analyse ``path`` between ``start`` and ``end`` seconds, using the cache.

    The cache key is a SHA-256 of ``CACHE_VERSION``, the requested range
    and the file's bytes, so renaming a file still hits the cache while
    editing it or changing the range does not. Returns ``(data, cache_hit)``.
    ``end=None`` means the end of the file.
    """
    key = hashlib.sha256(f"{CACHE_VERSION}:{start}:{end}".encode())
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            key.update(block)
    target = cache / f"{key.hexdigest()}.json"
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8")), True
        except json.JSONDecodeError:
            # An interrupted or concurrent writer may leave a partial cache entry.
            pass
    rate, samples = read_audio(path)
    stop = min(end, len(samples) / rate) if end is not None else len(samples) / rate
    if start >= stop:
        raise ValueError(f"Range starts outside {path.name}")
    # Peak and RMS are measured on the selected range across all channels;
    # pitch tracking uses a mono mix of the whole file, sliced by ``track``.
    clip = samples[round(start * rate):round(stop * rate)]
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    frames, hop = track(mono, rate, start, stop)
    notes = segment(frames, hop, stop)
    if not notes:
        raise ValueError(f"No stable solo notes detected in {path.name}")
    data = {"range": [start, stop], "peak": float(np.max(np.abs(clip))),
            "rms": float(np.sqrt(np.mean(clip**2))), "frames": frames,
            "notes": [asdict(note) for note in notes]}
    cache.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, allow_nan=False)
    try:
        # Exclusive create: never overwrite an entry another run just wrote.
        with target.open("x", encoding="utf-8") as out:
            out.write(encoded)
    except FileExistsError:
        pass
    return data, False


MAX_PAIR_DISTANCE_CENTS = 300.0


def align(original, render):
    """Global note alignment with insertions and deletions.

    Dynamic programming over the two note lists (like an edit distance).
    Pairing two notes costs up to 1.75 for pitch (free within 35 cents, then
    1 per 100 cents) plus up to 0.35 for a duration ratio. Skipping a note on
    either side costs 1. Notes more than three semitones apart are left
    unpaired. Returns ``(reference_index, render_index)`` pairs in
    order, with ``None`` for an unmatched side.
    """
    n, m = len(original), len(render)
    cost = np.zeros((n + 1, m + 1))
    # step: 0 = pair, 1 = reference note unmatched, 2 = render note unmatched.
    step = np.zeros_like(cost, dtype=np.uint8)
    cost[:, 0], cost[0, :] = np.arange(n + 1), np.arange(m + 1)
    step[1:, 0], step[0, 1:] = 1, 2
    for i, a in enumerate(original, 1):
        for j, b in enumerate(render, 1):
            cents = abs(a.pitch - b.pitch) * 100
            penalty = np.inf
            if cents <= MAX_PAIR_DISTANCE_CENTS:
                ratio = abs(np.log((b.end - b.start) / (a.end - a.start)))
                penalty = min(1.75, max(0., cents - 35) / 100) + min(.35, ratio * .2)
            choices = (cost[i - 1, j - 1] + penalty,
                       cost[i - 1, j] + 1, cost[i, j - 1] + 1)
            k = min(range(3), key=choices.__getitem__)
            cost[i, j], step[i, j] = choices[k], k
    # Trace back from the bottom-right corner.
    pairs = []
    while n or m:
        k = step[n, m]
        pairs.append((n - 1 if k != 2 else None, m - 1 if k != 1 else None))
        n -= k != 2
        m -= k != 1
    return pairs[::-1]


def compare(reference, rendered):
    """Measure render-minus-reference differences for every aligned pair.

    Timing is made relative to the first matched pair whose pitches agree
    within 60 cents, so a constant lead-in difference is removed. Levels are
    compared after applying the gain that matches the two clips' overall RMS.
    """
    original, render = ([Note(**item) for item in x["notes"]] for x in (reference, rendered))
    pairs = align(original, render)
    anchors = [(i, j) for i, j in pairs if i is not None and j is not None
               and abs(original[i].pitch - render[j].pitch) < .6]
    # Constant offset between the files, taken from the first anchor note.
    shift = render[anchors[0][1]].start - original[anchors[0][0]].start if anchors else None
    gain = float(20 * np.log10(reference["rms"] / rendered["rms"]))
    rows = []
    for i, j in pairs:
        a = original[i] if i is not None else None
        b = render[j] if j is not None else None
        row = {"reference_s": a.start if a else None, "render_s": b.start if b else None}
        if a is None or b is None:
            row["status"] = "extra render event" if a is None else "unmatched reference event"
        else:
            cents = (b.pitch - a.pitch) * 100
            # A neighbour with the same pitch means the pairing may have
            # slipped by one note (e.g. repeated notes), so flag for review.
            nearby = ((original, i, b.pitch), (render, j, a.pitch))
            repeated = any(
                abs(notes[k].pitch - pitch) < .5
                for notes, index, pitch in nearby
                for k in (index - 1, index + 1) if 0 <= k < len(notes)
            )
            row.update(status="matched", pitch_cents=cents,
                       onset_ms=None if shift is None else (b.start - a.start - shift) * 1000,
                       duration_ms=((b.end - b.start) - (a.end - a.start)) * 1000,
                       relative_level_db=float(20 * np.log10(b.rms / a.rms) + gain),
                       review=repeated or abs(cents) >= 60 or min(a.confidence, b.confidence) < .85)
        rows.append(row)
    return {"render_minus_reference_offset_s": shift, "render_gain_for_rms_match_db": gain,
            "note_match": note_scores(original, render, shift or 0.), "events": rows}


def note_scores(original, render, shift):
    """Score the render's notes against the reference with mir_eval.

    The render is shifted back by ``shift`` seconds first, so a constant
    lead-in difference is not counted as a timing error. Returns precision,
    recall and F1 for onset+pitch matching, and again with offsets required.
    These are the standard note-transcription metrics, useful for checking
    that a new draft is better overall than the previous one.
    """
    def arrays(notes, offset):
        intervals = np.array([[n.start - offset, n.end - offset] for n in notes])
        hertz = 440. * 2 ** ((np.array([n.pitch for n in notes]) - 69) / 12)
        return intervals, hertz

    scores = {}
    for name, ratio in (("onset_pitch", None), ("onset_pitch_offset", OFFSET_RATIO)):
        if not original or not render:
            # Nothing can match; mir_eval rejects empty interval arrays.
            scores[name] = {"precision": 0., "recall": 0., "f1": 0.}
            continue
        ref_intervals, ref_hz = arrays(original, 0.)
        est_intervals, est_hz = arrays(render, shift)
        precision, recall, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
            ref_intervals, ref_hz, est_intervals, est_hz, onset_tolerance=ONSET_TOLERANCE_S,
            pitch_tolerance=PITCH_TOLERANCE_CENTS, offset_ratio=ratio)
        scores[name] = {"precision": float(precision), "recall": float(recall), "f1": float(f1)}
    scores["tolerances"] = {"onset_s": ONSET_TOLERANCE_S, "pitch_cents": PITCH_TOLERANCE_CENTS,
                            "offset_ratio": OFFSET_RATIO, "render_shift_s": shift}
    return scores


def loudness(samples, rate):
    """Integrated loudness in LUFS (ITU-R BS.1770), or None if unmeasurable.

    BS.1770 needs at least 0.4 s of audio and returns -inf for near silence.
    """
    try:
        value = pyloudnorm.Meter(rate).integrated_loudness(samples)
    except ValueError:
        return None
    return float(value) if np.isfinite(value) else None


def listening_copies(folder, reference_path, reference_range, render_path, render_range,
                     rms_gain_db):
    """Write the two selected ranges as new WAVs for A/B listening.

    ``reference-clip.wav`` is the reference range unchanged.
    ``render-level-matched.wav`` is the render range with one gain applied so
    its integrated loudness (LUFS) matches the reference. If loudness cannot
    be measured (clip under 0.4 s or near silence) the overall RMS gain is
    used instead. Both are 32-bit float, so a gain above 0 dB cannot clip in
    the file; the reported peak shows whether playback could. Returns details
    for the report.
    """
    clips = {}
    for label, path, (start, stop) in (("reference", reference_path, reference_range),
                                       ("render", render_path, render_range)):
        rate, samples = read_audio(path)
        clips[label] = (rate, samples[round(start * rate):round(stop * rate)])
    ref_lufs = loudness(clips["reference"][1], clips["reference"][0])
    ren_lufs = loudness(clips["render"][1], clips["render"][0])
    if ref_lufs is not None and ren_lufs is not None:
        method, gain_db = "LUFS", ref_lufs - ren_lufs
    else:
        method, gain_db = "RMS", rms_gain_db
    rate, render = clips["render"]
    matched = render * 10 ** (gain_db / 20)
    soundfile.write(folder / "reference-clip.wav", clips["reference"][1], clips["reference"][0],
                    subtype="FLOAT")
    soundfile.write(folder / "render-level-matched.wav", matched, rate, subtype="FLOAT")
    return {"files": ["reference-clip.wav", "render-level-matched.wav"], "method": method,
            "gain_db": float(gain_db), "reference_lufs": ref_lufs, "render_lufs": ren_lufs,
            "matched_peak": float(np.max(np.abs(matched)))}


def write_midi(path, notes, range_start, program=DEFAULT_MIDI_PROGRAM):
    """Write detected notes as a single-track MIDI file for importing into Dorico.

    Times are seconds from the start of the selected range at the MIDI default
    tempo (120 bpm), so the rhythm still needs quantizing in the notation
    program. Pitches are rounded to the nearest semitone (the exact cents are
    in comparison.json). Velocity follows each note's level relative to the
    loudest note: 100 at the loudest, 2 velocity steps per dB, minimum 20.
    """
    loudest = max(n["rms"] for n in notes)
    midi = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=program)
    for n in notes:
        db = 20 * np.log10(max(n["rms"], 1e-12) / loudest)
        velocity = int(np.clip(round(100 + 2 * db), 20, 127))
        instrument.notes.append(pretty_midi.Note(
            velocity=velocity, pitch=int(np.clip(round(n["pitch"]), 0, 127)),
            start=max(0., n["start"] - range_start), end=max(0., n["end"] - range_start)))
    midi.instruments.append(instrument)
    midi.write(str(path))


def markdown(result, limit):
    """Render the short Markdown summary showing the ``limit`` largest deltas."""

    def priority(row):
        # Unmatched events always sort first; otherwise rank by the largest
        # difference scaled to rough "noticeable" units (50 cents, 100 ms, 6 dB).
        if row["status"] != "matched":
            return float("inf")
        return max(abs(row["pitch_cents"]) / 50, abs(row["onset_ms"] or 0) / 100,
                   abs(row["duration_ms"]) / 100, abs(row["relative_level_db"]) / 6)

    def number(value, digits=1, signed=True):
        return "—" if value is None else format(value, f"{'+' if signed else ''}.{digits}f")

    lines = ["# Audio comparison", "",
             f"- Reference cache hit: {result['reference_cache_hit']}",
             f"- Render offset at first pitch-matched attack: "
             f"{number(result['render_minus_reference_offset_s'], 3)} s",
             f"- Render gain for RMS comparison: {result['render_gain_for_rms_match_db']:+.1f} dB"]
    for label in ("reference", "render"):
        level = result[label]
        lines.append(f"- {label.capitalize()} peak/RMS: {level['peak']:.4f} / {level['rms']:.4f} (full scale)")
    match = result["note_match"]
    lines.append(f"- Note match F1 (mir_eval, ±{ONSET_TOLERANCE_S * 1000:.0f} ms, "
                 f"±{PITCH_TOLERANCE_CENTS:.0f} cents): {match['onset_pitch']['f1']:.2f}; "
                 f"with note ends: {match['onset_pitch_offset']['f1']:.2f}")
    copies = result.get("listening")
    if copies:
        lines.append(f"- Listening copies: {', '.join(copies['files'])} "
                     f"(render gain {copies['gain_db']:+.1f} dB by {copies['method']}, "
                     f"peak {copies['matched_peak']:.2f})")
    if result.get("midi"):
        lines.append(f"- Reference notes as MIDI: {result['midi']}")
    lines.extend(["", "| Reference s | Render s | Pitch cents | Attack ms | Duration ms | Level dB | Status |",
                  "|--:|--:|--:|--:|--:|--:|:--|"])
    for row in sorted(result["events"], key=priority, reverse=True)[:limit]:
        cells = [number(row[key], 3, False) for key in ("reference_s", "render_s")]
        cells += [number(row.get(key)) for key in
                  ("pitch_cents", "onset_ms", "duration_ms", "relative_level_db")]
        cells.append(row["status"] + (" · review" if row.get("review") else ""))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "Deltas are render minus reference. Timing uses a fixed offset. "
                  "Level is RMS-adjusted for comparison. Review flags are heuristic.", "",
                  "Unmatched events describe detector output. Check the audio and score "
                  "before treating them as missing or extra written notes.", ""])
    return "\n".join(lines)


def main():
    """Parse arguments, run the comparison and print the Markdown report path.

    Exits with status 2 and a one-line message on bad input or file errors.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("render", type=Path)
    # Starts default to 0 s; ends default to the end of each file.
    for name in ("reference-start", "reference-end", "render-start", "render-end"):
        parser.add_argument(f"--{name}", type=float, default=0. if name.endswith("start") else None)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--cache", type=Path, default=Path("work/cache"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--no-listening-copy", action="store_true",
                        help="skip writing reference-clip.wav and render-level-matched.wav")
    parser.add_argument("--midi", action="store_true",
                        help="also write the reference's detected notes as reference-notes.mid")
    parser.add_argument("--midi-program", type=int, default=DEFAULT_MIDI_PROGRAM,
                        help="General MIDI program for --midi, 0-127 (default: 73, Flute)")
    args = parser.parse_args()
    try:
        for start, end in ((args.reference_start, args.reference_end), (args.render_start, args.render_end)):
            if not np.isfinite(start) or start < 0 or (end is not None and (not np.isfinite(end) or end <= start)):
                raise ValueError("Ranges require finite seconds with 0 <= start < end")
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        if not 0 <= args.midi_program <= 127:
            raise ValueError("--midi-program must be between 0 and 127")
        reference, hit = analyze(args.reference, args.reference_start, args.reference_end, args.cache)
        rendered, _ = analyze(args.render, args.render_start, args.render_end, args.cache)
        result = compare(reference, rendered)
        result["reference_cache_hit"] = hit
        for label, path, data in (("reference", args.reference, reference), ("render", args.render, rendered)):
            result[label] = {"file": path.name, **{k: data[k] for k in ("range", "peak", "rms", "notes")}}
        args.output.mkdir(parents=True, exist_ok=True)
        # mkdtemp gives every run its own uniquely named folder.
        folder = Path(tempfile.mkdtemp(prefix="comparison-", dir=args.output))
        if not args.no_listening_copy:
            result["listening"] = listening_copies(
                folder, args.reference, reference["range"], args.render, rendered["range"],
                result["render_gain_for_rms_match_db"])
        if args.midi:
            write_midi(folder / "reference-notes.mid", reference["notes"], reference["range"][0],
                       args.midi_program)
            result["midi"] = "reference-notes.mid"
        (folder / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        (folder / "comparison.md").write_text(markdown(result, args.limit), encoding="utf-8")
        print(folder / "comparison.md")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Comparison failed: {error}\n")


if __name__ == "__main__":
    main()
