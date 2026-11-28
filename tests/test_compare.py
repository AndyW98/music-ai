"""Unit and end-to-end tests for compare.py using synthetic sample audio."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pretty_midi
import pyloudnorm
import pytest
from scipy.io import wavfile
import soundfile

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

    @pytest.mark.parametrize("suffix", [".flac", ".ogg"])
    def test_flac_and_ogg_are_read(self, tmp_path, suffix):
        path = tmp_path / f"a{suffix}"
        soundfile.write(path, tone(440), sa.RATE)
        rate, samples = compare.read_audio(path)
        assert rate == sa.RATE and samples.shape == (int(.5 * sa.RATE),)
        assert np.max(np.abs(samples - tone(440))) < .05  # Vorbis is lossy

    def test_unreadable_file_is_a_value_error(self, tmp_path):
        path = tmp_path / "bad.wav"
        path.write_bytes(b"not audio")
        with pytest.raises(ValueError, match="Cannot read audio"):
            compare.read_audio(path)

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
        # Silent frames (confidence 0, below the level gate) always end a note.
        notes = compare.segment(frames_for([69.] * 10 + [None] * 3 + [69.] * 10), .01, .23)
        assert len(notes) == 2
        assert notes[1].start == pytest.approx(.13)
        assert notes[1].start_reason == "first pitched frame"

    def test_notes_shorter_than_55_ms_are_dropped(self):
        candidates = []
        notes = compare.segment(frames_for([69.] * 5 + [None] + [72.] * 6), .01, .12, candidates)
        assert [round(n.pitch) for n in notes] == [72]
        (dropped,) = candidates
        assert dropped["pitch"] == 69 and dropped["reason"] == "shorter than 55 ms"
        assert (dropped["start"], dropped["end"]) == (0, pytest.approx(.05))

    def test_pitch_change_reason(self):
        notes = compare.segment(frames_for([69.] * 10 + [70.] * 10), .01, .2)
        assert notes[1].start_reason == "pitch change of +100 cents"

    @pytest.mark.parametrize("gap", [1, 3])
    def test_audible_unpitched_gap_is_bridged(self, gap):
        # A breath or tracker dropout: unpitched but audible (confidence > 0).
        frames = frames_for([69.] * 10 + [None] * gap + [69.] * 10)
        for frame in frames[10:10 + gap]:
            frame[2] = .4
        (n,) = compare.segment(frames, .01, (20 + gap) / 100)
        assert n.start == 0 and n.end == pytest.approx((20 + gap) / 100)
        assert n.gaps == [[pytest.approx(.1), pytest.approx(.1 + gap / 100)]]
        assert n.pitch == 69

    def test_long_or_different_pitch_gap_is_not_bridged(self):
        long_gap = frames_for([69.] * 10 + [None] * 4 + [69.] * 10)
        moved = frames_for([69.] * 10 + [None] * 2 + [70.] * 10)
        for frames in (long_gap, moved):
            for frame in frames:
                if frame[1] is None:
                    frame[2] = .4
            assert len(compare.segment(frames, .01, len(frames) / 100)) == 2

    def test_bridged_gaps_after_short_pitched_run(self):
        frames = frames_for([69.] * 10 + [None] * 3 + [69.] * 2 +
                            [None] * 3 + [69.] * 10)
        for frame in frames:
            if frame[1] is None:
                frame[2] = .4
        notes = compare.segment(frames, .01, len(frames) / 100)
        assert len(notes) == 1
        assert len(notes[0].gaps) == 2
        assert notes[0].pitch == 69

    def legato(self, confidence=.95, dip=.25):
        frames = frames_for([76.] * 40)
        for k, frame in enumerate(frames):
            frame[3] = .1 * (1 - (1 - dip) * max(0, 1 - abs(k - 20) / 4))
        frames[20][2] = confidence
        return frames

    def test_reattack_splits_a_stable_note(self):
        first, second = compare.segment(self.legato(), .01, .4)
        assert first.end == second.start == pytest.approx(.2)
        assert second.start_reason.startswith("reattack: level dipped 12.0 dB")

    def test_dip_without_clear_pitch_or_too_shallow_does_not_split(self):
        assert len(compare.segment(self.legato(confidence=.8), .01, .4)) == 1
        assert len(compare.segment(self.legato(dip=.6), .01, .4)) == 1  # 4.4 dB

    def test_reattack_too_close_to_note_edge_is_ignored(self):
        frames = self.legato()[15:]  # the dip is 5 frames from the start
        assert len(compare.segment(frames, .01, .25)) == 1

    def test_tremolo_vibrato_stays_one_note(self):
        vibrato = frames_for(list(69 + .3 * np.sin(np.arange(60) / 3)))
        for k, frame in enumerate(vibrato):
            frame[3] = .1 * (1 + .12 * np.sin(k / 3))  # about 2 dB of tremolo
        assert len(compare.segment(vibrato, .01, .6)) == 1

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
        assert set(data) == {"range", "peak", "rms", "frames", "notes", "candidates"}

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

    def test_ogg_input_gives_same_notes(self, tmp_path):
        path = tmp_path / "reference.ogg"
        soundfile.write(path, sa.synth(sa.REFERENCE_NOTES, 3.2), sa.RATE)
        data, _ = compare.analyze(path, 0., None, tmp_path / "cache")
        assert [round(n["pitch"], 1) for n in data["notes"]] == [69., 72., 76.]

    def test_cache_key_includes_version(self, pair, tmp_path, monkeypatch):
        compare.analyze(pair[0], 0., None, tmp_path / "cache")
        monkeypatch.setattr(compare, "CACHE_VERSION", "test-bump")
        assert compare.analyze(pair[0], 0., None, tmp_path / "cache")[1] is False

    def test_candidates_are_kept(self, tmp_path):
        audio = sa.synth([(.1, .015, 72, 1), (.5, .5, 69, 1)], 1.2)
        path = sa.write_wav(tmp_path / "blip.wav", audio)
        data, _ = compare.analyze(path, 0., None, tmp_path / "cache")
        assert [round(n["pitch"]) for n in data["notes"]] == [69]
        assert [round(c["pitch"]) for c in data["candidates"]] == [72]
        assert data["candidates"][0]["reason"] == "shorter than 55 ms"

    @pytest.mark.parametrize("case, expected", [
        ("legato", [76, 76]), ("breath", [69]), ("silence", [69, 69]),
    ])
    def test_boundary_regressions_on_audio(self, tmp_path, case, expected):
        if case == "legato":
            audio = sa.synth([(.5, .5, 76, .8, .04), (1., .5, 76, .8, .04)], 2.)
        else:
            audio = sa.synth([(.5, 1., 69, .8)], 2.,
                             dropouts=[(.95, .06, .05 if case == "breath" else 0.)])
        path = sa.write_wav(tmp_path / f"{case}.wav", audio, dtype="float32")
        data, _ = compare.analyze(path, 0., None, tmp_path / "cache")
        assert [round(n["pitch"]) for n in data["notes"]] == expected

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

    def test_implausible_pitch_pair_stays_unmatched(self):
        pairs = compare.align(melody([68, 47, 75]), melody([68, 73, 75]))
        assert pairs[0] == (0, 0) and pairs[-1] == (2, 2)
        assert set(pairs[1:-1]) == {(1, None), (None, 1)}

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

    def test_note_match_scores(self):
        ref = [note(1.0, 1.5, 69.), note(2.0, 2.5, 72.), note(3.0, 3.5, 76.)]
        ren = [note(1.3, 1.8, 69.), note(2.32, 2.8, 72.3), note(3.3, 3.6, 74.)]
        match = compare.compare(as_data(ref), as_data(ren))["note_match"]
        # Shift 0.3 s removed; note 2 is 20 ms late and 30 cents sharp (inside
        # the tolerances); note 3 is two semitones off, so it does not match.
        assert match["onset_pitch"]["f1"] == pytest.approx(2 / 3)
        # Note 2 ends 20 ms late: within 20% of 0.5 s, so offsets still match.
        assert match["onset_pitch_offset"]["f1"] == pytest.approx(2 / 3)
        assert match["tolerances"]["render_shift_s"] == pytest.approx(.3)

    def test_note_match_with_no_notes(self):
        assert compare.note_scores([], [note(0, .5, 60.)], 0.)["onset_pitch"]["f1"] == 0

    def test_repeated_neighbour_pitch_is_flagged(self):
        ref = [note(0, .3, 60.), note(.4, .7, 60.), note(.8, 1.1, 62.)]
        events = compare.compare(as_data(ref), as_data(ref))["events"]
        assert [e["review"] for e in events] == [True, True, False]


# --------------------------------------------------------------------------- markdown


def result_for_markdown(events):
    level = {"peak": .5, "rms": .1}
    for number, event in enumerate(events, 1):
        event.setdefault("id", number)
        event.setdefault("written", None)
        event.setdefault("written_status", "no event map")
        for side in ("reference", "render"):
            present = event[f"{side}_s"] is not None
            event.setdefault(f"{side}_end_s", event[f"{side}_s"] + .5 if present else None)
            event.setdefault(f"{side}_pitch", 69. if present else None)
            event.setdefault(f"{side}_confidence", .95 if present else None)
    score = {"precision": 1., "recall": 1., "f1": 1.}
    return {"reference_cache_hit": False, "render_minus_reference_offset_s": None,
            "render_gain_for_rms_match_db": 1.26, "reference": level, "render": level,
            "note_match": {"onset_pitch": score, "onset_pitch_offset": {**score, "f1": .5}},
            "events": events}


def matched(cents=0., onset=0., duration=0., level=0., review=False, at=1.):
    return {"reference_s": at, "render_s": at, "status": "matched", "pitch_cents": cents,
            "onset_ms": onset, "duration_ms": duration, "relative_level_db": level,
            "review": review, "reasons": ["low confidence"] if review else [],
            "reference_end_s": at + .5, "render_end_s": at + .5, "reference_pitch": 69.,
            "render_pitch": 69. + cents / 100, "reference_confidence": .95,
            "render_confidence": .95}


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
        assert "| 1 | — | 2.500 | — | A4 +0¢ | — | — | — | — | extra render event |" in text
        assert "matched · review" in text
        assert "Note match F1 (mir_eval, ±50 ms, ±50 cents): 1.00; with note ends: 0.50" in text
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
        assert result["note_match"]["onset_pitch"]["f1"] == 1.0
        assert result["listening"]["method"] == "LUFS"
        assert result["listening"]["gain_db"] == pytest.approx(5.2, abs=.5)
        assert sorted(p.name for p in report.parent.iterdir()) == [
            "comparison.json", "comparison.md", "reference-clip.wav", "render-level-matched.wav"]
        assert [sha256(p) for p in pair] == hashes

    def test_second_run_reuses_cache_and_makes_new_folder(self, pair, tmp_path):
        first = run_cli(*pair, cwd=tmp_path).stdout.strip()
        second = run_cli(*pair, cwd=tmp_path).stdout.strip()
        assert first != second
        assert "Reference cache hit: True" in (tmp_path / second).read_text(encoding="utf-8")
        third = run_cli(*pair, "--reference-end", 3, cwd=tmp_path).stdout.strip()
        assert "Reference cache hit: False" in (tmp_path / third).read_text(encoding="utf-8")
        assert len(list((tmp_path / "outputs").iterdir())) == 3

    def test_midi_and_no_listening_copy(self, pair, tmp_path):
        proc = run_cli(*pair, "--midi", "--midi-program", 0, "--no-listening-copy",
                       "--reference-start", .4, cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        folder = (tmp_path / proc.stdout.strip()).parent
        assert sorted(p.name for p in folder.iterdir()) == [
            "comparison.json", "comparison.md", "notation-handoff.json", "reference-notes.mid"]
        (track,) = pretty_midi.PrettyMIDI(str(folder / "reference-notes.mid")).instruments
        assert [n.pitch for n in track.notes] == [69, 72, 76]
        assert track.notes[0].start == pytest.approx(.09, abs=.011)  # 0.49 s - 0.4 s
        assert "Reference notes as MIDI: reference-notes.mid" in (folder / "comparison.md").read_text(encoding="utf-8")

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
        (["--midi-program", 128], "--midi-program must be between 0 and 127"),
    ])
    def test_bad_arguments_exit_2(self, pair, tmp_path, args, message):
        proc = run_cli(*pair, *args, cwd=tmp_path)
        assert proc.returncode == 2
        assert proc.stderr.startswith("Comparison failed:") and message in proc.stderr
        assert not (tmp_path / "outputs").exists()

    def test_unreadable_audio_exits_2(self, pair, tmp_path):
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not audio")
        proc = run_cli(bad, pair[1], cwd=tmp_path)
        assert proc.returncode == 2 and "Cannot read audio" in proc.stderr

    def test_missing_file_exits_2(self, pair, tmp_path):
        proc = run_cli(tmp_path / "nope.wav", pair[1], cwd=tmp_path)
        assert proc.returncode == 2 and "Comparison failed" in proc.stderr

    def test_help(self, tmp_path):
        proc = run_cli("--help", cwd=tmp_path)
        assert proc.returncode == 0
        assert "Compare a solo recording with a notation render." in proc.stdout
        assert "--reference-start" in proc.stdout


class TestListeningCopies:
    def test_render_copy_matches_reference_loudness(self, pair, tmp_path):
        info = compare.listening_copies(tmp_path, pair[0], [0., 3.2], pair[1], [0., 3.4], 0.)
        assert info["method"] == "LUFS"
        ref, rate = soundfile.read(tmp_path / "reference-clip.wav")
        ren, _ = soundfile.read(tmp_path / "render-level-matched.wav")
        meter = pyloudnorm.Meter(rate)
        assert meter.integrated_loudness(ren) == pytest.approx(meter.integrated_loudness(ref), abs=.1)
        assert info["gain_db"] == pytest.approx(info["reference_lufs"] - info["render_lufs"])
        assert soundfile.info(tmp_path / "render-level-matched.wav").subtype == "FLOAT"

    def test_clip_is_the_selected_range(self, pair, tmp_path):
        compare.listening_copies(tmp_path, pair[0], [1., 2.5], pair[1], [0., 3.4], 0.)
        assert soundfile.info(tmp_path / "reference-clip.wav").duration == pytest.approx(1.5)

    def test_short_clip_falls_back_to_rms_gain(self, pair, tmp_path):
        info = compare.listening_copies(tmp_path, pair[0], [.5, .8], pair[1], [.7, 1.], 4.5)
        assert info["method"] == "RMS" and info["gain_db"] == 4.5
        assert info["reference_lufs"] is None

    def test_inputs_unchanged(self, pair, tmp_path):
        before = [sha256(p) for p in pair]
        compare.listening_copies(tmp_path, pair[0], [0., 3.2], pair[1], [0., 3.4], 0.)
        assert [sha256(p) for p in pair] == before


class TestMidi:
    def test_notes_relative_to_range_start(self, tmp_path):
        notes = [vars(note(1.5, 2., 69.2, rms=.1)), vars(note(2.5, 3., 71.6, rms=.01))]
        compare.write_midi(tmp_path / "n.mid", notes, 1.0, program=40)
        (track,) = pretty_midi.PrettyMIDI(str(tmp_path / "n.mid")).instruments
        assert track.program == 40
        assert [(round(n.start, 3), round(n.end, 3), n.pitch) for n in track.notes] == \
            [(.5, 1., 69), (1.5, 2., 72)]
        assert [n.velocity for n in track.notes] == [100, 60]  # 20 dB quieter


def test_sample_script_writes_demo_pair(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / "sample_audio.py"), str(tmp_path / "s")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == [
        "reference.wav", "render.wav", "validation-events.csv", "validation-render.wav"]


# --------------------------------------------------------------------------- event maps


def write_map(path, rows, header="time_s,pitch,duration_s,bar,beat,part,voice"):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def render_map(path, offset=0.):
    """An event map CSV for the sample render (``RENDER_NOTES``)."""
    rows = [f"{start + offset:.3f},{pitch},{duration:.3f},1,{k + 1},Flute,1"
            for k, (start, duration, pitch, _) in enumerate(sa.RENDER_NOTES)]
    return write_map(path, rows)


class TestEventMap:
    def test_csv_columns_note_names_and_sorting(self, tmp_path):
        path = write_map(tmp_path / "m.csv", ["1.5,C#5,,2,1.5,Flute,", "0.5,69.25,0.4,1,1,Flute,1"])
        first, second = compare.read_event_map(path)
        assert first == {"time_s": .5, "end_s": pytest.approx(.9), "pitch": 69.25, "bar": 1,
                         "beat": 1., "part": "Flute", "voice": "1", "source": "line 3"}
        assert second["pitch"] == 73 and second["end_s"] is None and second["voice"] is None
        assert second["beat"] == 1.5

    def test_minimal_columns_bom_and_offset(self, tmp_path):
        path = tmp_path / "m.csv"
        path.write_text("\ufeffTime_s , Pitch\n1.0,A4\n", encoding="utf-8")
        (event,) = compare.read_event_map(path, offset=.25)
        assert event["time_s"] == 1.25 and event["pitch"] == 69 and event["bar"] is None

    @pytest.mark.parametrize("rows, message", [
        (["x,69"], "line 2"), (["1,H4"], "line 2"), (["-1,69"], "line 2"),
        (["1,69,0"], "duration_s"), (["1,200"], "between 0 and 127"), ([], "No note events"),
    ])
    def test_bad_csv_is_a_value_error(self, tmp_path, rows, message):
        path = write_map(tmp_path / "m.csv", rows, header="time_s,pitch,duration_s")
        with pytest.raises(ValueError, match=message):
            compare.read_event_map(path)

    def test_missing_columns(self, tmp_path):
        with pytest.raises(ValueError, match="needs time_s and pitch"):
            compare.read_event_map(write_map(tmp_path / "m.csv", ["1"], header="time_s"))

    def test_midi_gives_bar_beat_and_part(self, tmp_path):
        midi = pretty_midi.PrettyMIDI(initial_tempo=120)
        midi.time_signature_changes.append(pretty_midi.TimeSignature(3, 4, 0))
        flute = pretty_midi.Instrument(73, name="Flute")
        # 120 bpm in 3/4: a beat is 0.5 s and a bar 1.5 s.
        for start, pitch in ((0., 69), (.5, 71), (1.75, 72)):
            flute.notes.append(pretty_midi.Note(80, pitch, start, start + .4))
        drums = pretty_midi.Instrument(0, is_drum=True)
        drums.notes.append(pretty_midi.Note(80, 36, 0, .1))
        midi.instruments += [flute, drums]
        midi.write(str(tmp_path / "m.mid"))
        events = compare.read_event_map(tmp_path / "m.mid")
        assert [(e["bar"], e["beat"], e["pitch"]) for e in events] == [
            (1, 1., 69), (1, 2., 71), (2, 1.5, 72)]
        assert events[2]["end_s"] == pytest.approx(2.15)
        assert events[0]["part"] == "Flute" and events[0]["voice"] is None
        assert events[2]["source"] == "Flute note 3"

    def test_unreadable_midi(self, tmp_path):
        (tmp_path / "m.mid").write_bytes(b"not midi")
        with pytest.raises(ValueError, match="Cannot read MIDI event map"):
            compare.read_event_map(tmp_path / "m.mid")


def written(time, pitch, end=None, bar=None, beat=None):
    return {"time_s": time, "end_s": end, "pitch": float(pitch), "bar": bar, "beat": beat,
            "part": None, "voice": None, "source": f"event at {time}"}


class TestTrace:
    def test_rows_carry_both_sides_without_a_map(self):
        ref = [note(0, .5, 60., confidence=.9), note(1, 1.5, 62.)]
        ren = [note(.2, .7, 60.1, confidence=.97)]
        events = compare.compare(as_data(ref), as_data(ren))["events"]
        first, second = events
        assert [e["id"] for e in events] == [1, 2]
        assert first["reference_pitch"] == 60. and first["render_pitch"] == 60.1
        assert first["reference_confidence"] == .9 and first["render_confidence"] == .97
        assert first["reference_end_s"] == .5 and first["render_end_s"] == .7
        assert first["reference_note"] == 0 and first["render_note"] == 0
        assert second["render_note"] is None and second["reasons"] == ["no detected render event"]
        assert all(e["written"] is None and e["written_status"] == "no event map" for e in events)
        assert "detector_check" not in compare.compare(as_data(ref), as_data(ren))

    def test_review_reasons(self):
        ref = [note(0, .3, 60., confidence=.8), note(.4, .7, 60.), note(.8, 1.1, 62.)]
        ren = [note(0, .3, 60.), note(.4, .7, 60.), note(.8, 1.1, 63.)]
        first, _, third = compare.compare(as_data(ref), as_data(ren))["events"]
        assert first["review"] and len(first["reasons"]) == 2
        assert "confidence below 0.85" in first["reasons"][1]
        assert third["reasons"] == ["pitches differ by 60 cents or more"]

    def test_written_event_without_render_detection(self):
        # The render lacks the reference's second note, but the score has it.
        ref = melody([60, 62, 64])
        ren = [note(.1, .3, 60.), note(.7, .9, 64.)]
        events = [written(.1, 60, bar=1, beat=1), written(.42, 62, bar=1, beat=2),
                  written(.7, 64, bar=1, beat=3)]
        rows = compare.compare(as_data(ref), as_data(ren), events)["events"]
        missing = rows[1]
        assert missing["status"] == "unmatched reference event"
        assert missing["written_status"] == "mapped" and missing["written"]["beat"] == 2
        assert missing["reasons"] == ["written event with no detected render event"]
        assert missing["expected_render_s"] == pytest.approx(.4)
        assert [r["written"]["beat"] for r in rows] == [1, 2, 3]

    def test_no_mapped_written_event(self):
        ref = melody([60, 62, 64])
        ren = [note(0, .2, 60.), note(.6, .8, 64.)]
        events = [written(0, 60), written(.6, 64)]
        rows = compare.compare(as_data(ref), as_data(ren), events)["events"]
        assert rows[1]["status"] == "unmatched reference event"
        assert rows[1]["written"] is None and rows[1]["written_status"] == "no mapped written event"
        assert rows[1]["reasons"] == ["no detected render event"]

    def test_render_detection_without_written_event_is_flagged(self):
        notes = melody([60, 62])
        rows = compare.compare(as_data(notes), as_data(notes), [written(0, 60)])["events"]
        assert rows[0]["written_status"] == "mapped" and rows[0]["review"] is False
        assert rows[1]["written_status"] == "no mapped written event"
        assert rows[1]["review"] is True
        assert rows[1]["reasons"] == ["render detection has no mapped written event"]

    def test_undetected_written_event_is_placed_in_order(self):
        notes = [note(0, .2, 60.), note(.6, .8, 64.)]
        events = [written(0, 60), written(.3, 62), written(.6, 64)]
        rows = compare.compare(as_data(notes), as_data(notes), events)["events"]
        assert [r["status"] for r in rows] == ["matched", "undetected written event", "matched"]
        assert [r["id"] for r in rows] == [1, 2, 3]
        assert rows[1]["reference_s"] is None and rows[1]["render_s"] is None
        assert rows[1]["expected_render_s"] == .3

    def test_written_event_far_off_pitch_is_not_used(self):
        ref = melody([60, 62, 64])
        ren = [note(0, .2, 60.), note(.6, .8, 64.)]
        events = [written(0, 60), written(.3, 67), written(.6, 64)]
        rows = compare.compare(as_data(ref), as_data(ren), events)["events"]
        assert rows[1]["written_status"] == "no mapped written event"
        assert rows[2]["status"] == "undetected written event"


class TestDetectorCheck:
    def check(self, notes, events):
        return compare.check_detector(notes, events, compare.match_written(notes, events))

    def test_perfect_match(self):
        notes = [note(0, .4, 60.), note(.5, .9, 62.)]
        result = self.check(notes, [written(0, 60, .4), written(.5, 62, .9)])
        assert (result["precision"], result["recall"], result["f1"]) == (1, 1, 1)
        assert result["issues"] == [] and result["median_onset_ms"] == 0

    def test_missed_and_extra(self):
        notes = [note(0, .4, 60.), note(1., 1.3, 70.)]
        result = self.check(notes, [written(0, 60, .4), written(.5, 62, .9)])
        assert [i["kind"] for i in result["issues"]] == ["missed", "extra"]
        assert result["false_negatives"] == 1 and result["false_positives"] == 1
        assert result["precision"] == .5 and result["recall"] == .5

    def test_merged_repeated_note(self):
        notes = [note(0, 1., 60.)]
        result = self.check(notes, [written(0, 60, .5), written(.5, 60, 1.)])
        merged = result["issues"][-1]
        assert merged["kind"] == "merged" and merged["detection"] == 0
        assert result["merged_count"] == 1 and result["boundary_count"] == 1

    def test_split_note(self):
        notes = [note(0, .4, 60.), note(.45, 1., 60.)]
        result = self.check(notes, [written(0, 60, 1.)])
        kinds = [i["kind"] for i in result["issues"]]
        assert "split" in kinds and result["split_count"] == 1
        assert result["false_positives"] == 1

    def test_boundary_error(self):
        notes = [note(.04, .5, 60.)]
        (issue,) = self.check(notes, [written(0, 60, .5)])["issues"]
        assert issue["kind"] == "boundary" and issue["onset_ms"] == pytest.approx(40)

    def test_validation_sample(self, tmp_path):
        audio, events = sa.make_validation(tmp_path)
        data, _ = compare.analyze(audio, 0., None, tmp_path / "cache")
        notes = [Note(**n) for n in data["notes"]]
        mapped = compare.read_event_map(events)
        result = self.check(notes, mapped)
        assert result["written_events"] == len(sa.VALIDATION_SCORE)
        # The slurred repeated E5 is split at its reattack and the breath in
        # the bar 4 minim is bridged, so every written note is found once.
        assert result["issues"] == []
        assert result["recall"] == result["precision"] == 1
        assert abs(result["median_onset_ms"]) <= 11
        second = next(n for n in notes if abs(n.start - 5.) < .02)
        assert second.start_reason.startswith("reattack")
        minim = next(n for n in notes if abs(n.start - 6.5) < .02)
        assert len(minim.gaps) == 1


class TestExcerpts:
    def test_windows_cover_neighbouring_pairs(self):
        ref = melody([60, 62, 64])
        ren = [note(.5, .7, 60.), note(1.1, 1.3, 64.)]
        result = compare.compare(as_data(ref), as_data(ren))
        windows = compare.excerpt_windows(result["events"], 1, result["render_minus_reference_offset_s"])
        assert windows["reference"] == (0, pytest.approx(.8))
        assert windows["render"] == (.5, pytest.approx(1.3))

    def test_cli_writes_clips_for_flagged_events(self, tmp_path):
        ref = sa.write_wav(tmp_path / "ref.wav", sa.synth(sa.REFERENCE_NOTES, 3.2))
        # The render drops the reference's second note.
        ren = sa.write_wav(tmp_path / "ren.wav", sa.synth(sa.RENDER_NOTES[::2], 3.4, gain=.5))
        hashes = [sha256(ref), sha256(ren)]
        proc = run_cli(ref, ren, "--excerpts", "--no-listening-copy", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        folder = (tmp_path / proc.stdout.strip()).parent
        result = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
        flagged = [e for e in result["events"] if "excerpt" in e]
        assert [e["status"] for e in flagged] == ["unmatched reference event"]
        excerpt = flagged[0]["excerpt"]
        assert excerpt["gain_method"] == "LUFS" and excerpt["render_gain_db"] > 4
        assert excerpt["reference"]["range_s"][0] == pytest.approx(.25, abs=.011)
        assert excerpt["render"]["file"] == "excerpts/event-002-render.wav"
        start, stop = excerpt["render"]["range_s"]
        assert soundfile.info(folder / excerpt["render"]["file"]).duration == pytest.approx(stop - start, abs=1e-3)
        text = (folder / "comparison.md").read_text(encoding="utf-8")
        assert "## Flagged events in musical order" in text
        assert "[render](excerpts/event-002-render.wav)" in text
        assert [sha256(ref), sha256(ren)] == hashes


class TestEventMapCommandLine:
    def test_comparison_with_event_map(self, pair, tmp_path):
        mapped = render_map(tmp_path / "map.csv")
        proc = run_cli(*pair, "--event-map", mapped, cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        folder = (tmp_path / proc.stdout.strip()).parent
        result = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
        assert [e["written"]["beat"] for e in result["events"]] == [1, 2, 3]
        assert result["detector_check"]["recall"] == 1
        assert result["event_map"]["file"] == "map.csv"
        text = (folder / "comparison.md").read_text(encoding="utf-8")
        assert "bar 1 beat 2 · Flute · voice 1" in text
        assert "## Detector check" in text

    def test_check_command(self, tmp_path):
        audio, events = sa.make_validation(tmp_path / "v")
        proc = run_cli("check", audio, events, cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        report = tmp_path / proc.stdout.strip()
        assert report.name == "detector-check.md"
        result = json.loads((report.parent / "detector-check.json").read_text(encoding="utf-8"))
        assert result["detector_check"]["recall"] == 1
        assert "candidates" in result["render"]
        text = report.read_text(encoding="utf-8")
        assert "0 merged" in text and "0 split" in text

    @pytest.mark.parametrize("args, message", [
        (["--event-map", "missing.csv"], "Comparison failed"),
        (["--event-map-offset", "inf"], "--event-map-offset"),
    ])
    def test_bad_event_map_arguments_exit_2(self, pair, tmp_path, args, message):
        proc = run_cli(*pair, *args, cwd=tmp_path)
        assert proc.returncode == 2 and message in proc.stderr
        assert not (tmp_path / "outputs").exists()

    def test_bad_check_map_exits_2(self, pair, tmp_path):
        bad = write_map(tmp_path / "bad.csv", ["x,69"])
        proc = run_cli("check", pair[1], bad, cwd=tmp_path)
        assert proc.returncode == 2 and proc.stderr.startswith("Detector check failed:")


# --------------------------------------------------------------------------- suspect pitches


class TestPitchFlags:
    def flags(self, ref, ren, **kwargs):
        return compare.compare(as_data(ref), as_data(ren), **kwargs)["events"]

    def test_octave_leap_is_flagged_on_its_side(self):
        ref = melody([69, 81, 69])
        ren = melody([69, 81.1, 69])
        rows = self.flags(ref, ren)
        flags = rows[1]["pitch_flags"]
        assert {f["kind"] for f in flags} == {"octave_leap"}
        assert {f["side"] for f in flags} == {"reference", "render"}
        assert flags[0]["evidence"]["neighbours"] == [69, 69]
        assert rows[1]["review"] is True and rows[0]["pitch_flags"] == []
        assert "possible octave error" in rows[1]["reasons"][-1]

    def test_ordinary_leap_is_not_flagged(self):
        assert self.flags(melody([69, 76, 69]), melody([69, 76, 69]))[1]["pitch_flags"] == []

    def test_octave_counterpart(self):
        ref = melody([60, 62, 64])
        ren = melody([60, 74, 64])
        rows = self.flags(ref, ren)
        flagged = [r for r in rows if r["pitch_flags"]]
        assert {r["status"] for r in flagged} == {"unmatched reference event", "extra render event"}
        kinds = [f["kind"] for r in flagged for f in r["pitch_flags"]]
        assert kinds == ["octave_counterpart", "octave_counterpart"]
        assert flagged[0]["pitch_flags"][0]["evidence"]["cents"] == pytest.approx(1200)

    def test_octave_from_written_note(self):
        notes = melody([60, 74])
        events = [written(0, 60), written(.3, 62)]
        rows = self.flags(notes, notes, event_map=events)
        (flag,) = [f for f in rows[1]["pitch_flags"] if f["kind"] == "octave_written"]
        assert flag["side"] == "render" and flag["evidence"]["cents"] == pytest.approx(1200)

    def test_instrument_range(self):
        rows = self.flags(melody([59, 60, 99]), melody([60, 60, 99]), instrument_range=[60., 98.])
        assert [f["side"] for f in rows[0]["pitch_flags"]] == ["reference"]
        assert rows[0]["pitch_flags"][0]["evidence"]["cents_outside"] == pytest.approx(100)
        assert {f["kind"] for f in rows[2]["pitch_flags"]} == {"instrument_range", "tracker_limit"}
        assert rows[1]["pitch_flags"] == []
        assert len(rows) == 3  # flags never remove notes

    def test_tracker_limit(self):
        rows = self.flags(melody([47.5]), melody([47.5]))
        assert [f["kind"] for f in rows[0]["pitch_flags"]] == ["tracker_limit"] * 2


class TestMidiFilters:
    def test_filters_are_explicit_and_reported(self, tmp_path):
        notes = [vars(note(0, .5, 69., confidence=.95)), vars(note(.5, 1., 71., confidence=.7)),
                 vars(note(1., 1.5, 100., confidence=.95))]
        info = compare.write_midi(tmp_path / "n.mid", notes, 0., min_confidence=.8,
                                  instrument_range=[60., 98.])
        (track,) = pretty_midi.PrettyMIDI(str(tmp_path / "n.mid")).instruments
        assert [n.pitch for n in track.notes] == [69]
        assert (info["written"], info["detected"]) == (1, 3)
        assert [e["note"] for e in info["excluded"]] == [1, 2]
        assert info["excluded"][0]["reason"] == "confidence 0.70 below 0.80"
        assert "outside the instrument range" in info["excluded"][1]["reason"]

    def test_no_filters_writes_everything(self, tmp_path):
        notes = [vars(note(0, .5, 69., confidence=.5))]
        info = compare.write_midi(tmp_path / "n.mid", notes, 0.)
        assert info["excluded"] == [] and info["written"] == 1

    def test_cli_reports_filters(self, pair, tmp_path):
        proc = run_cli(*pair, "--midi", "--instrument-range", "A4", "D5", "--midi-skip-out-of-range",
                       "--no-listening-copy", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        folder = (tmp_path / proc.stdout.strip()).parent
        result = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
        assert result["midi"]["written"] == 2
        assert [round(e["pitch"]) for e in result["midi"]["excluded"]] == [76]
        assert result["instrument_range"] == [69, 74]
        assert result["events"][2]["pitch_flags"][0]["kind"] == "instrument_range"
        text = (folder / "comparison.md").read_text(encoding="utf-8")
        assert "reference-notes.mid (2 of 3 detected notes; 1 excluded" in text
        assert "Instrument range: A4 +0¢–D5 +0¢" in text

    @pytest.mark.parametrize("args, message", [
        (["--instrument-range", "A4", "zz"], "--instrument-range needs two pitches"),
        (["--instrument-range", "D5", "A4"], "LOW must be below HIGH"),
        (["--midi-skip-out-of-range"], "needs --instrument-range"),
        (["--midi-min-confidence", 2], "between 0 and 1"),
        (["--midi", "--midi-min-confidence", 1], "excluded every note"),
    ])
    def test_bad_arguments_exit_2(self, pair, tmp_path, args, message):
        proc = run_cli(*pair, *args, cwd=tmp_path)
        assert proc.returncode == 2 and message in proc.stderr
        assert not (tmp_path / "outputs").exists()


# --------------------------------------------------------------------------- phrase alignment


def timed(times, pitches, length=.3):
    return [note(t, t + length, float(p)) for t, p in zip(times, pitches)]


def matched_pairs(result):
    return [(e["reference_note"], e["render_note"]) for e in result["events"] if e["status"] == "matched"]


class TestPhraseAlignment:
    def test_vote_offset(self):
        ref, ren = timed([0, 1, 2], [60, 62, 64]), timed([.3, 1.3, 2.32], [60, 62, 64])
        assert compare.vote_offset(ref, ren) == pytest.approx(.3)
        # A repeated phrase played once: two offsets tie, the smaller wins.
        ref = timed([0, .4, 4, 4.4], [60, 62, 60, 62])
        assert compare.vote_offset(ref, timed([.1, .5], [60, 62])) == pytest.approx(.1)
        assert compare.vote_offset(timed([0], [60]), timed([0], [70])) is None

    def test_missing_repeat_is_paired_by_time(self):
        # Reference plays A B A C; the render plays only A C, starting with the first A.
        a, b, c = [60, 62, 64], [65, 67, 69], [71, 72, 74]
        ref = timed([o + k * .4 for o in (0, 1.5, 3, 4.5) for k in range(3)], a + b + a + c)
        ren = timed([o + k * .4 + .1 for o in (0, 4.5) for k in range(3)], a + c)
        sequence = compare.compare(as_data(ref), as_data(ren))
        phrase = compare.compare(as_data(ref), as_data(ren), alignment="phrase")
        assert matched_pairs(sequence)[:3] == [(6, 0), (7, 1), (8, 2)]  # the wrong A
        assert matched_pairs(phrase) == [(0, 0), (1, 1), (2, 2), (9, 3), (10, 4), (11, 5)]

    def test_gradual_drift_keeps_raw_and_warped_timing(self):
        jitter = np.zeros(20)
        jitter[10] = .12  # one genuinely late note
        ref = timed([k * .5 for k in range(20)], [60 + k % 5 for k in range(20)])
        ren = timed([k * .55 + jitter[k] for k in range(20)], [60 + k % 5 for k in range(20)])
        result = compare.compare(as_data(ref), as_data(ren), alignment="phrase")
        events = result["events"]
        assert [e["status"] for e in events] == ["matched"] * 20
        assert events[-1]["onset_ms"] == pytest.approx(950)  # raw, after the constant offset
        assert events[-1]["warped_onset_ms"] == pytest.approx(0, abs=1)
        assert events[-1]["local_offset_s"] == pytest.approx(.95, abs=.001)
        assert events[10]["warped_onset_ms"] == pytest.approx(120, abs=5)
        assert events[10]["reference_s"] == 5. and events[10]["render_s"] == pytest.approx(5.62)
        alignment = result["alignment"]
        assert alignment["method"] == "phrase" and alignment["max_drift_s"] == 1.
        assert len(alignment["anchors"]) >= 19

    def test_long_pause_of_different_length(self):
        a, b = [60, 62, 64], [67, 65, 64]
        ref = timed([k * .4 for k in range(3)] + [5 + k * .4 for k in range(3)], a + b)
        ren = timed([k * .4 for k in range(3)] + [5.8 + k * .4 for k in range(3)], a + b)
        events = compare.compare(as_data(ref), as_data(ren), alignment="phrase")["events"]
        assert [e["status"] for e in events] == ["matched"] * 6
        assert [round(e["warped_onset_ms"]) for e in events] == [0] * 6
        assert [round(e["onset_ms"]) for e in events] == [0, 0, 0, 800, 800, 800]

    def test_extra_and_missing_notes_with_drift(self):
        pitches = [60, 62, 64, 65, 67, 69, 71, 72]
        ref = timed([k * .5 for k in range(8)], pitches)
        ren = timed([k * .52 for k in range(8)], pitches)
        del ren[3]
        ren.insert(5, note(2.7, 2.8, 80.))
        events = compare.compare(as_data(ref), as_data(ren), alignment="phrase")["events"]
        statuses = [e["status"] for e in events]
        assert statuses.count("matched") == 7
        assert statuses.count("unmatched reference event") == 1
        assert statuses.count("extra render event") == 1

    def test_uncertain_note_is_left_unmatched(self):
        ref = timed([float(k) for k in range(9)], [60, 62] * 4 + [60])
        ren = timed([k + (.5 if k == 4 else 0.) for k in range(9)], [60, 62] * 4 + [60])
        sequence = compare.compare(as_data(ref), as_data(ren))["events"]
        phrase = compare.compare(as_data(ref), as_data(ren), alignment="phrase")["events"]
        assert [e["status"] for e in sequence] == ["matched"] * 9
        assert [e["status"] for e in phrase].count("matched") == 8
        unmatched = [e for e in phrase if e["status"] != "matched"]
        assert {e["reference_note"] for e in unmatched} | {e["render_note"] for e in unmatched} == {4, None}

    def test_max_drift_bounds_the_map(self):
        ref = timed([k * .5 for k in range(30)], [60 + k % 5 for k in range(30)])
        ren = timed([k * .6 for k in range(30)], [60 + k % 5 for k in range(30)])  # 2.9 s by the end
        tight = compare.compare(as_data(ref), as_data(ren), alignment="phrase", max_drift=1.)
        loose = compare.compare(as_data(ref), as_data(ren), alignment="phrase", max_drift=4.)
        assert len(matched_pairs(tight)) < 30
        assert len(matched_pairs(loose)) == 30

    def test_sequence_is_the_default(self):
        result = compare.compare(as_data(melody([60, 62])), as_data(melody([60, 62])))
        assert result["alignment"] == {"method": "sequence"}
        assert "warped_onset_ms" not in result["events"][0]


class TestDiagnostics:
    def test_systematic_tuning(self):
        ref = melody([60, 62, 64, 65])
        ren = [note(n.start, n.end, n.pitch + .6) for n in ref]
        diag = compare.compare(as_data(ref), as_data(ren))["diagnostics"]
        assert diag["tuning_cents"] == pytest.approx(60)
        assert diag["f1_variants"]["strict"] == 0
        assert diag["f1_variants"]["tuning_removed"] == 1
        assert diag["causes"]["tuning"] == 4 and diag["causes"]["pitch"] == 0

    def test_pitch_timing_and_unmatched_causes(self):
        ref = melody([60, 62, 64, 65, 67])
        ren = [note(0, .2, 60.), note(.3, .5, 64.), note(.7, .9, 64.), note(.9, 1.1, 65.)]
        diag = compare.compare(as_data(ref), as_data(ren))["diagnostics"]
        causes = diag["causes"]
        assert causes["pitch"] == 1 and causes["timing"] == 1 and causes["unmatched"] == 1
        assert causes["within tolerance"] == 2
        assert diag["pitch_cents"]["max_abs"] == pytest.approx(200)
        assert diag["onset_ms"]["max_abs"] == pytest.approx(100)
        assert diag["applied"]["alignment"] == "sequence" and "drift_removed" not in diag["f1_variants"]

    def test_drift_is_separated_from_timing(self):
        ref = timed([k * .5 for k in range(20)], [60 + k % 5 for k in range(20)])
        ren = timed([k * .55 for k in range(20)], [60 + k % 5 for k in range(20)])
        diag = compare.compare(as_data(ref), as_data(ren), alignment="phrase")["diagnostics"]
        assert diag["causes"]["drift"] == 19 and diag["causes"]["timing"] == 0
        assert diag["f1_variants"]["strict"] < .2
        assert diag["f1_variants"]["drift_removed"] == 1
        assert diag["applied"]["local_time_map"] is True

    def test_markdown_section(self):
        ref = melody([60, 62])
        result = compare.compare(as_data(ref), as_data(ref), alignment="phrase")
        result.update(reference_cache_hit=False, reference={"peak": .5, "rms": .1},
                      render={"peak": .5, "rms": .1})
        text = compare.markdown(result, 12)
        assert "## What the note match score reflects" in text
        assert "Strict note match F1 (unchanged baseline): 1.00" in text
        assert "phrase alignment" in text and "Reported cents and ms are not corrected" in text

    def test_negative_times_after_the_offset_still_score(self):
        assert compare.note_scores([note(0, .3, 60.)], [note(.05, .3, 60.)], .2)["onset_pitch"]["f1"] == 0


class TestNotationHandoff:
    notes = [vars(note(1.00, 1.48, 69.2)), vars(note(1.52, 1.98, 71.)), vars(note(2.07, 2.4, 72.))]

    def test_tempo_meter_and_quantize(self, tmp_path):
        info = compare.write_midi(tmp_path / "n.mid", self.notes, 1., tempo=60, meter=(3, 8),
                                  quantize=.5)
        midi = pretty_midi.PrettyMIDI(str(tmp_path / "n.mid"))
        assert midi.get_tempo_changes()[1][0] == pytest.approx(30)  # quavers at 60 = crotchets at 30
        (signature,) = midi.time_signature_changes
        assert (signature.numerator, signature.denominator) == (3, 8)
        (track,) = midi.instruments
        assert [(round(n.start, 3), round(n.end, 3)) for n in track.notes] == [
            (0, .5), (.5, 1.), (1., 1.5)]
        first, second, third = info["notes"]
        assert first["start_s"] == 1. and first["cents"] == pytest.approx(20)
        assert third["start_beat"] == 1. and third["quantize_shift_ms"] == pytest.approx(-70)
        assert (third["bar"], third["beat"]) == (1, 2)
        assert info["tempo_bpm"] == 60 and info["meter"] == "3/8" and info["quantize_beats"] == .5

    def test_bars_and_beats_without_quantize(self, tmp_path):
        info = compare.write_midi(tmp_path / "n.mid", self.notes, 0., tempo=120, meter=(2, 4))
        first = info["notes"][0]
        assert first["start_beat"] == pytest.approx(2) and (first["bar"], first["beat"]) == (2, 1)
        assert first["written_start_s"] == pytest.approx(1.) and first["quantize_shift_ms"] == 0

    def test_no_tempo_keeps_performed_timing(self, tmp_path):
        info = compare.write_midi(tmp_path / "n.mid", self.notes, 1.)
        assert [n["written_start_s"] for n in info["notes"]] == pytest.approx([0, .52, 1.07])
        assert "start_beat" not in info["notes"][0] and info["tempo_bpm"] is None

    def test_cli_writes_new_revisions(self, pair, tmp_path):
        def run(*extra):
            proc = run_cli(*pair, "--midi", "--no-listening-copy", *extra, cwd=tmp_path)
            assert proc.returncode == 0, proc.stderr
            folder = (tmp_path / proc.stdout.strip()).parent
            return folder, json.loads((folder / "notation-handoff.json").read_text(encoding="utf-8"))
        first_folder, first = run()
        second_folder, second = run("--midi-tempo", 100, "--midi-meter", "3/4", "--midi-quantize", "1/4")
        _, other_range = run("--reference-end", 3)
        assert (first["revision"], first["previous"]) == (1, None)
        assert (second["revision"], second["previous"]) == (2, first_folder.name)
        assert other_range["revision"] == 1
        assert first["reference"]["sha256"] == sha256(pair[0])
        assert second["tempo_bpm"] == 100 and second["meter"] == "3/4" and second["quantize_beats"] == .25
        assert [round(n["pitch"]) for n in second["notes"]] == [69, 72, 76]
        assert first_folder.exists() and (first_folder / "reference-notes.mid").exists()
        text = (second_folder / "comparison.md").read_text(encoding="utf-8")
        assert "Notation handoff: notation-handoff.json, revision 2 (100 bpm in 3/4, quantized to 0.25 beat)" in text

    @pytest.mark.parametrize("args, message", [
        (["--midi-quantize", "1/4"], "--midi-quantize needs --midi-tempo"),
        (["--midi-tempo", 0], "--midi-tempo must be more than 0"),
        (["--midi-meter", "3/5"], "--midi-meter must look like 3/4"),
        (["--midi-meter", "x"], "--midi-meter must look like 3/4"),
        (["--midi-tempo", 90, "--midi-quantize", "abc"], "--midi-quantize must be a number"),
        (["--midi-tempo", 90, "--midi-quantize", "0"], "--midi-quantize must be a number"),
        (["--max-drift", 0], "--max-drift must be more than 0"),
    ])
    def test_bad_arguments_exit_2(self, pair, tmp_path, args, message):
        proc = run_cli(*pair, "--midi", *args, cwd=tmp_path)
        assert proc.returncode == 2 and message in proc.stderr
        assert not (tmp_path / "outputs").exists()

    def test_cli_phrase_alignment(self, pair, tmp_path):
        proc = run_cli(*pair, "--align", "phrase", "--max-drift", .5, "--no-listening-copy", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        folder = (tmp_path / proc.stdout.strip()).parent
        result = json.loads((folder / "comparison.json").read_text(encoding="utf-8"))
        assert result["alignment"]["method"] == "phrase" and result["alignment"]["max_drift_s"] == .5
        np.testing.assert_allclose([e["warped_onset_ms"] for e in result["events"]], [0, 40, -30], atol=10.5)
        assert result["diagnostics"]["f1_variants"]["strict"] == 1
