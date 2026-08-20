"""Versioned atomic job state, cancellation, and idempotent cleanup (AC-005, AC-012, AC-013)."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

JOB_CONTRACT = "audio-job/v1"

TRANSITIONS = {
    "created": {"chunking", "failed", "cancelled"},
    "chunking": {"preprocessing", "failed", "cancelled"},
    "preprocessing": {"transcribing", "failed", "cancelled"},
    "transcribing": {"aggregating", "failed", "cancelled"},
    "aggregating": {"completed", "failed", "cancelled"},
    "completed": (), "failed": (), "cancelled": (),
}


class StateError(Exception):
    """Raised on invalid transitions or incompatible resume."""


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path, obj):
    fd, staged = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(staged, str(path))


class JobState:
    """Owns the ``audio-job/v1`` checkpoint inside the job workspace."""

    def __init__(self, workspace, *, job_id, source_id, config_fingerprint):
        self.workspace = Path(workspace)
        self.job_id = job_id
        self.source_id = source_id
        self.config_fingerprint = config_fingerprint
        self.state = "created"
        self.cancel_requested = False
        self.chunks = []
        self.active_chunk = None

    @property
    def checkpoint_path(self):
        return self.workspace / "checkpoint.json"

    def transition(self, new_state):
        if new_state not in TRANSITIONS[self.state]:
            raise StateError(f"invalid transition {self.state} -> {new_state}")
        self.state = new_state
        self.checkpoint()

    def checkpoint(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(self.checkpoint_path, {
            "contract_version": JOB_CONTRACT, "job_id": self.job_id,
            "source_id": self.source_id, "state": self.state,
            "cancel_requested": self.cancel_requested, "chunks": self.chunks,
            "active_chunk": self.active_chunk,
            "config_fingerprint": self.config_fingerprint, "updated_at": _now_iso(),
        })

    def request_cancel(self):
        self.cancel_requested = True
        self.checkpoint()

    def mark_chunk_started(self, chunk_index):
        self.active_chunk = {"index": chunk_index, "started_at": _now_iso()}
        self.checkpoint()

    def mark_chunk_completed(self, chunk_index, artifact_hash, duration_s=None):
        update = {"state": "completed", "artifact_hash": artifact_hash}
        if duration_s is not None:
            update["duration_s"] = round(float(duration_s), 2)
        for c in self.chunks:
            if c["index"] == chunk_index:
                c.update(update)
                break
        else:
            self.chunks.append({"index": chunk_index, **update})
        self.active_chunk = None
        self.checkpoint()

    def completed_chunk_indexes(self):
        return {c["index"] for c in self.chunks if c["state"] == "completed"}

    def cleanup(self):
        """Idempotently remove the owned workspace; report unremovable leftovers.

        Never touches anything outside the workspace (source and finals live
        outside), so AC-005 source-immutability holds even on failure.
        """
        leftovers = []
        ws = str(self.workspace)
        if not os.path.exists(ws):
            return leftovers
        for root, dirs, files in os.walk(ws, topdown=False):
            for name in files:
                p = os.path.join(root, name)
                try:
                    os.unlink(p)
                except OSError:
                    leftovers.append(p)
            for name in dirs:
                p = os.path.join(root, name)
                try:
                    os.rmdir(p)
                except OSError:
                    leftovers.append(p)
        try:
            os.rmdir(ws)
        except OSError:
            leftovers.append(ws)
        return leftovers


def load_checkpoint(workspace, *, job_id, source_id, config_fingerprint):
    """Reopen a checkpoint; reject incompatible source/config (no reuse)."""
    path = Path(workspace) / "checkpoint.json"
    if not path.exists():
        raise StateError(f"no checkpoint at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("contract_version") != JOB_CONTRACT:
        raise StateError("incompatible checkpoint contract version")
    if (data.get("job_id") != job_id or data.get("source_id") != source_id
            or data.get("config_fingerprint") != config_fingerprint):
        raise StateError("incompatible resume: job_id/source_id/config_fingerprint mismatch")
    state = JobState(workspace, job_id=job_id, source_id=source_id,
                     config_fingerprint=config_fingerprint)
    state.state = data.get("state", "created")
    state.cancel_requested = data.get("cancel_requested", False)
    state.chunks = data.get("chunks", [])
    state.active_chunk = data.get("active_chunk")
    return state
