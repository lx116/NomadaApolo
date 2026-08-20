"""Contract tests for transcriptor.state (AC-005, AC-012, AC-013)."""

import json
import os

import pytest

from transcriptor.state import JobState, StateError, load_checkpoint


def _state(workspace):
    return JobState(workspace, job_id="job-1", source_id="sha256:src",
                    config_fingerprint="sha256:cfg")


def test_valid_transition_sequence_and_atomic_checkpoint(tmp_path):
    st = _state(tmp_path / "ws")
    for nxt in ("chunking", "preprocessing", "transcribing", "aggregating", "completed"):
        st.transition(nxt)
    data = json.loads((tmp_path / "ws" / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["state"] == "completed"
    assert data["contract_version"] == "audio-job/v1"
    assert data["source_id"] == "sha256:src"
    assert data["config_fingerprint"] == "sha256:cfg"
    assert data["cancel_requested"] is False


def test_invalid_transition_is_rejected(tmp_path):
    st = _state(tmp_path / "ws")
    with pytest.raises(StateError):
        st.transition("transcribing")  # created -> transcribing skips stages
    assert st.state == "created"


def test_incompatible_resume_is_rejected(tmp_path):
    st = _state(tmp_path / "ws")
    for nxt in ("chunking", "preprocessing", "transcribing"):
        st.transition(nxt)
    with pytest.raises(StateError) as ei:
        load_checkpoint(tmp_path / "ws", job_id="job-1", source_id="sha256:OTHER",
                        config_fingerprint="sha256:cfg")
    assert "mismatch" in str(ei.value)


def test_compatible_resume_reuses_completed_chunks(tmp_path):
    st = _state(tmp_path / "ws")
    for nxt in ("chunking", "preprocessing", "transcribing"):
        st.transition(nxt)
    st.mark_chunk_completed(0, "sha256:art0")
    st.mark_chunk_completed(1, "sha256:art1")

    resumed = load_checkpoint(tmp_path / "ws", job_id="job-1", source_id="sha256:src",
                              config_fingerprint="sha256:cfg")
    assert resumed.state == "transcribing"
    assert resumed.completed_chunk_indexes() == {0, 1}
    assert resumed.chunks[0]["artifact_hash"] == "sha256:art0"


def test_active_chunk_is_checkpointed_and_cleared_on_completion(tmp_path):
    st = _state(tmp_path / "ws")
    st.transition("chunking")
    st.transition("preprocessing")
    st.transition("transcribing")

    st.mark_chunk_started(3)
    data = json.loads((tmp_path / "ws" / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["active_chunk"]["index"] == 3
    assert data["active_chunk"]["started_at"].endswith("Z")
    resumed = load_checkpoint(tmp_path / "ws", job_id="job-1", source_id="sha256:src",
                              config_fingerprint="sha256:cfg")
    assert resumed.active_chunk == data["active_chunk"]

    st.mark_chunk_completed(3, "sha256:art3")
    data = json.loads((tmp_path / "ws" / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["active_chunk"] is None


def test_cancellation_persists_and_blocks_new_work(tmp_path):
    st = _state(tmp_path / "ws")
    st.transition("chunking")
    st.request_cancel()
    assert st.cancel_requested is True
    data = json.loads((tmp_path / "ws" / "checkpoint.json").read_text(encoding="utf-8"))
    assert data["cancel_requested"] is True
    st.transition("cancelled")
    with pytest.raises(StateError):
        st.transition("completed")  # terminal: no further work


def test_cleanup_error_reports_leftover_and_preserves_source(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    partial = ws / "partial.tmp"
    partial.write_text("temp")
    source = tmp_path / "source.wav"
    source.write_bytes(b"SOURCE-BYTES")

    st = _state(ws)
    real_unlink = os.unlink

    def failing_unlink(path):
        if str(path).endswith("partial.tmp"):
            raise OSError("simulated cleanup failure")
        return real_unlink(path)

    monkeypatch.setattr("transcriptor.state.os.unlink", failing_unlink)

    leftovers = st.cleanup()
    assert leftovers  # reported, never hidden
    assert partial.exists()  # the failing artifact survives and is reported
    assert source.read_bytes() == b"SOURCE-BYTES"  # source untouched (AC-005)


def test_cleanup_is_idempotent_and_empty_when_absent(tmp_path):
    st = _state(tmp_path / "ws")
    assert st.cleanup() == []  # nothing to clean
    st.workspace.mkdir()
    (st.workspace / "tmp.bin").write_text("x")
    assert st.cleanup() == []
    assert not st.workspace.exists()
    assert st.cleanup() == []  # idempotent
