"""Contract and integration tests for transcriptor.chunker (AC-001..AC-005)."""

import json
import shutil
import wave
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from transcriptor.chunker import ChunkingError, chunk_audio, compute_windows, source_fingerprint

_NEEDS_FFMPEG = shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None

def _make_wav(path, seconds=0.25, rate=16000, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds * channels * 2))
    return Path(path)

def _run_writes_wav(argv, shell=False, capture_output=False, text=False):
    _make_wav(argv[-1])
    return CompletedProcess(argv, 0, "", "")

def _run_fails(argv, shell=False, capture_output=False, text=False):
    return CompletedProcess(argv, 1, "", "input/output error\n")

@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr("transcriptor.chunker._resolve_executable", lambda name: f"/usr/bin/{name}")
    return monkeypatch

def test_compute_windows_pure():
    with pytest.raises(ChunkingError, match="greater than 30"):
        compute_windows(30.0)
    with pytest.raises(ChunkingError, match="greater than 30"):
        compute_windows(0.0)
    with pytest.raises(ChunkingError, match="overlap"):
        compute_windows(31.0, overlap=300.0)
    assert compute_windows(30.1) == []
    assert compute_windows(299.9) == []
    assert len(compute_windows(300.0)) == 1
    ws = compute_windows(601.0, overlap=1.0)
    assert len(ws) == 3
    assert ws[0]["source_end"] == 300.0 and ws[0]["overlap_after"] == 1.0
    assert ws[0]["content_end"] == 299.0
    assert ws[1]["source_start"] == 299.0 and ws[2]["source_end"] == 601.0
    assert all(w["source_end"] - w["source_start"] <= 300.0 for w in ws)

def test_short_source_bypasses(tmp_path, mocked):
    src = _make_wav(tmp_path / "short.wav")
    mocked.setattr("transcriptor.chunker.probe_duration", lambda p: 299.9)
    mocked.setattr("transcriptor.chunker.subprocess.run",
                   lambda *a, **k: pytest.fail("no extraction for bypassed source"))
    manifest = json.loads(chunk_audio(src, tmp_path / "ws", "job-1").read_text())
    assert manifest["bypassed"] is True and manifest["chunks"][0]["path"] is None
    assert manifest["source_id"] == source_fingerprint(src)
    assert manifest["source_id"].startswith("sha256:")
    assert not (tmp_path / "ws" / "job-1" / "chunks").exists()

def test_long_source_writes_chunks_and_manifest(tmp_path, mocked):
    src = _make_wav(tmp_path / "evil; rm -rf $HOME.wav")  # metacharacter path
    mocked.setattr("transcriptor.chunker.probe_duration", lambda p: 601.0)
    captured = {}

    def fake_run(argv, shell=False, capture_output=False, text=False):
        captured["argv"], captured["shell"] = argv, shell
        _make_wav(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    mocked.setattr("transcriptor.chunker.subprocess.run", fake_run)
    manifest = json.loads(chunk_audio(src, tmp_path / "ws", "job-2").read_text())
    assert [c["path"] for c in manifest["chunks"]] == [f"chunks/{i:06d}.wav" for i in range(3)]
    assert captured["shell"] is False and str(src) in captured["argv"]
    assert (tmp_path / "ws" / "job-2" / "chunks" / "000002.wav").exists()

def test_workspace_safety_and_source_immutability(tmp_path, mocked):
    src = _make_wav(tmp_path / "a.wav")
    original = src.read_bytes()
    mocked.setattr("transcriptor.chunker.probe_duration", lambda p: 601.0)
    mocked.setattr("transcriptor.chunker.subprocess.run", _run_writes_wav)
    (tmp_path / "ws" / "job-3").mkdir(parents=True)
    with pytest.raises(ChunkingError, match="already exists"):
        chunk_audio(src, tmp_path / "ws", "job-3")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(ChunkingError, match="repository"):
        chunk_audio(src, repo, "job-4")
    manifest = json.loads(chunk_audio(src, tmp_path / "ws", "job-5").read_text())
    assert src.read_bytes() == original
    assert manifest["source_id"] == source_fingerprint(src)

def test_interrupted_write_leaves_no_partial(tmp_path, mocked):
    src = _make_wav(tmp_path / "a.wav")
    original = src.read_bytes()
    mocked.setattr("transcriptor.chunker.probe_duration", lambda p: 601.0)
    mocked.setattr("transcriptor.chunker.subprocess.run", _run_fails)
    with pytest.raises(ChunkingError, match="input/output error"):
        chunk_audio(src, tmp_path / "ws", "job-6")
    chunks_dir = tmp_path / "ws" / "job-6" / "chunks"
    assert list(chunks_dir.iterdir()) == []
    assert not (tmp_path / "ws" / "job-6" / "manifest.json").exists()
    assert src.read_bytes() == original

@pytest.mark.skipif(_NEEDS_FFMPEG, reason="ffprobe/ffmpeg not installed")
def test_integration_real_short_source_bypasses(tmp_path):
    src = _make_wav(tmp_path / "short.wav", seconds=30.5)
    manifest = json.loads(chunk_audio(src, tmp_path / "ws", "job-real").read_text())
    assert manifest["bypassed"] is True and len(manifest["chunks"]) == 1
    assert manifest["source_id"] == source_fingerprint(src)
