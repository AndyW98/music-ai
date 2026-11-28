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
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
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

# A matched note is flagged for review below this tracker confidence.
REVIEW_CONFIDENCE = .85

# Event maps (--event-map): a detected render note is the written event when
# its attack is within 100 ms and its pitch within 50 cents. The detector check
# calls a matched note a boundary error when its attack is more than 30 ms, or
# its end more than 100 ms, from the written event.
MAP_ONSET_TOLERANCE_S = .1
MAP_PITCH_TOLERANCE_CENTS = 50.
BOUNDARY_ONSET_MS = 30.
BOUNDARY_OFFSET_MS = 100.

# Excerpts (--excerpts) run from the previous matched pair to the next one,
# plus this much padding on each side.
EXCERPT_PAD_S = .25


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


def side_fields(prefix, note, index):
    """Detected-note details for one side of an event row (``None`` when absent)."""
    return {f"{prefix}_note": None if index is None else int(index),
            f"{prefix}_end_s": note.end if note else None,
            f"{prefix}_pitch": note.pitch if note else None,
            f"{prefix}_confidence": note.confidence if note else None}


def compare(reference, rendered, event_map=None):
    """Measure render-minus-reference differences for every aligned pair.

    Timing is made relative to the first matched pair whose pitches agree
    within 60 cents, so a constant lead-in difference is removed. Levels are
    compared after applying the gain that matches the two clips' overall RMS.

    Every event row carries an ``id`` (its position in musical order), the
    detected start, end, pitch and confidence on both sides, the index of each
    note in the analysis' ``notes`` list, and ``reasons`` explaining any review
    flag. With ``event_map`` (from ``read_event_map``), rows also say which
    written event they correspond to; see ``trace``.
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
        row = {"reference_s": a.start if a else None, "render_s": b.start if b else None,
               **side_fields("reference", a, i), **side_fields("render", b, j)}
        if a is None or b is None:
            row["status"] = "extra render event" if a is None else "unmatched reference event"
            row["reasons"] = ["no detected reference event" if a is None
                              else "no detected render event"]
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
            reasons = []
            if repeated:
                reasons.append("a neighbouring note has the same pitch, so the pairing may have slipped")
            if abs(cents) >= 60:
                reasons.append("pitches differ by 60 cents or more")
            if min(a.confidence, b.confidence) < REVIEW_CONFIDENCE:
                reasons.append(f"tracker confidence below {REVIEW_CONFIDENCE:.2f}")
            row.update(status="matched", pitch_cents=cents,
                       onset_ms=None if shift is None else (b.start - a.start - shift) * 1000,
                       duration_ms=((b.end - b.start) - (a.end - a.start)) * 1000,
                       relative_level_db=float(20 * np.log10(b.rms / a.rms) + gain),
                       reasons=reasons)
        rows.append(row)
    result = {"render_minus_reference_offset_s": shift, "render_gain_for_rms_match_db": gain,
              "note_match": note_scores(original, render, shift or 0.)}
    if event_map is not None:
        matches = match_written(render, event_map)
        rows = trace(rows, event_map, matches, shift)
        result["detector_check"] = check_detector(render, event_map, matches)
    for number, row in enumerate(rows, 1):
        row["id"] = number
        row.setdefault("written", None)
        row.setdefault("written_status", "no event map")
        if row["status"] == "matched":
            row["review"] = bool(row["reasons"])
    result["events"] = rows
    return result


# --------------------------------------------------------------------------- event maps


def parse_pitch(text):
    """A MIDI number (``69``, ``69.25``) or a note name (``A4``, ``C#5``, ``Bb3``)."""
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return float(pretty_midi.note_name_to_number(text))


def optional(text, kind=float):
    """Parse an optional CSV cell: blank means ``None``."""
    text = (text or "").strip()
    return kind(text) if text else None


def csv_events(path):
    """Note events from a CSV with ``time_s`` and ``pitch`` columns (see ``read_event_map``)."""
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames or []]
        if not {"time_s", "pitch"} <= set(reader.fieldnames):
            raise ValueError(f"Event map {path.name} needs time_s and pitch columns")
        events = []
        for line, row in enumerate(reader, 2):
            try:
                time, pitch = float(row["time_s"]), parse_pitch(row["pitch"] or "")
                duration = optional(row.get("duration_s"))
                bar, beat = optional(row.get("bar"), int), optional(row.get("beat"))
                if not np.isfinite(time) or time < 0:
                    raise ValueError("time_s must be 0 or more")
                if duration is not None and not (np.isfinite(duration) and duration > 0):
                    raise ValueError("duration_s must be more than 0")
                if not 0 <= pitch <= 127:
                    raise ValueError("pitch must be between 0 and 127")
            except (TypeError, ValueError) as error:
                raise ValueError(f"Event map {path.name} line {line}: {error}") from None
            events.append({"time_s": time, "end_s": None if duration is None else time + duration,
                           "pitch": pitch, "bar": bar, "beat": beat,
                           "part": optional(row.get("part"), str),
                           "voice": optional(row.get("voice"), str), "source": f"line {line}"})
    return events


