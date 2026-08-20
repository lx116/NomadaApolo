"""Gated Yurbaco E2E acceptance and invariant classification (AC-015).

The full-pipeline test is externally gated: it requires ``YURBACO_AUDIO_PATH``
pointing at an out-of-repository source, local ``ffmpeg``/``ffprobe``, cached
``faster-whisper`` ``tiny`` weights, and workspace/output capacity. Every
missing prerequisite skips deterministically; the harness never false-passes.

Invariant scenarios (missing chunk, changed source hash, incoherent export,
surviving workspace) are tested directly against the evidence classifier and
run without any external prerequisite.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from transcriptor.chunk_transcriber import ChunkTranscriber
from transcriptor.chunker import source_fingerprint
from transcriptor.exporters import EXPORT_MARKER, export_aggregate, render_txt
from transcriptor.pipeline import run

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL = "tiny"
MIN_FREE_BYTES = 256 * 1024 * 1024  # ponytail: one volume-wide capacity floor


class _PrerequisiteSkip(Exception):
    """Classified prerequisite block; mapped to ``pytest.skip``, never a pass."""


def _repo_root():
    """Walk up from the test file to the repository root (via ``.git``)."""
    cur = REPO_ROOT
    while True:
        if (cur / ".git").exists():
            return cur.resolve()
        if cur.parent == cur:
            return None
        cur = cur.parent


def _resolve_source():
    """Resolve the configured source, defaulting to the authorized repo fixture."""
    raw = os.environ.get("YURBACO_AUDIO_PATH", str(REPO_ROOT / "Yurbaco.m4a")).strip()
    if not raw:
        raise _PrerequisiteSkip("YURBACO_AUDIO_PATH is not set")
    src = Path(raw).expanduser().resolve()
    if not src.is_file():
        raise _PrerequisiteSkip(f"source is not a readable file: {src}")
    return src


def _require_binaries():
    for name in ("ffmpeg", "ffprobe"):
        if shutil.which(name) is None:
            raise _PrerequisiteSkip(f"{name} not on PATH")


def _require_capacity():
    free = shutil.disk_usage(tempfile.gettempdir()).free
    if free < MIN_FREE_BYTES:
        raise _PrerequisiteSkip(f"insufficient workspace capacity: {free} free bytes")


def _require_cached_weights():
    try:
        from faster_whisper import WhisperModel
        WhisperModel(MODEL, device="cpu", compute_type="int8", local_files_only=True)
    except _PrerequisiteSkip:
        raise
    except Exception as e:  # weights absent -> local_files_only construction fails
        raise _PrerequisiteSkip(
            f"cached {MODEL} weights unavailable: {type(e).__name__}") from e


@pytest.fixture(scope="module")
def e2e_env(tmp_path_factory):
    try:
        source = _resolve_source()
        _require_binaries()
        _require_capacity()
        _require_cached_weights()
    except _PrerequisiteSkip as e:
        pytest.skip(str(e))
    base = tmp_path_factory.mktemp("yurbaco-e2e")
    return {"source": source, "tmp_root": base / "jobs", "output_dir": base / "out"}


def test_yurbaco_full_pipeline(e2e_env):
    """Run stages 01-05 on the external source and validate every invariant."""
    source = e2e_env["source"]
    tmp_root, output_dir = e2e_env["tmp_root"], e2e_env["output_dir"]
    job_id = "yurbaco-e2e"

    before = source_fingerprint(source)

    def offline_factory():
        # ponytail: reuse cached weights, never touch the network mid-pipeline
        return ChunkTranscriber(job_id, before, model=MODEL, language="es",
                                device="cpu", compute_type="int8", vad_filter=True,
                                beam_size=5, local_files_only=True)

    result = run(str(source), str(tmp_root), job_id, output_dir=str(output_dir),
                 model=MODEL, transcriber_factory=offline_factory)
    after = source_fingerprint(source)

    agg = result["aggregate"]
    assert agg["job_id"] == job_id
    assert agg["source_id"] == before  # manifest source identity preserved
    assert agg["contract_version"] == "audio-transcription/v1"
    assert agg["metrics"]["chunks"] >= 1

    violations = validate_evidence(
        source_hash_before=before, source_hash_after=after, aggregate=agg,
        json_path=result["json"], txt_path=result["txt"],
        output_dir=output_dir, leftovers=result["leftovers"],
    )
    assert violations == [], f"contract violations: {violations}"
    assert not (tmp_root / job_id).exists(), "workspace survived cleanup"
    # intermediates never land in the repository
    for p in (result["json"], result["txt"]):
        assert REPO_ROOT not in Path(p).resolve().parents


def test_repo_source_is_authorized_fixture(monkeypatch):
    """The authorized repository-root fixture resolves without copying it."""
    monkeypatch.setenv("YURBACO_AUDIO_PATH", str(REPO_ROOT / "Yurbaco.m4a"))
    assert _resolve_source() == (REPO_ROOT / "Yurbaco.m4a").resolve()


# --- invariant classifier ---------------------------------------------------


def validate_evidence(*, source_hash_before, source_hash_after, aggregate,
                      json_path, txt_path, output_dir, leftovers):
    """Return classified invariant violations (empty list == acceptance)."""
    violations = []
    if source_hash_before != source_hash_after:
        violations.append("changed-source-hash")
    metrics = aggregate.get("metrics", {})
    if metrics.get("chunks_completed") != metrics.get("chunks"):
        violations.append("missing-chunk")
    segments = aggregate.get("segments", [])
    txt_path = Path(txt_path)
    json_path = Path(json_path)
    if not txt_path.exists() or txt_path.read_text(encoding="utf-8") != render_txt(segments):
        violations.append("incoherent-export")
    if not json_path.exists() or json.loads(json_path.read_text(encoding="utf-8")) != aggregate:
        violations.append("json-mismatch")
    if leftovers:
        violations.append("surviving-workspace")
    for seg in segments:
        prov = seg.get("provenance", {})
        if not all(k in prov for k in ("chunk_index", "source_start", "source_end")):
            violations.append("missing-provenance")
            break
    keys = [(s["start"], s["end"], s["provenance"]["chunk_index"], s["id"])
            for s in segments]
    if keys != sorted(keys):
        violations.append("disordered-segments")
    if not (Path(output_dir) / "transcription" / EXPORT_MARKER).exists():
        violations.append("missing-completion-marker")
    return violations


def _segment(seg_id, start, end, text):
    return {"id": seg_id, "start": start, "end": end, "text": text,
            "provenance": {"chunk_index": 0, "source_start": 0.0, "source_end": 300.0}}


def _clean_aggregate():
    return {
        "contract_version": "audio-transcription/v1", "job_id": "j",
        "source_id": "sha256:s", "source_name": "x.m4a", "language": "es",
        "duration": 300.0,
        "segments": [_segment("j:chunk-000000:segment-000000", 1.0, 2.0, "hola mundo")],
        "metrics": {"chunks": 1, "chunks_completed": 1, "segments_before": 1,
                    "segments_after": 1, "reconciliation": [], "ambiguities": []},
    }


def _export_evidence(tmp_path, aggregate):
    out_dir = tmp_path / "out"
    json_path, txt_path = export_aggregate(aggregate, out_dir / "transcription")
    return {"json_path": json_path, "txt_path": txt_path, "output_dir": out_dir}


def _validate(tmp_path, aggregate, **overrides):
    kw = _export_evidence(tmp_path, aggregate)
    kw.update(overrides)
    kw.setdefault("source_hash_before", "sha256:s")
    kw.setdefault("source_hash_after", "sha256:s")
    kw.setdefault("leftovers", [])
    return validate_evidence(aggregate=aggregate, **kw)


def test_clean_evidence_passes_all_invariants(tmp_path):
    assert _validate(tmp_path, _clean_aggregate()) == []


def test_missing_chunk_is_classified(tmp_path):
    agg = _clean_aggregate()
    agg["metrics"]["chunks_completed"] = 0
    assert "missing-chunk" in _validate(tmp_path, agg)


def test_changed_source_hash_is_classified(tmp_path):
    agg = _clean_aggregate()
    violations = _validate(tmp_path, agg,
                           source_hash_before="sha256:a", source_hash_after="sha256:b")
    assert "changed-source-hash" in violations


def test_incoherent_export_is_classified(tmp_path):
    agg = _clean_aggregate()
    kw = _export_evidence(tmp_path, agg)
    kw["txt_path"].write_text("[00:00:01 - 00:00:02]\ntampered text\n", encoding="utf-8")
    violations = validate_evidence(source_hash_before="sha256:s", source_hash_after="sha256:s",
                                   aggregate=agg, leftovers=[], **kw)
    assert "incoherent-export" in violations


def test_surviving_workspace_is_classified(tmp_path):
    agg = _clean_aggregate()
    violations = _validate(tmp_path, agg, leftovers=[str(tmp_path / "chunk-000000.wav")])
    assert "surviving-workspace" in violations
