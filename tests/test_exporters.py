"""Contract tests for transcriptor.exporters (AC-009..AC-011)."""

import json

import pytest

from transcriptor.exporters import export_aggregate, format_timestamp, render_txt


def _seg(seg_id, start, end, text):
    return {
        "id": seg_id, "start": start, "end": end, "text": text,
        "provenance": {"chunk_index": 0, "source_start": 0.0, "source_end": 300.0},
    }


def _aggregate(segments):
    return {
        "contract_version": "audio-transcription/v1", "job_id": "job-1",
        "source_id": "sha256:abc", "source_name": "Yurbaco.m4a", "language": "es",
        "duration": 3723.0, "segments": segments,
        "metrics": {"chunks": 1, "segments_before": 1, "segments_after": 1},
    }


def test_valid_job_publishes_json_and_txt_with_same_sequence(tmp_path):
    agg = _aggregate([
        _seg("a", 0.0, 2.5, "hola"),
        _seg("b", 3661.9, 3663.1, "mundo"),
    ])
    json_path, txt_path = export_aggregate(agg, tmp_path)
    assert (tmp_path / "export.complete").exists()  # announced only after both promote
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert [s["id"] for s in data["segments"]] == ["a", "b"]
    assert txt_path.read_text(encoding="utf-8") == (
        "[00:00:00 - 00:00:02]\nhola\n[01:01:02 - 01:01:03]\nmundo\n")


def test_timestamps_and_render():
    assert format_timestamp(0.0) == "00:00:00"
    assert format_timestamp(3661.9) == "01:01:02"
    assert format_timestamp(59.4) == "00:00:59"
    segments = [_seg("a", 0.0, 2.5, "hola"), _seg("b", 3661.9, 3663.1, "mundo")]
    assert render_txt(segments) == (
        "[00:00:00 - 00:00:02]\nhola\n[01:01:02 - 01:01:03]\nmundo\n")


def test_pair_failure_removes_promoted_sibling(tmp_path, monkeypatch):
    agg = _aggregate([_seg("a", 0.0, 2.5, "hola")])
    monkeypatch.setattr("transcriptor.exporters.render_txt",
                        lambda segments: (_ for _ in ()).throw(RuntimeError("txt render failed")))
    with pytest.raises(RuntimeError):
        export_aggregate(agg, tmp_path)
    assert not (tmp_path / "transcription.json").exists()  # promoted sibling removed
    assert not (tmp_path / "transcription.txt").exists()
    assert not (tmp_path / "export.complete").exists()  # never announced