def bar_beat(time, beats, downbeats):
    """Bar (from 1) and fractional beat (from 1) of ``time`` given pretty_midi beat grids."""
    if not len(downbeats) or time < downbeats[0]:
        return None, None
    bar = int(np.searchsorted(downbeats, time + 1e-6, side="right"))
    index = int(np.searchsorted(beats, time + 1e-6, side="right")) - 1
    first = int(np.searchsorted(beats, downbeats[bar - 1] - 1e-6))
    step = beats[index + 1] - beats[index] if index + 1 < len(beats) else (
        beats[index] - beats[index - 1] if index else 0)
    fraction = (time - beats[index]) / step if step else 0.
    return bar, round(index - first + 1 + fraction, 3)


def midi_events(path):
    """Note events from a MIDI file, e.g. a Dorico MIDI export (see ``read_event_map``)."""
    try:
        midi = pretty_midi.PrettyMIDI(str(path))
    except Exception as error:  # mido and pretty_midi raise many types for bad files
        raise ValueError(f"Cannot read MIDI event map {path.name}: {error}") from error
    beats, downbeats = midi.get_beats(), midi.get_downbeats()
    events = []
    for number, instrument in enumerate(midi.instruments, 1):
        if instrument.is_drum:
            continue
        part = instrument.name.strip() or f"Track {number}"
        for count, n in enumerate(sorted(instrument.notes, key=lambda n: n.start), 1):
            bar, beat = bar_beat(n.start, beats, downbeats)
            events.append({"time_s": float(n.start), "end_s": float(n.end), "pitch": float(n.pitch),
                           "bar": bar, "beat": beat, "part": part, "voice": None,
                           "source": f"{part} note {count}"})
    return events


def read_event_map(path, offset=0.):
    """Read the written note events of the render, for tracing and checking.

    ``path`` is a CSV file or a MIDI file (``.mid``/``.midi``). A CSV needs
    ``time_s`` (seconds from the start of the render file) and ``pitch`` (a
    MIDI number or a note name such as ``C#5``) and may add ``duration_s``,
    ``bar``, ``beat``, ``part`` and ``voice``. A MIDI file supplies times,
    pitches and durations; bar and beat come from its tempo and time
    signatures, the part from the track name, and the voice is unknown.
    ``offset`` seconds are added to every time. Returns events sorted by time.
    """
    path = Path(path)
    events = midi_events(path) if path.suffix.lower() in (".mid", ".midi") else csv_events(path)
    if not events:
        raise ValueError(f"No note events in event map {path.name}")
    for event in events:
        event["time_s"] += offset
        if event["end_s"] is not None:
            event["end_s"] += offset
    return sorted(events, key=lambda e: (e["time_s"], e["pitch"]))


def hertz(pitches):
    return 440. * 2 ** ((np.asarray(pitches, dtype=float) - 69) / 12)


