"""Compare a solo recording with a notation render."""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
from scipy import signal
from scipy.io import wavfile


@dataclass
class Note:
    start: float
    end: float
    pitch: float
    confidence: float
    rms: float


def read_audio(path):
    rate, raw = wavfile.read(path)
    if raw.dtype.kind == "u":
        samples = (raw.astype(float) - 128) / 128
    elif raw.dtype.kind == "i":
        samples = raw.astype(float) / -float(np.iinfo(raw.dtype).min)
    else:
        samples = raw.astype(float)
    if not samples.size or not np.all(np.isfinite(samples)):
        raise ValueError(f"Empty or invalid audio in {path}")
    return rate, samples


def track(mono, rate, start, stop):
    hop = round(rate * .01)
    width = round(rate * .04)
    min_lag, max_lag = max(2, int(rate / 2400)), int(rate / 120)
    clip = mono[round(start * rate):round(stop * rate)]
    if len(clip) < width or not np.any(clip):
        raise ValueError("Selected range is silent or shorter than 40 ms")
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
            power = np.r_[0, np.cumsum(centered**2)]
            lags = np.arange(1, max_lag + 2)
            difference = np.maximum(0, power[width - lags] + power[width] -
                                    power[lags] - 2 * ac[lags])
            curve = np.r_[1., difference * lags / np.maximum(np.cumsum(difference), 1e-15)]
            candidates = signal.find_peaks(-curve)[0]
            candidates = candidates[(candidates >= min_lag) & (candidates <= max_lag)]
            if len(candidates):
                good = candidates[curve[candidates] < .15]
                lag = good[0] if len(good) else candidates[np.argmin(curve[candidates])]
                confidence = float(np.clip(1 - curve[lag], 0, 1))
                if confidence >= .70:
                    left, center, right = curve[lag - 1:lag + 2]
                    delta = .5 * (left - right) / (left - 2 * center + right)
                    pitch = float(69 + 12 * np.log2(rate / (lag + delta) / 440))
        frames.append([start + index / rate, pitch, confidence, rms])
    return frames, hop / rate


def segment(frames, hop, stop):
    notes = []
    group = []
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
    key = hashlib.sha256(f"v1:{start}:{end}".encode())
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
        with target.open("x", encoding="utf-8") as out:
            out.write(encoded)
    except FileExistsError:
        pass
    return data, False


def align(original, render):
    """Global note alignment with insertions and deletions."""
    n, m = len(original), len(render)
    cost = np.zeros((n + 1, m + 1))
    step = np.zeros_like(cost, dtype=np.uint8)
    cost[:, 0], cost[0, :] = np.arange(n + 1), np.arange(m + 1)
    step[1:, 0], step[0, 1:] = 1, 2
    for i, a in enumerate(original, 1):
        for j, b in enumerate(render, 1):
            cents = abs(a.pitch - b.pitch) * 100
            ratio = abs(np.log((b.end - b.start) / (a.end - a.start)))
            penalty = min(1.75, max(0., cents - 35) / 100) + min(.35, ratio * .2)
            choices = (cost[i - 1, j - 1] + penalty,
                       cost[i - 1, j] + 1, cost[i, j - 1] + 1)
            k = min(range(3), key=choices.__getitem__)
            cost[i, j], step[i, j] = choices[k], k
    pairs = []
    while n or m:
        k = step[n, m]
        pairs.append((n - 1 if k != 2 else None, m - 1 if k != 1 else None))
        n -= k != 2
        m -= k != 1
    return pairs[::-1]


def compare(reference, rendered):
    original, render = ([Note(**item) for item in x["notes"]] for x in (reference, rendered))
    pairs = align(original, render)
    anchors = [(i, j) for i, j in pairs if i is not None and j is not None
               and abs(original[i].pitch - render[j].pitch) < .6]
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
            "events": rows}


def markdown(result, limit):
    def priority(row):
        if row["status"] != "matched":
            return 10
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
    lines.extend(["", "| Reference s | Render s | Pitch cents | Attack ms | Duration ms | Level dB | Status |",
                  "|--:|--:|--:|--:|--:|--:|:--|"])
    for row in sorted(result["events"], key=priority, reverse=True)[:limit]:
        cells = [number(row[key], 3, False) for key in ("reference_s", "render_s")]
        cells += [number(row.get(key)) for key in
                  ("pitch_cents", "onset_ms", "duration_ms", "relative_level_db")]
        cells.append(row["status"] + (" · review" if row.get("review") else ""))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "Deltas are render minus reference. Timing uses a fixed offset. "
                  "Level is RMS-adjusted for comparison. Review flags are heuristic.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("render", type=Path)
    for name in ("reference-start", "reference-end", "render-start", "render-end"):
        parser.add_argument(f"--{name}", type=float, default=0. if name.endswith("start") else None)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--cache", type=Path, default=Path("work/cache"))
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    try:
        for start, end in ((args.reference_start, args.reference_end), (args.render_start, args.render_end)):
            if not np.isfinite(start) or start < 0 or (end is not None and (not np.isfinite(end) or end <= start)):
                raise ValueError("Ranges require finite seconds with 0 <= start < end")
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        reference, hit = analyze(args.reference, args.reference_start, args.reference_end, args.cache)
        rendered, _ = analyze(args.render, args.render_start, args.render_end, args.cache)
        result = compare(reference, rendered)
        result["reference_cache_hit"] = hit
        for label, path, data in (("reference", args.reference, reference), ("render", args.render, rendered)):
            result[label] = {"file": path.name, **{k: data[k] for k in ("range", "peak", "rms", "notes")}}
        args.output.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="comparison-", dir=args.output))
        (folder / "comparison.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        (folder / "comparison.md").write_text(markdown(result, args.limit), encoding="utf-8")
        print(folder / "comparison.md")
    except (OSError, ValueError) as error:
        parser.exit(2, f"Comparison failed: {error}\n")


if __name__ == "__main__":
    main()
