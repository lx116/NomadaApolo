"""Tests for transcriptor.audio — validation, probing, and normalization."""

import math
import os
import shutil
import wave
from pathlib import Path

import pytest
from subprocess import CompletedProcess

from transcriptor.audio import (
    SUPPORTED_SUFFIXES,
    AudioProbeError,
    NormalizationError,
    normalize_audio,
    probe_duration,
    validate_audio_input,
)


@pytest.mark.parametrize("suffix", [".m4a", ".mp3", ".wav", ".mp4"])
def test_valid_lowercase_suffix(tmp_path, suffix):
    f = tmp_path / f"audio{suffix}"
    f.write_bytes(b"\x00")
    result = validate_audio_input(f)
    assert result == f


@pytest.mark.parametrize("suffix", [".M4A", ".MP3", ".WAV", ".MP4"])
def test_valid_uppercase_suffix(tmp_path, suffix):
    f = tmp_path / f"audio{suffix}"
    f.write_bytes(b"\x00")
    result = validate_audio_input(f)
    assert result == f


def test_missing_path_raises_file_not_found(tmp_path):
    missing = tmp_path / "nonexistent.m4a"
    with pytest.raises(FileNotFoundError, match="not found"):
        validate_audio_input(missing)


def test_directory_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="not a regular file"):
        validate_audio_input(tmp_path)


def test_unsupported_suffix_raises_value_error(tmp_path):
    f = tmp_path / "audio.flac"
    f.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="Unsupported audio suffix"):
        validate_audio_input(f)


def test_no_suffix_raises_value_error(tmp_path):
    f = tmp_path / "audio"
    f.write_bytes(b"\x00")
    with pytest.raises(ValueError, match="Unsupported audio suffix"):
        validate_audio_input(f)


def test_import_isolation():
    """Import succeeds without Django, FFmpeg, or whisper."""
    import importlib
    mod = importlib.import_module("transcriptor.audio")
    assert hasattr(mod, "validate_audio_input")
    assert hasattr(mod, "SUPPORTED_SUFFIXES")


# --- Slice 2 helpers ---


def _make_wav(path, seconds=0.25, rate=16000, channels=1, sampwidth=2):
    """Write a synthetic mono WAV with stdlib wave; return the Path."""
    path = Path(path)
    nframes = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(b"\x00" * (nframes * channels * sampwidth))
    return path


