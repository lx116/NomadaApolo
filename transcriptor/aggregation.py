"""Deterministic conservative aggregation of per-chunk results (AC-009..AC-011)."""

import math

AGGREGATE_CONTRACT = "audio-transcription/v1"


class AggregationError(Exception):
    """Raised when results are incomplete or invalid."""


def _sort_key(seg):
    return (seg["start"], seg["end"], seg["chunk_index"], seg["segment_id"])


def _validate_segment(seg, chunk_index):
    try:
        start, end = float(seg["start"]), float(seg["end"])
    except (KeyError, TypeError, ValueError):
        raise AggregationError(
            f"chunk {chunk_index}: invalid timestamp in segment {seg.get('segment_id')}") from None
    if not (math.isfinite(start) and math.isfinite(end)) or start < 0 or end < start:
        raise AggregationError(
            f"chunk {chunk_index}: invalid range [{start}, {end}] in segment {seg.get('segment_id')}")


def _reconcile(segments):
    """Adjacent-pair scan after sort; overlaps only span adjacent segments."""
    kept, reconciliation, ambiguities = [], [], []
    prev = None
    for seg in segments:
        if prev is not None and seg["start"] < prev["end"]:
            if prev["text"].strip() and prev["text"].strip() == seg["text"].strip():
                reconciliation.append({"removed": seg["segment_id"], "kept": prev["segment_id"],
                                       "reason": "identical-overlap"})
                continue  # prev stays the anchor for chained overlaps
            ambiguities.append({"a": prev["segment_id"], "b": seg["segment_id"],
                                "reason": "partial-overlap"})
        kept.append(seg)
        prev = seg
    return kept, reconciliation, ambiguities


def aggregate(results, required_chunks, *, job_id, source_id, source_name,
              duration, language=None):
    """Validate completeness, sort deterministically, reconcile identical overlap."""
    by_chunk = {}
    for r in results:
        idx = r["chunk_index"]
        if idx in by_chunk:
            raise AggregationError(f"duplicate result for chunk {idx}")
        by_chunk[idx] = r
    required = list(required_chunks)
    missing = sorted(set(required) - set(by_chunk))
    if missing:
        raise AggregationError(f"missing chunk(s): {missing}")
    unknown = sorted(set(by_chunk) - set(required))
    if unknown:
        raise AggregationError(f"unexpected chunk(s): {unknown}")

    segments = []
    for idx in sorted(required):
        r = by_chunk[idx]
        for seg in r["segments"]:
            _validate_segment(seg, idx)
            segments.append({**seg, "source_start": r["source_start"],
                             "source_end": r["source_end"]})
    segments.sort(key=_sort_key)
    final, reconciliation, ambiguities = _reconcile(segments)

    return {
        "contract_version": AGGREGATE_CONTRACT,
        "job_id": job_id, "source_id": source_id, "source_name": source_name,
        "language": language, "duration": duration,
        "segments": [{"id": s["segment_id"], "start": s["start"], "end": s["end"],
                      "text": s["text"],
                      "provenance": {"chunk_index": s["chunk_index"],
                                     "source_start": s["source_start"],
                                     "source_end": s["source_end"]}} for s in final],
        "metrics": {"chunks": len(required), "chunks_completed": len(by_chunk),
                    "segments_before": len(segments), "segments_after": len(final),
                    "reconciliation": reconciliation, "ambiguities": ambiguities},
    }