def match_written(notes, events):
    """Pair detected notes with written events: ``{note_index: event_index}``.

    Uses mir_eval's optimal note matching with attacks within 100 ms and
    pitches within 50 cents. Note ends are ignored.
    """
    if not notes or not events:
        return {}
    written = np.array([[e["time_s"], max(e["end_s"] or 0, e["time_s"] + .05)] for e in events])
    detected = np.array([[n.start, n.end] for n in notes])
    pairs = mir_eval.transcription.match_notes(
        written, hertz([e["pitch"] for e in events]), detected, hertz([n.pitch for n in notes]),
        onset_tolerance=MAP_ONSET_TOLERANCE_S, pitch_tolerance=MAP_PITCH_TOLERANCE_CENTS,
        offset_ratio=None)
    return {int(j): int(k) for k, j in pairs}


def trace(rows, events, matches, shift):
    """Attach the corresponding written event to each comparison row.

    ``written_status`` is ``"mapped"`` when a written event is found and
    ``"no mapped written event"`` otherwise. A row with a render detection
    uses that detection's match. A reference event with no detected render
    event looks for an unused written event at the same pitch (within 50
    cents) between the neighbouring render detections; if there is one, the
    note is written but was not detected in the render. Written events left
    over become rows with status ``"undetected written event"``, placed in
    musical order. Returns the new row list.
    """
    used = set(matches.values())
    for row in rows:
        if row["render_note"] is not None:
            k = matches.get(row["render_note"])
            row["written"] = dict(events[k]) if k is not None else None
    for index, row in enumerate(rows):
        if row["render_note"] is not None:
            continue
        before = next((r for r in reversed(rows[:index]) if r["render_s"] is not None), None)
        after = next((r for r in rows[index + 1:] if r["render_s"] is not None), None)
        pair = next((r for r in reversed(rows[:index]) if r["status"] == "matched"), None)
        offset = pair["render_s"] - pair["reference_s"] if pair else shift or 0.
        row["expected_render_s"] = row["reference_s"] + offset
        low = before["render_s"] if before else -np.inf
        high = after["render_s"] if after else np.inf
        candidates = [k for k, e in enumerate(events) if k not in used and low < e["time_s"] < high
                      and abs(e["pitch"] - row["reference_pitch"]) * 100 <= MAP_PITCH_TOLERANCE_CENTS]
        if candidates:
            k = min(candidates, key=lambda k: abs(events[k]["time_s"] - row["expected_render_s"]))
            used.add(k)
            row["written"] = dict(events[k])
        else:
            row["written"] = None
    for row in rows:
        row["written_status"] = "mapped" if row["written"] else "no mapped written event"
        if row["status"] == "matched" and not row["written"]:
            row["reasons"].append("render detection has no mapped written event")
        elif row["status"] == "unmatched reference event" and row["written"]:
            row["reasons"] = ["written event with no detected render event"]
    for k, event in enumerate(events):
        if k in used:
            continue
        written_only = {"reference_s": None, "render_s": None,
                        **side_fields("reference", None, None), **side_fields("render", None, None),
                        "expected_render_s": event["time_s"], "status": "undetected written event",
                        "reasons": ["written event with no detected event on either side"],
                        "written": dict(event), "written_status": "mapped"}
        position = sum(1 for r in rows if render_position(r) <= event["time_s"])
        rows.insert(position, written_only)
    return rows


def render_position(row):
    """Render-file time of a row: the detection, else its expected position."""
    value = row["render_s"] if row["render_s"] is not None else row.get("expected_render_s")
    return -np.inf if value is None else value


