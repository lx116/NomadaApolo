"""Contract and integration tests for transcriptor.preprocess (AC-005..AC-007)."""

import shutil
import wave
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from transcriptor.preprocess import PreprocessError, preprocess_chunk

_NEEDS_FFMPEG = shutil.which("ffmpeg") is None

def _make_wav(path, seconds=0.25, rate=16000, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds * channels * 2))
    return Path(path)

def _run_fails(argv, shell=False, capture_output=False, text=False):
    return CompletedProcess(argv, 1, "", "codec error\n")

def _run_garbage(argv, shell=False, capture_output=False, text=False):
    Path(argv[-1]).write_bytes(b"not a wav")
    return CompletedProcess(argv, 0, "", "")

def _run_missing(name):
    raise RuntimeError(f"{name} not found")

@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr("transcriptor.preprocess._resolve_executable", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("transcriptor.preprocess.ffmpeg_version", lambda f: "ffmpeg version 7.1")
    return monkeypatch

def _valid_ffmpeg(calls):
    def fake_run(argv, shell=False, capture_output=False, text=False):
        calls.append((argv, shell))
        _make_wav(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    return fake_run

def test_argv_flags_naming_and_output(tmp_path, mocked):
    src = _make_wav(tmp_path / "evil; rm -rf $HOME.wav")  # metacharacter path
    calls = []
    mocked.setattr("transcriptor.preprocess.subprocess.run", _valid_ffmpeg(calls))
    result = preprocess_chunk(src, tmp_path / "out", 3, source_start=0.0, source_end=300.0)
    assert result["output_audio"].endswith("000003.wav") and Path(result["output_audio"]).exists()
    argv, shell = calls[0]
    assert shell is False and argv[0] == "/usr/bin/ffmpeg" and str(src) in argv
    assert argv[argv.index("-ac") + 1] == "1" and argv[argv.index("-ar") + 1] == "16000"
    assert argv[argv.index("-c:a") + 1] == "pcm_s16le"
    assert "-af" not in argv  # default: no filter, no heuristic rewrites content

def test_vad_and_denoise_are_distinct(tmp_path, mocked):
    src = _make_wav(tmp_path / "chunk.wav")
    calls = []
    mocked.setattr("transcriptor.preprocess.subprocess.run", _valid_ffmpeg(calls))
    vad = preprocess_chunk(src, tmp_path / "out", 0, source_start=10.0, source_end=310.0,
                           vad_enabled=True)
    den = preprocess_chunk(src, tmp_path / "out", 1, source_start=0.0, source_end=300.0,
                           denoise_enabled=True)
    assert vad["vad"] == {"enabled": True, "mode": "silence-context-only"}
    assert vad["denoising"] == {"enabled": False, "filter": None}
    assert den["vad"] == {"enabled": False, "mode": None}
    assert den["denoising"] == {"enabled": True, "filter": "afftdn"}
    assert (vad["sample_rate"], vad["channels"], vad["sample_format"]) == (16000, 1, "s16")
    assert vad["source_start"] == 10.0 and vad["ffmpeg_version"].startswith("ffmpeg version")
    assert calls[0][0][calls[0][0].index("-af") + 1].startswith("silenceremove")
    assert calls[1][0][calls[1][0].index("-af") + 1] == "afftdn"

def test_failures_clean_partial_and_report_chunk(tmp_path, mocked):
    src = _make_wav(tmp_path / "chunk.wav")
    out_dir = tmp_path / "out"
    mocked.setattr("transcriptor.preprocess.subprocess.run", _run_fails)
    with pytest.raises(PreprocessError) as exc:
        preprocess_chunk(src, out_dir, 2, source_start=0.0, source_end=300.0)
    assert "chunk 2" in str(exc.value) and "codec error" in str(exc.value)
    assert list(out_dir.iterdir()) == []
    mocked.setattr("transcriptor.preprocess.subprocess.run", _run_garbage)
    with pytest.raises(PreprocessError, match="chunk 0"):
        preprocess_chunk(src, out_dir, 0, source_start=0.0, source_end=300.0)
    assert list(out_dir.iterdir()) == []
    mocked.setattr("transcriptor.preprocess._resolve_executable", _run_missing)
    with pytest.raises(PreprocessError, match="ffmpeg not found"):
        preprocess_chunk(src, out_dir, 0, source_start=0.0, source_end=300.0)

@pytest.mark.skipif(_NEEDS_FFMPEG, reason="ffmpeg not installed")
def test_integration_real_preprocess_mono_16k(tmp_path):
    src = _make_wav(tmp_path / "stereo.wav", seconds=0.3, rate=44100, channels=2)
    result = preprocess_chunk(src, tmp_path / "out", 0, source_start=0.0, source_end=0.3)
    out = Path(result["output_audio"])
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
