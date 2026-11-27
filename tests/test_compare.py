"""Unit and end-to-end tests for compare.py using synthetic sample audio."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

import compare
from compare import Note
from tests import sample_audio as sa

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tone(freq, seconds=.5, rate=sa.RATE, amp=.5):
    t = np.arange(int(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * freq * t)


def note(start, end, pitch, confidence=.95, rms=.1):
    return Note(start, end, pitch, confidence, rms)


def as_data(notes, rms=.1, peak=.5):
    """Shape a note list like the output of ``analyze`` for ``compare``."""
    return {"rms": rms, "peak": peak, "notes": [vars(n) for n in notes]}


@pytest.fixture
def pair(tmp_path):
    return sa.make_pair(tmp_path / "audio")


# --------------------------------------------------------------------------- read_audio


class TestReadAudio:
    def test_int16_is_scaled_to_full_scale(self, tmp_path):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, np.array([-32768, 0, 16384], dtype=np.int16))
        rate, samples = compare.read_audio(path)
        assert rate == 8000
        np.testing.assert_allclose(samples, [-1.0, 0.0, .5])

    def test_int32_is_scaled_to_full_scale(self, tmp_path):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, np.array([-2**31, 2**30], dtype=np.int32))
        np.testing.assert_allclose(compare.read_audio(path)[1], [-1.0, .5])

    def test_uint8_is_centred_on_128(self, tmp_path):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, np.array([0, 128, 192], dtype=np.uint8))
        np.testing.assert_allclose(compare.read_audio(path)[1], [-1.0, 0.0, .5])

    def test_float_is_unchanged(self, tmp_path):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, np.array([-.25, .75], dtype=np.float32))
        np.testing.assert_allclose(compare.read_audio(path)[1], [-.25, .75])

    def test_stereo_keeps_channel_axis(self, tmp_path):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, np.zeros((10, 2), dtype=np.int16))
        assert compare.read_audio(path)[1].shape == (10, 2)

    @pytest.mark.parametrize("data", [np.array([0., np.nan], dtype=np.float32),
                                      np.array([np.inf], dtype=np.float32),
                                      np.zeros(0, dtype=np.int16)])
    def test_invalid_or_empty_audio_is_rejected(self, tmp_path, data):
        path = tmp_path / "a.wav"
        wavfile.write(path, 8000, data)
        with pytest.raises(ValueError, match="Empty or invalid"):
            compare.read_audio(path)


# --------------------------------------------------------------------------- track


class TestTrack:
    @pytest.mark.parametrize("freq", [130.81, 220., 440., 880., 1760.])
    def test_pure_tone_pitch_within_two_cents(self, freq):
        frames, hop = compare.track(tone(freq), sa.RATE, 0., .5)
        pitches = [f[1] for f in frames if f[1] is not None]
        expected = 69 + 12 * np.log2(freq / 440)
        assert hop == pytest.approx(.01)
        assert len(pitches) > 40
        assert abs(np.median(pitches) - expected) * 100 < 2

    def test_detuned_harmonic_tone(self):
        samples = sa.synth([(0, .5, 72.25, 1)], .5)
        frames, _ = compare.track(samples, sa.RATE, 0., .5)
        pitches = [f[1] for f in frames if f[1] is not None]
        assert np.median(pitches) == pytest.approx(72.25, abs=.02)

    def test_frame_times_start_at_range_start(self):
        signal = np.r_[np.zeros(sa.RATE), tone(440)]
        frames, _ = compare.track(signal, sa.RATE, 1., 1.5)
        assert frames[0][0] == pytest.approx(1.)
        assert frames[1][0] == pytest.approx(1.01)
        assert len(frames) == 50

    def test_quiet_frames_have_no_pitch(self):
        signal = np.r_[np.zeros(sa.RATE // 4), tone(440, .25)]
        frames, _ = compare.track(signal, sa.RATE, 0., .5)
        assert all(f[1] is None and f[2] == 0 for f in frames[:20])
        assert frames[-5][1] is not None

    def test_silence_is_rejected(self):
        with pytest.raises(ValueError, match="silent"):
            compare.track(np.zeros(sa.RATE), sa.RATE, 0., 1.)

    def test_range_shorter_than_window_is_rejected(self):
        with pytest.raises(ValueError, match="shorter than 40 ms"):
            compare.track(tone(440), sa.RATE, 0., .02)


# --------------------------------------------------------------------------- segment


def frames_for(pitches, hop=.01, start=0.):
    return [[start + k * hop, p, .95 if p is not None else 0., .1]
            for k, p in enumerate(pitches)]


class TestSegment:
    def test_pitch_change_splits_notes(self):
        notes = compare.segment(frames_for([69.] * 20 + [72.] * 20), .01, .4)
        assert [round(n.pitch) for n in notes] == [69, 72]
        assert notes[0].start == 0 and notes[0].end == pytest.approx(.2)
        assert notes[1].end == pytest.approx(.4)

    def test_unpitched_gap_splits_repeated_notes(self):
        notes = compare.segment(frames_for([69.] * 10 + [None] * 3 + [69.] * 10), .01, .23)
        assert len(notes) == 2
        assert notes[1].start == pytest.approx(.13)

    def test_notes_shorter_than_55_ms_are_dropped(self):
        notes = compare.segment(frames_for([69.] * 5 + [None] + [72.] * 6), .01, .12)
        assert [round(n.pitch) for n in notes] == [72]

    def test_vibrato_stays_one_note(self):
        vibrato = list(69 + .3 * np.sin(np.arange(60) / 3))
        notes = compare.segment(frames_for(vibrato), .01, .6)
        assert len(notes) == 1
        assert notes[0].pitch == pytest.approx(69, abs=.1)

    def test_note_values_are_medians_and_rms(self):
        frames = frames_for([69.] * 10)
        for k, frame in enumerate(frames):
            frame[2], frame[3] = (.8 if k < 3 else .9), (.3 if k % 2 else .4)
        (n,) = compare.segment(frames, .01, .1)
        assert n.confidence == pytest.approx(.9)
        assert n.rms == pytest.approx(np.sqrt((.3**2 + .4**2) / 2))

    def test_no_pitched_frames_gives_no_notes(self):
        assert compare.segment(frames_for([None] * 10), .01, .1) == []


# --------------------------------------------------------------------------- analyze


class TestAnalyze:
    def test_detects_sample_notes(self, pair, tmp_path):
        data, hit = compare.analyze(pair[0], 0., None, tmp_path / "cache")
        assert hit is False
        assert [round(n["pitch"]) for n in data["notes"]] == [69, 72, 76]
        starts = [n["start"] for n in data["notes"]]
        np.testing.assert_allclose(starts, [.49, 1.29, 2.09], atol=.011)
        assert data["range"] == [0., pytest.approx(3.2)]
        assert set(data) == {"range", "peak", "rms", "frames", "notes"}

    def test_second_call_hits_cache_with_same_data(self, pair, tmp_path):
        first, _ = compare.analyze(pair[0], 0., None, tmp_path / "cache")
        second, hit = compare.analyze(pair[0], 0., None, tmp_path / "cache")
        assert hit is True
        assert second == json.loads(json.dumps(first))

    def test_renamed_copy_hits_cache(self, pair, tmp_path):
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        copy = shutil.copy(pair[0], tmp_path / "renamed.wav")
        assert compare.analyze(Path(copy), 0., None, tmp_path / "cache")[1] is True

    def test_changed_range_misses_cache(self, pair, tmp_path):
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        assert compare.analyze(pair[0], 0., 3., tmp_path / "cache")[1] is False
        assert compare.analyze(pair[0], .1, None, tmp_path / "cache")[1] is False
        assert len(list((tmp_path / "cache").iterdir())) == 3

    def test_changed_content_misses_cache(self, pair, tmp_path):
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        sa.write_wav(pair[0], sa.synth(sa.REFERENCE_NOTES, 3.2, gain=.9))
        assert compare.analyze(pair[0], 0., None, tmp_path / "cache")[1] is False

    def test_corrupt_cache_entry_is_recomputed(self, pair, tmp_path):
        cache = tmp_path / "cache"
        good, _ = compare.analyze(pair[0], 0., None, cache)
        (entry,) = cache.iterdir()
        entry.write_text("{not json", encoding="utf-8")
        data, hit = compare.analyze(pair[0], 0., None, cache)
        assert hit is False
        assert data["notes"] == good["notes"]

    def test_input_file_is_not_modified(self, pair, tmp_path):
        before = sha256(pair[0])
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        assert sha256(pair[0]) == before

    def test_range_end_is_clamped_to_file_length(self, pair, tmp_path):
        # The first reference note ends at 1.1 s, so starting at 1.2 s skips it.
        data, _ = compare.analyze(pair[0], 1.2, 99., tmp_path / "cache")
        assert data["range"] == [1.2, pytest.approx(3.2)]
        assert [round(n["pitch"]) for n in data["notes"]] == [72, 76]

    def test_range_start_past_end_is_rejected(self, pair, tmp_path):
        with pytest.raises(ValueError, match="Range starts outside"):
            compare.analyze(pair[0], 10., None, tmp_path / "cache")

    def test_stereo_file_is_mixed_to_mono(self, tmp_path):
        mono = sa.synth(sa.REFERENCE_NOTES, 3.2)
        path = sa.write_wav(tmp_path / "stereo.wav", np.c_[mono, mono * .5], dtype="float32")
        data, _ = compare.analyze(path, 0., None, tmp_path / "cache")
        assert [round(n["pitch"]) for n in data["notes"]] == [69, 72, 76]
        assert data["peak"] == pytest.approx(np.max(np.abs(mono)), rel=1e-5)

    @pytest.mark.parametrize("dtype", ["int16", "int32", "uint8", "float32"])
    def test_all_sample_formats_give_same_notes(self, tmp_path, dtype):
        path = sa.write_wav(tmp_path / f"{dtype}.wav", sa.synth(sa.REFERENCE_NOTES, 3.2), dtype)
        data, _ = compare.analyze(path, 0., None, tmp_path / "cache")
        assert [round(n["pitch"], 1) for n in data["notes"]] == [69., 72., 76.]

    def test_only_blips_gives_no_notes_error(self, tmp_path):
        # 15 ms tones stay under the 55 ms minimum even after the 40 ms
        # analysis window spreads them across neighbouring frames.
        blip = sa.synth([(.1, .015, 69, 1), (.5, .015, 72, 1)], 1.)
        path = sa.write_wav(tmp_path / "blips.wav", blip)
        with pytest.raises(ValueError, match="No stable solo notes"):
            compare.analyze(path, 0., None, tmp_path / "cache")


# --------------------------------------------------------------------------- align


def melody(pitches, length=.2):
    return [note(k * .3, k * .3 + length, p) for k, p in enumerate(pitches)]


class TestAlign:
    def test_identical_lists_pair_in_order(self):
        notes = melody([60, 62, 64])
        assert compare.align(notes, notes) == [(0, 0), (1, 1), (2, 2)]

    def test_extra_render_note(self):
        pairs = compare.align(melody([60, 64, 67]), melody([60, 62, 64, 67]))
        assert pairs == [(0, 0), (None, 1), (1, 2), (2, 3)]

    def test_missing_render_note(self):
        pairs = compare.align(melody([60, 62, 64, 67]), melody([60, 64, 67]))
        assert pairs == [(0, 0), (1, None), (2, 1), (3, 2)]

    def test_wrong_note_still_pairs(self):
        pairs = compare.align(melody([60, 62, 64]), melody([60, 63, 64]))
        assert pairs == [(0, 0), (1, 1), (2, 2)]

    def test_empty_render(self):
        assert compare.align(melody([60, 62]), []) == [(0, None), (1, None)]


# --------------------------------------------------------------------------- compare


class TestCompare:
    def test_measurements(self):
        ref = [note(1.0, 1.5, 69., rms=.1), note(2.0, 2.5, 72., rms=.1)]
        ren = [note(1.3, 1.8, 69., rms=.05), note(2.34, 2.9, 72.2, rms=.1)]
        result = compare.compare(as_data(ref, rms=.1), as_data(ren, rms=.05))
        assert result["render_minus_reference_offset_s"] == pytest.approx(.3)
        assert result["render_gain_for_rms_match_db"] == pytest.approx(20 * np.log10(2))
        first, second = result["events"]
        assert first["onset_ms"] == pytest.approx(0)
        assert first["relative_level_db"] == pytest.approx(0, abs=1e-9)
        assert second["pitch_cents"] == pytest.approx(20)
        assert second["onset_ms"] == pytest.approx(40)
        assert second["duration_ms"] == pytest.approx(60)
        assert second["relative_level_db"] == pytest.approx(20 * np.log10(2))
        assert second["status"] == "matched" and second["review"] is False

    def test_unmatched_and_extra_events(self):
        ref = melody([60, 62, 64, 67])
        ren = melody([60, 64, 67, 69, 71])
        events = compare.compare(as_data(ref), as_data(ren))["events"]
        statuses = [e["status"] for e in events]
        assert statuses.count("unmatched reference event") == 1
        assert statuses.count("extra render event") == 2
        missing = next(e for e in events if e["status"] == "unmatched reference event")
        assert missing["render_s"] is None and "pitch_cents" not in missing

    def test_no_pitch_anchor_leaves_onset_empty(self):
        ref, ren = [note(0, .5, 60.)], [note(.2, .7, 61.)]
        result = compare.compare(as_data(ref), as_data(ren))
        assert result["render_minus_reference_offset_s"] is None
        assert result["events"][0]["onset_ms"] is None
        assert result["events"][0]["review"] is True  # 100 cents >= 60

    def test_offset_uses_first_pitch_matched_pair(self):
        ref = [note(0, .3, 60.), note(1, 1.3, 64.)]
        ren = [note(.5, .8, 61.), note(1.2, 1.5, 64.)]
        result = compare.compare(as_data(ref), as_data(ren))
        assert result["render_minus_reference_offset_s"] == pytest.approx(.2)

    def test_low_confidence_is_flagged(self):
        ref, ren = [note(0, .5, 60., confidence=.8)], [note(0, .5, 60.)]
        assert compare.compare(as_data(ref), as_data(ren))["events"][0]["review"] is True

    def test_repeated_neighbour_pitch_is_flagged(self):
        ref = [note(0, .3, 60.), note(.4, .7, 60.), note(.8, 1.1, 62.)]
        events = compare.compare(as_data(ref), as_data(ref))["events"]
        assert [e["review"] for e in events] == [True, True, False]


# --------------------------------------------------------------------------- markdown


def result_for_markdown(events):
    level = {"peak": .5, "rms": .1}
    return {"reference_cache_hit": False, "render_minus_reference_offset_s": None,
            "render_gain_for_rms_match_db": 1.26, "reference": level, "render": level,
            "events": events}


def matched(cents=0., onset=0., duration=0., level=0., review=False, at=1.):
    return {"reference_s": at, "render_s": at, "status": "matched", "pitch_cents": cents,
            "onset_ms": onset, "duration_ms": duration, "relative_level_db": level,
            "review": review}


class TestMarkdown:
    def test_largest_differences_first_and_limit(self):
        events = [matched(cents=5, at=1), matched(onset=300, at=2), matched(level=3, at=3),
                  {"reference_s": 4., "render_s": None, "status": "unmatched reference event"}]
        text = compare.markdown(result_for_markdown(events), limit=3)
        rows = [line for line in text.splitlines() if line.startswith("| ") and "Status" not in line]
        assert len(rows) == 3
        assert "unmatched reference event" in rows[0]
        assert "+300.0" in rows[1]
        assert "+3.0" in rows[2]
        assert "1.000" not in text  # the smallest difference was cut by the limit

    def test_header_and_missing_values(self):
        events = [{"reference_s": None, "render_s": 2.5, "status": "extra render event"},
                  matched(review=True)]
        text = compare.markdown(result_for_markdown(events), limit=12)
        assert text.startswith("# Audio comparison")
        assert "Reference cache hit: False" in text
        assert "first pitch-matched attack: — s" in text
        assert "Render gain for RMS comparison: +1.3 dB" in text
        assert "| — | 2.500 | — | — | — | — | extra render event |" in text
        assert "matched · review" in text
        assert text.endswith("\n")


# --------------------------------------------------------------------------- command line


def run_cli(*args, cwd):
    return subprocess.run([sys.executable, str(ROOT / "compare.py"), *map(str, args)],
                          cwd=cwd, capture_output=True, text=True)


class TestCommandLine:
    def test_sample_pair_end_to_end(self, pair, tmp_path):
        hashes = [sha256(p) for p in pair]
        proc = run_cli(*pair, cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        report = Path(proc.stdout.strip())
        if not report.is_absolute():
            report = tmp_path / report
        assert report.name == "comparison.md" and report.parent.parent.name == "outputs"
        result = json.loads((report.parent / "comparison.json").read_text(encoding="utf-8"))

        assert result["render_minus_reference_offset_s"] == pytest.approx(sa.RENDER_OFFSET_S, abs=.011)
        assert result["render_gain_for_rms_match_db"] == pytest.approx(5.8, abs=.3)
        events = result["events"]
        assert [e["status"] for e in events] == ["matched"] * 3
        cents = [e["pitch_cents"] for e in events]
        onset = [e["onset_ms"] for e in events]
        duration = [e["duration_ms"] for e in events]
        level = [e["relative_level_db"] for e in events]
        np.testing.assert_allclose(cents, [0, 25, -18], atol=2)
        np.testing.assert_allclose(onset, [0, 40, -30], atol=10.5)
        np.testing.assert_allclose(duration, [0, 50, -40], atol=10.5)
        assert level[1] > level[0] > level[2]
        assert result["reference"]["file"] == "reference.wav"
        assert result["reference_cache_hit"] is False
        assert [sha256(p) for p in pair] == hashes

    def test_second_run_reuses_cache_and_makes_new_folder(self, pair, tmp_path):
        first = run_cli(*pair, cwd=tmp_path).stdout.strip()
        second = run_cli(*pair, cwd=tmp_path).stdout.strip()
        assert first != second
        assert "Reference cache hit: True" in (tmp_path / second).read_text(encoding="utf-8")
        third = run_cli(*pair, "--reference-end", 3, cwd=tmp_path).stdout.strip()
        assert "Reference cache hit: False" in (tmp_path / third).read_text(encoding="utf-8")
        assert len(list((tmp_path / "outputs").iterdir())) == 3

    def test_custom_cache_output_and_limit(self, pair, tmp_path):
        proc = run_cli(*pair, "--cache", tmp_path / "c", "--output", tmp_path / "o",
                       "--limit", 1, cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        text = Path(proc.stdout.strip()).read_text(encoding="utf-8")
        assert len([line for line in text.splitlines() if "| matched" in line]) == 1
        assert len(list((tmp_path / "c").iterdir())) == 2

    @pytest.mark.parametrize("args, message", [
        (["--reference-end", 0], "Ranges require"),
        (["--render-start", -1], "Ranges require"),
        (["--reference-start", 2, "--reference-end", 1], "Ranges require"),
        (["--render-end", "nan"], "Ranges require"),
        (["--limit", 0], "--limit must be positive"),
    ])
    def test_bad_arguments_exit_2(self, pair, tmp_path, args, message):
        proc = run_cli(*pair, *args, cwd=tmp_path)
        assert proc.returncode == 2
        assert proc.stderr.startswith("Comparison failed:") and message in proc.stderr
        assert not (tmp_path / "outputs").exists()

    def test_missing_file_exits_2(self, pair, tmp_path):
        proc = run_cli(tmp_path / "nope.wav", pair[1], cwd=tmp_path)
        assert proc.returncode == 2 and "Comparison failed" in proc.stderr

    def test_help(self, tmp_path):
        proc = run_cli("--help", cwd=tmp_path)
        assert proc.returncode == 0
        assert "Compare a solo recording with a notation render." in proc.stdout
        assert "--reference-start" in proc.stdout


def test_sample_script_writes_demo_pair(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / "sample_audio.py"), str(tmp_path / "s")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["reference.wav", "render.wav"]