def check_detector(notes, events, matches):
    """Score detected render notes against the written events they should show.

    Returns counts and an ``issues`` list in time order. Kinds: ``missed``
    (a written event with no detection), ``merged`` (a written event inside a
    detection matched to another event, e.g. a legato repeated note),
    ``extra`` (a detection with no written event), ``split`` (a detection
    inside a written event already matched, e.g. a note broken in two) and
    ``boundary`` (a matched detection whose attack is more than 30 ms or whose
    end is more than 100 ms from the written event).
    """
    by_event = {k: j for j, k in matches.items()}

    def same(a, b):
        return abs(a - b) * 100 <= MAP_PITCH_TOLERANCE_CENTS

    def end(k):
        later = [e["time_s"] for e in events[k + 1:] if e["time_s"] > events[k]["time_s"]]
        return events[k]["end_s"] or (later[0] if later else np.inf)

    def issue(kind, k=None, j=None, **extra):
        note = notes[j] if j is not None else None
        return {"kind": kind, "written": dict(events[k]) if k is not None else None,
                "detection": j, "detection_s": note.start if note else None,
                "detection_end_s": note.end if note else None,
                "detection_pitch": note.pitch if note else None, **extra}

    issues, onsets, offsets = [], [], []
    for k, j in sorted(by_event.items()):
        onset = (notes[j].start - events[k]["time_s"]) * 1000
        offset = None if events[k]["end_s"] is None else (notes[j].end - events[k]["end_s"]) * 1000
        onsets.append(onset)
        if offset is not None:
            offsets.append(offset)
        if abs(onset) > BOUNDARY_ONSET_MS or (offset is not None and abs(offset) > BOUNDARY_OFFSET_MS):
            issues.append(issue("boundary", k, j, onset_ms=onset, offset_ms=offset))
    for k, event in enumerate(events):
        if k not in by_event:
            host = next((j for j, n in enumerate(notes) if j in matches and
                         n.start < event["time_s"] < n.end and same(n.pitch, event["pitch"])), None)
            issues.append(issue("merged" if host is not None else "missed", k, host))
    for j, n in enumerate(notes):
        if j not in matches:
            host = next((k for k in by_event if events[k]["time_s"] < n.start < end(k)
                         and same(n.pitch, events[k]["pitch"])), None)
            issues.append(issue("split" if host is not None else "extra", host, j))

    def when(item):
        written = item["written"]["time_s"] if item["written"] else np.inf
        return min(written, item["detection_s"] if item["detection_s"] is not None else np.inf)

    issues.sort(key=when)
    kinds = [item["kind"] for item in issues]
    matched = len(by_event)
    precision = matched / len(notes) if notes else 0.
    recall = matched / len(events) if events else 0.
    return {"written_events": len(events), "detections": len(notes), "matched": matched,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if matched else 0.,
            "false_negatives": kinds.count("missed") + kinds.count("merged"),
            "false_positives": kinds.count("extra") + kinds.count("split"),
            **{f"{kind}_count": kinds.count(kind) for kind in ("missed", "merged", "extra", "split", "boundary")},
            "median_onset_ms": float(np.median(onsets)) if onsets else None,
            "median_offset_ms": float(np.median(offsets)) if offsets else None,
            "tolerances": {"onset_s": MAP_ONSET_TOLERANCE_S, "pitch_cents": MAP_PITCH_TOLERANCE_CENTS,
                           "boundary_onset_ms": BOUNDARY_ONSET_MS,
                           "boundary_offset_ms": BOUNDARY_OFFSET_MS},
            "issues": issues}


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