def _write_wav_at(path):
    """Write a valid mono 16 kHz 16-bit WAV at path (fake ffmpeg output)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00" * 4000)


def _mock_which(monkeypatch):
    monkeypatch.setattr(
        "transcriptor.audio.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )


# --- probe_duration ---


def test_probe_duration_parses_valid_stdout(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    captured = {}
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        captured["argv"] = argv
        captured["shell"] = shell
        captured["capture_output"] = capture_output
        captured["text"] = text
        return CompletedProcess(argv, 0, "2453.4\n", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)

    assert probe_duration(src) == 2453.4
    assert captured["shell"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["argv"] == [
        "/usr/bin/ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(src),
    ]


def test_probe_duration_metacharacter_path_is_single_argv(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "we;ird $name && rm.wav")
    captured = {}
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        captured["argv"] = argv
        captured["shell"] = shell
        return CompletedProcess(argv, 0, "1.0\n", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)

    assert probe_duration(src) == 1.0
    assert captured["shell"] is False
    assert str(src) in captured["argv"]  # one argv item, never shell-split


def test_probe_duration_missing_binary_raises_runtime_error(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    monkeypatch.setattr("transcriptor.audio.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffprobe not found"):
        probe_duration(src)


def test_probe_duration_nonzero_exit_raises_with_stderr(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        return CompletedProcess(argv, 1, "", "invalid data found\n")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(AudioProbeError, match="invalid data found"):
        probe_duration(src)


def test_probe_duration_empty_output_raises(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(AudioProbeError, match="empty"):
        probe_duration(src)


@pytest.mark.parametrize("bad", ["N/A\n", "abc\n"])
def test_probe_duration_non_numeric_output_raises(tmp_path, monkeypatch, bad):
    src = _make_wav(tmp_path / "a.wav")
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        return CompletedProcess(argv, 0, bad, "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(AudioProbeError, match="non-numeric"):
        probe_duration(src)


@pytest.mark.parametrize("bad", ["-3.0\n", "inf\n", "nan\n"])
def test_probe_duration_invalid_number_raises(tmp_path, monkeypatch, bad):
    src = _make_wav(tmp_path / "a.wav")
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        return CompletedProcess(argv, 0, bad, "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(AudioProbeError, match="invalid duration"):
        probe_duration(src)


# --- normalize_audio ---


def test_normalize_audio_argv_flags_and_naming(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "recording.wav")
    out_dir = tmp_path / "out"
    captured = {}
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        captured["argv"] = argv
        captured["shell"] = shell
        _write_wav_at(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)

    result = normalize_audio(src, output_dir=out_dir)
    assert result == out_dir / "recording.16k-mono.wav"
    assert result.exists()
    assert captured["shell"] is False
    argv = captured["argv"]
    assert argv[0] == "/usr/bin/ffmpeg"
    assert argv[1:6] == ["-nostdin", "-y", "-i", str(src), "-vn"]
    assert argv[6:12] == ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]


def test_normalize_audio_default_output_dir(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "rec.wav")
    monkeypatch.chdir(tmp_path)
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        _write_wav_at(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)

    result = normalize_audio(src)
    assert result.parent.name == "output"
    assert result.name == "rec.16k-mono.wav"
    assert result.exists()


def test_normalize_audio_preserves_source(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "keep.wav", seconds=0.2)
    original = src.read_bytes()
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        _write_wav_at(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)

    normalize_audio(src, output_dir=tmp_path / "out")
    assert src.read_bytes() == original


def test_normalize_audio_missing_binary_raises(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    monkeypatch.setattr("transcriptor.audio.shutil.which", lambda name: None)
    with pytest.raises(NormalizationError, match="ffmpeg not found"):
        normalize_audio(src, output_dir=tmp_path / "out")


def test_normalize_audio_nonzero_exit_raises_with_stderr(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        return CompletedProcess(argv, 1, "", "codec error\n")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(NormalizationError, match="codec error"):
        normalize_audio(src, output_dir=tmp_path / "out")


def test_normalize_audio_missing_output_raises_and_cleans_up(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    out_dir = tmp_path / "out"
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        os.unlink(argv[-1])  # ffmpeg claims success but produces no file
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(NormalizationError, match="no output"):
        normalize_audio(src, output_dir=out_dir)
    assert list(out_dir.iterdir()) == []


def test_normalize_audio_invalid_wav_raises_and_cleans_up(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    out_dir = tmp_path / "out"
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        Path(argv[-1]).write_bytes(b"not a wav at all")
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    with pytest.raises(NormalizationError, match="Invalid WAV"):
        normalize_audio(src, output_dir=out_dir)
    assert list(out_dir.iterdir()) == []


def test_normalize_audio_rejects_destination_resolving_to_source(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "audio.wav")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    os.symlink(src, out_dir / "audio.16k-mono.wav")  # resolves back to source
    _mock_which(monkeypatch)
    with pytest.raises(NormalizationError, match="source"):
        normalize_audio(src, output_dir=out_dir)


def test_normalize_audio_metacharacter_path_is_single_argv(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "evil; rm -rf $HOME.wav")
    captured = {}
    _mock_which(monkeypatch)

    def fake_run(argv, shell=False, capture_output=False, text=False):
        captured["argv"] = argv
        captured["shell"] = shell
        _write_wav_at(argv[-1])
        return CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("transcriptor.audio.subprocess.run", fake_run)
    normalize_audio(src, output_dir=tmp_path / "out")
    assert captured["shell"] is False
    assert str(src) in captured["argv"]  # one argv item, never shell-split


def test_normalize_audio_output_dir_is_file_raises(tmp_path, monkeypatch):
    src = _make_wav(tmp_path / "a.wav")
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_bytes(b"x")
    _mock_which(monkeypatch)
    with pytest.raises(NormalizationError, match="output directory"):
        normalize_audio(src, output_dir=not_a_dir)


# --- optional real-binary integration ---

_NEEDS_FFMPEG = shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None


@pytest.mark.skipif(_NEEDS_FFMPEG, reason="ffprobe/ffmpeg not installed")
def test_integration_real_probe_and_normalize(tmp_path):
    src = _make_wav(tmp_path / "tone.wav", seconds=0.4)
    duration = probe_duration(src)
    assert math.isfinite(duration) and duration >= 0
    out = normalize_audio(src, output_dir=tmp_path / "out")
    assert out.exists()
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 16000
        assert w.getsampwidth() == 2
