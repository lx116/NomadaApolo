"""Contract tests for transcriptor.aggregation (AC-009..AC-011)."""

import pytest

from transcriptor.aggregation import AggregationError, aggregate


def _seg(chunk_index, local_index, start, end, text):
    return {
        "segment_id": f"job-1:chunk-{chunk_index:06d}:segment-{local_index:06d}",
        "chunk_index": chunk_index, "start": start, "end": end,
        "local_start": 0.0, "local_end": 0.0, "text": text,
    }


def _result(chunk_index, source_start, source_end, segments):
    return {
        "contract_version": "audio-transcription/v1", "job_id": "job-1",
        "source_id": "sha256:abc", "config_fingerprint": "sha256:cfg",
        "chunk_index": chunk_index, "source_start": source_start,
        "source_end": source_end, "segments": segments, "metrics": {},
    }


def _aggregate(results, required=None):
    return aggregate(
        results,
        required if required is not None else [r["chunk_index"] for r in results],
        job_id="job-1", source_id="sha256:abc", source_name="Yurbaco.m4a",
        duration=600.0, language="es",
    )


def test_identical_overlap_is_deduped_traceably():
    # chunk 0 and chunk 1 overlap in [299, 300] with identical text
    results = [
        _result(0, 0.0, 300.0, [_seg(0, 0, 298.0, 300.0, "hola mundo")]),
        _result(1, 299.0, 599.0, [_seg(1, 0, 299.0, 301.0, "hola mundo")]),
    ]
    out = _aggregate(results)
    assert len(out["segments"]) == 1
    assert out["segments"][0]["id"] == "job-1:chunk-000000:segment-000000"
    assert out["metrics"]["segments_before"] == 2
    assert out["metrics"]["segments_after"] == 1
    assert out["metrics"]["reconciliation"] == [
        {"removed": "job-1:chunk-000001:segment-000000",
         "kept": "job-1:chunk-000000:segment-000000",
         "reason": "identical-overlap"},
    ]


def test_keep_on_doubt_preserves_partial_and_empty_overlap():
    # partially-different overlap: both kept + ambiguity marked
    partial = [
        _result(0, 0.0, 300.0, [_seg(0, 0, 298.0, 300.0, "hola mundo")]),
        _result(1, 299.0, 599.0, [_seg(1, 0, 299.0, 301.0, "hola mundo chao")]),
    ]
    out = _aggregate(partial)
    assert [s["text"] for s in out["segments"]] == ["hola mundo", "hola mundo chao"]
    assert out["metrics"]["ambiguities"] == [
        {"a": "job-1:chunk-000000:segment-000000",
         "b": "job-1:chunk-000001:segment-000000", "reason": "partial-overlap"},
    ]
    # empty text (silence) is never treated as an identical duplicate
    empty = [
        _result(0, 0.0, 300.0, [_seg(0, 0, 298.0, 300.0, "")]),
        _result(1, 299.0, 599.0, [_seg(1, 0, 299.0, 301.0, "")]),
    ]
    out = _aggregate(empty)
    assert len(out["segments"]) == 2
    assert out["metrics"]["reconciliation"] == []


def test_missing_chunk_blocks_aggregation():
    results = [
        _result(0, 0.0, 300.0, [_seg(0, 0, 0.0, 1.0, "a")]),
        _result(1, 299.0, 599.0, [_seg(1, 0, 1.0, 2.0, "b")]),
    ]
    with pytest.raises(AggregationError) as ei:
        _aggregate(results, required=[0, 1, 2])
    assert "missing chunk" in str(ei.value) and "2" in str(ei.value)


def test_sort_is_deterministic_by_contract_key():
    # results arrive out of order; segments must sort by (start, end, chunk_index, segment_id)
    results = [
        _result(1, 299.0, 599.0, [
            _seg(1, 0, 5.0, 6.0, "z"),
            _seg(1, 1, 5.0, 7.0, "later-end"),
        ]),
        _result(0, 0.0, 300.0, [_seg(0, 0, 10.0, 11.0, "a")]),
    ]
    out = _aggregate(results)
    assert [s["id"] for s in out["segments"]] == [
        "job-1:chunk-000001:segment-000000",  # start 5.0, end 6.0
        "job-1:chunk-000001:segment-000001",  # start 5.0, end 7.0
        "job-1:chunk-000000:segment-000000",  # start 10.0
    ]
    assert _aggregate(results) == out  # repeatable


def test_provenance_and_metrics_are_preserved():
    results = [_result(0, 0.0, 300.0, [_seg(0, 0, 10.0, 11.0, "uno")])]
    out = _aggregate(results)
    assert out["segments"][0]["provenance"] == {
        "chunk_index": 0, "source_start": 0.0, "source_end": 300.0,
    }
    assert out["metrics"]["chunks"] == 1 and out["metrics"]["chunks_completed"] == 1


def test_invalid_timestamp_is_rejected():
    results = [_result(0, 0.0, 300.0, [_seg(0, 0, 5.0, 3.0, "backwards")])]
    with pytest.raises(AggregationError):
        _aggregate(results)