def level_match(reference_path, reference_range, render_path, render_range, rms_gain_db):
    """Load both selected ranges and choose the render gain for listening.

    The gain matches integrated loudness (LUFS). If loudness cannot be
    measured (clip under 0.4 s or near silence) the overall RMS gain is used
    instead. Returns ``(clips, info)``, where ``clips`` maps ``"reference"``
    and ``"render"`` to ``(rate, samples)``.
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
    return clips, {"method": method, "gain_db": float(gain_db),
                   "reference_lufs": ref_lufs, "render_lufs": ren_lufs}


def listening_copies(folder, reference_path, reference_range, render_path, render_range,
                     rms_gain_db):
    """Write the two selected ranges as new WAVs for A/B listening.

    ``reference-clip.wav`` is the reference range unchanged.
    ``render-level-matched.wav`` is the render range with the gain from
    ``level_match`` applied. Both are 32-bit float, so a gain above 0 dB
    cannot clip in the file; the reported peak shows whether playback could.
    Returns details for the report.
    """
    clips, info = level_match(reference_path, reference_range, render_path, render_range,
                              rms_gain_db)
    rate, render = clips["render"]
    matched = render * 10 ** (info["gain_db"] / 20)
    soundfile.write(folder / "reference-clip.wav", clips["reference"][1], clips["reference"][0],
                    subtype="FLOAT")
    soundfile.write(folder / "render-level-matched.wav", matched, rate, subtype="FLOAT")
    return {"files": ["reference-clip.wav", "render-level-matched.wav"], **info,
            "matched_peak": float(np.max(np.abs(matched)))}


def excerpt_windows(rows, index, shift):
    """Reference and render time spans giving one event the same musical context.

    Each span runs from the start of the previous matched pair to the end of
    the next one, so both sides cover the same notes. Without a neighbouring
    pair, the event itself is used; a missing side is estimated from the
    other side (or, for the render, the expected or written position) and the
    constant offset. Padding and clamping are left to the caller.
    """
    row = rows[index]
    shift = shift or 0.
    before = next((r for r in reversed(rows[:index]) if r["status"] == "matched"), None)
    after = next((r for r in rows[index + 1:] if r["status"] == "matched"), None)

    def start(r, side):
        if r[f"{side}_s"] is not None:
            return r[f"{side}_s"]
        if side == "render":
            expected = r.get("expected_render_s")
            return expected if expected is not None else r["reference_s"] + shift
        estimate = r["render_s"] if r["render_s"] is not None else r.get("expected_render_s")
        return estimate - shift

    def end(r, side):
        if r[f"{side}_end_s"] is not None:
            return r[f"{side}_end_s"]
        other = "reference" if side == "render" else "render"
        length = (r[f"{other}_end_s"] - r[f"{other}_s"]) if r[f"{other}_s"] is not None else None
        if length is None and r.get("written") and r["written"]["end_s"] is not None:
            length = r["written"]["end_s"] - r["written"]["time_s"]
        return start(r, side) + (length or .3)

    return {side: (start(before or row, side), end(after or row, side))
            for side in ("reference", "render")}


def write_excerpts(folder, rows, ids, paths, ranges, gain, shift):
    """Write short reference and level-matched render clips for the ``ids`` rows.

    Files go in ``excerpts/`` as ``event-NNN-reference.wav`` and
    ``event-NNN-render.wav`` (32-bit float). The render clip gets the same
    gain as the listening copy (``gain`` is ``level_match`` info). Each row
    gains an ``excerpt`` entry with the files, their source time ranges in
    seconds from the start of each file, and the gain applied.
    """
    audio = {side: read_audio(path) for side, path in paths.items()}
    (folder / "excerpts").mkdir()
    for index, row in enumerate(rows):
        if row["id"] not in ids:
            continue
        info = {"render_gain_db": gain["gain_db"], "gain_method": gain["method"]}
        for side, (start, stop) in excerpt_windows(rows, index, shift).items():
            low, high = ranges[side]
            start, stop = max(low, start - EXCERPT_PAD_S), min(high, stop + EXCERPT_PAD_S)
            rate, samples = audio[side]
            clip = samples[round(start * rate):round(stop * rate)]
            if stop - start < .01 or not len(clip):
                info[side] = None  # the context lies outside the selected range
                continue
            if side == "render":
                clip = clip * 10 ** (gain["gain_db"] / 20)
            name = f"excerpts/event-{row['id']:03d}-{side}.wav"
            soundfile.write(folder / name, clip, rate, subtype="FLOAT")
            info[side] = {"file": name, "range_s": [float(start), float(stop)]}
        row["excerpt"] = info


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


def priority(row):
    """Sort key for "largest difference first".

    Events without a pair always come first; matched notes rank by their
    largest difference scaled to rough "noticeable" units (50 cents, 100 ms
    of attack or duration, 6 dB).
    """
    if row["status"] != "matched":
        return float("inf")
    return max(abs(row["pitch_cents"]) / 50, abs(row["onset_ms"] or 0) / 100,
               abs(row["duration_ms"]) / 100, abs(row["relative_level_db"]) / 6)


def selected_flags(events, limit):
    """Ids of up to ``limit`` flagged events (unpaired or ``review``), largest first."""
    flagged = [row for row in events if row["status"] != "matched" or row.get("review")]
    return {row["id"] for row in sorted(flagged, key=priority, reverse=True)[:limit]}


def note_label(pitch, confidence=None):
    """``A4 +12¢`` (optionally with confidence), or ``—`` when there is no note."""
    if pitch is None:
        return "—"
    semitone = int(round(pitch))
    text = f"{pretty_midi.note_number_to_name(semitone)} {(pitch - semitone) * 100:+.0f}¢"
    return text if confidence is None else f"{text} ({confidence:.2f})"


def location(written):
    """Human-readable position of a written event, e.g. ``bar 3 beat 2 · Flute · voice 1``."""
    if not written:
        return "—"
    parts = []
    if written.get("bar") is not None:
        beat = written.get("beat")
        parts.append(f"bar {written['bar']}" + (f" beat {beat:g}" if beat is not None else ""))
    else:
        parts.append(f"{written['time_s']:.3f} s")
    parts += [value for value in (written.get("part"),) if value]
    if written.get("voice"):
        parts.append(f"voice {written['voice']}")
    return " · ".join(parts)


def number(value, digits=1, signed=True):
    return "—" if value is None else format(value, f"{'+' if signed else ''}.{digits}f")


def detector_lines(check, limit=None):
    """Markdown lines summarising a ``check_detector`` result and its issues."""
    lines = [f"- Written events: {check['written_events']}; render detections: "
             f"{check['detections']}; matched: {check['matched']}",
             f"- Precision {check['precision']:.2f}, recall {check['recall']:.2f}, "
             f"F1 {check['f1']:.2f} (attack ±{MAP_ONSET_TOLERANCE_S * 1000:.0f} ms, "
             f"pitch ±{MAP_PITCH_TOLERANCE_CENTS:.0f} cents)",
             f"- False negatives: {check['false_negatives']} ({check['missed_count']} missed, "
             f"{check['merged_count']} merged); false positives: {check['false_positives']} "
             f"({check['extra_count']} extra, {check['split_count']} split)",
             f"- Boundary errors (attack over {BOUNDARY_ONSET_MS:.0f} ms or end over "
             f"{BOUNDARY_OFFSET_MS:.0f} ms): {check['boundary_count']}; median attack "
             f"{number(check['median_onset_ms'])} ms, median end {number(check['median_offset_ms'])} ms"]
    issues = check["issues"][:limit] if limit else check["issues"]
    if issues:
        lines += ["", "| Kind | Written | Written s | Detected s | Detected note | Attack ms | End ms |",
                  "|:--|:--|--:|--:|:--|--:|--:|"]
        for item in issues:
            written = item["written"]
            lines.append("| " + " | ".join([
                item["kind"], location(written),
                number(written["time_s"] if written else None, 3, False),
                number(item["detection_s"], 3, False), note_label(item["detection_pitch"]),
                number(item.get("onset_ms")), number(item.get("offset_ms"))]) + " |")
        if limit and len(check["issues"]) > limit:
            lines.append(f"\n{len(check['issues']) - limit} more issues are in the JSON.")
    return lines


def side_text(row, side):
    """One line describing the detected note on ``side`` of an event row."""
    if row[f"{side}_s"] is None:
        expected = row.get("expected_render_s") if side == "render" else None
        return f"no detected {side} event" + (
            f" (expected near {expected:.3f} s)" if expected is not None else "")
    return (f"{row[f'{side}_s']:.3f}–{row[f'{side}_end_s']:.3f} s, "
            f"{note_label(row[f'{side}_pitch'])}, confidence {row[f'{side}_confidence']:.2f}")


def flagged_lines(result, limit):
    """The chronological "Flagged events" section with excerpt links."""
    ids = selected_flags(result["events"], limit)
    if not ids:
        return []
    lines = ["", "## Flagged events in musical order", ""]
    for row in result["events"]:
        if row["id"] not in ids:
            continue
        lines.append(f"**Event {row['id']}** · {row['status']}")
        lines.append(f"- Reference: {side_text(row, 'reference')}")
        lines.append(f"- Render: {side_text(row, 'render')}")
        if row["written_status"] != "no event map":
            written = (f"{location(row['written'])}, {note_label(row['written']['pitch'])} "
                       f"({row['written']['source']})" if row["written"] else row["written_status"])
            lines.append(f"- Written: {written}")
        if row.get("reasons"):
            lines.append(f"- Why: {'; '.join(row['reasons'])}")
        excerpt = row.get("excerpt")
        if excerpt:
            links = [f"[{side}]({clip['file']}) {clip['range_s'][0]:.2f}–{clip['range_s'][1]:.2f} s"
                     for side, clip in ((s, excerpt[s]) for s in ("reference", "render")) if clip]
            lines.append(f"- Listen: {' · '.join(links)} (render gain "
                         f"{excerpt['render_gain_db']:+.1f} dB by {excerpt['gain_method']})")
        lines.append("")
    return lines[:-1]


def markdown(result, limit):
    """Render the Markdown summary: header, the ``limit`` largest deltas and flagged events."""
    mapped = "event_map" in result
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
    if mapped:
        event_map = result["event_map"]
        lines.append(f"- Event map: {event_map['file']} ({len(event_map['events'])} written events, "
                     f"offset {event_map['offset_s']:+.3f} s)")
    header = "| # | Reference s | Render s | Reference note | Render note | Pitch cents | Attack ms | Duration ms | Level dB |"
    rule = "|--:|--:|--:|:--|:--|--:|--:|--:|--:|"
    if mapped:
        header, rule = header + " Written |", rule + ":--|"
    lines.extend(["", header + " Status |", rule + ":--|"])
    for row in sorted(result["events"], key=priority, reverse=True)[:limit]:
        cells = [str(row["id"])]
        cells += [number(row[key], 3, False) for key in ("reference_s", "render_s")]
        cells += [note_label(row.get(f"{side}_pitch")) for side in ("reference", "render")]
        cells += [number(row.get(key)) for key in
                  ("pitch_cents", "onset_ms", "duration_ms", "relative_level_db")]
        if mapped:
            cells.append(location(row["written"]) if row["written"] else row["written_status"])
        cells.append(row["status"] + (" · review" if row.get("review") else ""))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(flagged_lines(result, limit))
    if result.get("detector_check"):
        lines.extend(["", "## Detector check (render against the event map)", "",
                      *detector_lines(result["detector_check"], limit)])
    lines.extend(["", "Deltas are render minus reference. Timing uses a fixed offset. "
                  "Level is RMS-adjusted for comparison. Review flags are heuristic.", "",
                  "Unmatched events describe detector output. Check the audio and score "
                  "before treating them as missing or extra written notes.", ""])
    return "\n".join(lines)


def check_markdown(result):
    """Markdown report for ``compare.py check``."""
    return "\n".join(["# Detector check", "",
                      f"- Render: {result['render']['file']} "
                      f"({result['render']['range'][0]:.3f}–{result['render']['range'][1]:.3f} s)",
                      f"- Event map: {result['event_map']['file']} "
                      f"(offset {result['event_map']['offset_s']:+.3f} s)",
                      *detector_lines(result["detector_check"]), "",
                      "Missed and merged events are false negatives; extra and split detections "
                      "are false positives. Listen to the render before changing the detector "
                      "or the score.", ""])


def check_ranges(*ranges):
    for start, end in ranges:
        if not np.isfinite(start) or start < 0 or (end is not None and (not np.isfinite(end) or end <= start)):
            raise ValueError("Ranges require finite seconds with 0 <= start < end")


def new_folder(output, prefix):
    output.mkdir(parents=True, exist_ok=True)
    # mkdtemp gives every run its own uniquely named folder.
    return Path(tempfile.mkdtemp(prefix=prefix, dir=output))


def check_main(argv):
    """``compare.py check RENDER EVENTS``: score the detector on a render with known notes."""
    parser = argparse.ArgumentParser(
        prog="compare.py check",
        description="Check the note detector on a render against its known written events.")
    parser.add_argument("render", type=Path)
    parser.add_argument("event_map", type=Path, metavar="events",
                        help="CSV (time_s, pitch, ...) or MIDI file of the written notes")
    parser.add_argument("--render-start", type=float, default=0.)
    parser.add_argument("--render-end", type=float)
    parser.add_argument("--event-map-offset", type=float, default=0.)
    parser.add_argument("--cache", type=Path, default=Path("work/cache"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args(argv)
    try:
        check_ranges((args.render_start, args.render_end))
        events = read_event_map(args.event_map, args.event_map_offset)
        data, _ = analyze(args.render, args.render_start, args.render_end, args.cache)
        notes = [Note(**item) for item in data["notes"]]
        result = {"render": {"file": args.render.name, **{k: data[k] for k in ("range", "notes")}},
                  "event_map": {"file": args.event_map.name, "offset_s": args.event_map_offset,
                                "events": events},
                  "detector_check": check_detector(notes, events, match_written(notes, events))}
        folder = new_folder(args.output, "detector-check-")
        (folder / "detector-check.json").write_text(json.dumps(result, indent=2, allow_nan=False),
                                                    encoding="utf-8")
        (folder / "detector-check.md").write_text(check_markdown(result), encoding="utf-8")
        print(folder / "detector-check.md")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Detector check failed: {error}\n")


def main(argv=None):
    """Parse arguments, run the comparison and print the Markdown report path.

    ``compare.py check …`` runs ``check_main`` instead. Exits with status 2
    and a one-line message on bad input or file errors.
    """
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["check"]:
        return check_main(argv[1:])
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Run 'compare.py check RENDER EVENTS' to score the note detector on a "
               "render against its known written notes.")
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
    parser.add_argument("--excerpts", action="store_true",
                        help="write short level-matched clips for each flagged event in the report")
    parser.add_argument("--event-map", type=Path,
                        help="CSV or MIDI file of the render's written notes, to locate events "
                             "by bar, beat, part and voice")
    parser.add_argument("--event-map-offset", type=float, default=0.,
                        help="seconds added to every event-map time (default: 0)")
    parser.add_argument("--midi", action="store_true",
                        help="also write the reference's detected notes as reference-notes.mid")
    parser.add_argument("--midi-program", type=int, default=DEFAULT_MIDI_PROGRAM,
                        help="General MIDI program for --midi, 0-127 (default: 73, Flute)")
    args = parser.parse_args(argv)
    try:
        check_ranges((args.reference_start, args.reference_end), (args.render_start, args.render_end))
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        if not 0 <= args.midi_program <= 127:
            raise ValueError("--midi-program must be between 0 and 127")
        if not np.isfinite(args.event_map_offset):
            raise ValueError("--event-map-offset must be a finite number of seconds")
        events = read_event_map(args.event_map, args.event_map_offset) if args.event_map else None
        reference, hit = analyze(args.reference, args.reference_start, args.reference_end, args.cache)
        rendered, _ = analyze(args.render, args.render_start, args.render_end, args.cache)
        result = compare(reference, rendered, events)
        result["reference_cache_hit"] = hit
        for label, path, data in (("reference", args.reference, reference), ("render", args.render, rendered)):
            result[label] = {"file": path.name, **{k: data[k] for k in ("range", "peak", "rms", "notes")}}
        if events is not None:
            result["event_map"] = {"file": args.event_map.name, "offset_s": args.event_map_offset,
                                   "events": events}
        folder = new_folder(args.output, "comparison-")
        if not args.no_listening_copy:
            result["listening"] = listening_copies(
                folder, args.reference, reference["range"], args.render, rendered["range"],
                result["render_gain_for_rms_match_db"])
        if args.excerpts:
            gain = result.get("listening") or level_match(
                args.reference, reference["range"], args.render, rendered["range"],
                result["render_gain_for_rms_match_db"])[1]
            write_excerpts(folder, result["events"], selected_flags(result["events"], args.limit),
                           {"reference": args.reference, "render": args.render},
                           {"reference": reference["range"], "render": rendered["range"]},
                           gain, result["render_minus_reference_offset_s"])
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
