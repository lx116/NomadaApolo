"""Synchronous audio chunking: deterministic windows, manifest, source immutability (AC-001..AC-005)."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from transcriptor.audio import _resolve_executable, probe_duration, validate_audio_input

CHUNK_SECONDS = 300.0
DEFAULT_OVERLAP = 1.0
MIN_AUDIO_SECONDS = 30.0
MANIFEST_CONTRACT = "audio-chunk/v1"

class ChunkingError(Exception):
    """Raised when chunking fails."""

def source_fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"

def compute_windows(duration, chunk_seconds=CHUNK_SECONDS, overlap=DEFAULT_OVERLAP):
    """Deterministic windows; empty when the source is shorter than one chunk."""
    duration, chunk_seconds, overlap = float(duration), float(chunk_seconds), float(overlap)
    if duration <= MIN_AUDIO_SECONDS:
        raise ChunkingError(f"audio duration must be greater than {MIN_AUDIO_SECONDS} seconds")
    if chunk_seconds <= 0 or overlap < 0 or overlap >= chunk_seconds:
        raise ChunkingError("chunk_seconds must be positive and overlap must be below chunk_seconds")
    if duration < chunk_seconds:
        return []
    windows, start, index = [], 0.0, 0
    while start < duration - 1e-9:
        end = min(start + chunk_seconds, duration)
        overlap_before = overlap if index > 0 else 0.0
        overlap_after = overlap if end < duration - 1e-9 else 0.0
        content_end = end - overlap_after
        windows.append({
            "chunk_index": index, "source_start": round(start, 6),
            "source_end": round(end, 6), "content_start": round(start + overlap_before, 6),
            "content_end": round(content_end, 6), "overlap_before": round(overlap_before, 6),
            "overlap_after": round(overlap_after, 6),
        })
        if content_end >= duration - 1e-9:
            break
        start, index = content_end, index + 1
    return windows

def _reject_unsafe_workspace(workspace):
    resolved = workspace.resolve()
    current = resolved
    while True:
        if (current / ".git").exists():
            raise ChunkingError(f"workspace must not live inside a repository: {resolved}")
        if current.parent == current:
            break
        current = current.parent
    if resolved.exists():
        raise ChunkingError(f"workspace already exists: {resolved}")

def _write_json_atomic(path, obj):
    fd, staged = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(staged, str(path))

def _extract_chunk(ffmpeg, source, window, chunks_dir):
    final = chunks_dir / f"{window['chunk_index']:06d}.wav"
    fd, staged = tempfile.mkstemp(prefix=".c.", suffix=".wav", dir=str(chunks_dir))
    os.close(fd)
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-y", "-ss", str(window["source_start"]), "-i", str(source),
             "-t", str(window["source_end"] - window["source_start"]),
             "-vn", "-c:a", "pcm_s16le", staged],
            shell=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ChunkingError(f"chunk {window['chunk_index']}: ffmpeg failed: {stderr or 'ffmpeg failed'}")
        if not os.path.exists(staged):
            raise ChunkingError(f"chunk {window['chunk_index']}: ffmpeg produced no output")
        os.replace(staged, str(final))
    finally:
        if os.path.exists(staged):
            os.unlink(staged)

def chunk_audio(source, tmp_root, job_id, chunk_seconds=CHUNK_SECONDS, overlap=DEFAULT_OVERLAP):
    """Chunk ``source`` into an isolated workspace; return the manifest path."""
    src = validate_audio_input(source)
    workspace = Path(tmp_root) / job_id
    _reject_unsafe_workspace(workspace)
    duration = probe_duration(src)
    windows = compute_windows(duration, chunk_seconds, overlap)
    workspace.mkdir(parents=True, exist_ok=False, mode=0o700)
    chunks = []
    if windows:
        chunks_dir = workspace / "chunks"
        chunks_dir.mkdir()
        ffmpeg = _resolve_executable("ffmpeg")
        for w in windows:
            _extract_chunk(ffmpeg, src, w, chunks_dir)
            chunks.append({**w, "path": f"chunks/{w['chunk_index']:06d}.wav"})
    else:
        chunks.append({
            "chunk_index": 0, "source_start": 0.0, "source_end": round(duration, 6),
            "content_start": 0.0, "content_end": round(duration, 6),
            "overlap_before": 0.0, "overlap_after": 0.0, "path": None,
        })
    manifest = {
        "contract_version": MANIFEST_CONTRACT, "job_id": job_id,
        "source_id": source_fingerprint(src), "source_name": src.name,
        "source_duration": round(duration, 6), "chunk_seconds": chunk_seconds,
        "overlap_seconds": overlap, "bypassed": not windows, "chunks": chunks,
    }
    manifest_path = workspace / "manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return manifest_path
