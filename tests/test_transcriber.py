"""Tests for transcriptor.transcriber — deterministic contract plus one optional real-model integration test."""

import importlib.util
import math
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from transcriptor.config import TranscriptionConfig
from transcriptor.transcriber import TranscriptionError, transcribe


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def _info(**kw):
    d = dict(language="es", language_probability=0.98, duration=30.0, duration_after_vad=28.5)
    d.update(kw)
    return SimpleNamespace(**d)


def _setup(monkeypatch, tmp_path, segments, info, config=None,
           clock=(10.0, 12.25), construct_error=None, transcribe_error=None):
    events = []
    src = tmp_path / "audio.m4a"
    src.write_bytes(b"original-source-bytes")
    normalized = tmp_path / "out" / "audio.16k-mono.wav"

    monkeypatch.setattr("transcriptor.transcriber.validate_audio_input",
                        lambda p: events.append("validate") or Path(p))
    monkeypatch.setattr("transcriptor.transcriber.probe_duration",
                        lambda p: events.append("probe") or 25.0)
    monkeypatch.setattr("transcriptor.transcriber.normalize_audio",
                        lambda p, output_dir=None: events.append("normalize") or normalized)

    created = {}

    def fake_model(*args, **kwargs):
        created["args"], created["kwargs"] = args, kwargs
        if construct_error:
            raise construct_error
        model = SimpleNamespace(transcribe_kwargs=None)

        def transcribe(path, **kw):
            model.transcribe_kwargs = kw
            if transcribe_error:
                raise transcribe_error
            return (iter(segments), info)

        model.transcribe = transcribe
        created["model"] = model
        return model

    monkeypatch.setattr("transcriptor.transcriber.WhisperModel", fake_model)
    ticks = iter(clock)
    monkeypatch.setattr("transcriptor.transcriber.perf_counter", lambda: next(ticks))
    return src, created, events


def test_config_defaults():
    c = TranscriptionConfig()
    assert (c.model, c.language, c.device, c.compute_type) == ("medium", "es", "cpu", "int8")
    assert c.vad_filter is True and c.beam_size == 5
    assert c.output_dir == Path("output") and c.download_root is None
    assert c.local_files_only is False


def test_overrides_forwarded(tmp_path, monkeypatch):
    cfg = TranscriptionConfig(model="tiny", language="en", device="cuda",
                              compute_type="float16", vad_filter=False, beam_size=10,
                              download_root=Path("/tmp/models"), local_files_only=True)
    src, created, _ = _setup(monkeypatch, tmp_path, [_seg(0.0, 1.5, "hola")], _info(), cfg)
    transcribe(src, config=cfg)
    assert created["args"] == ("tiny",)
    assert created["kwargs"] == dict(device="cuda", compute_type="float16",
                                     download_root="/tmp/models", local_files_only=True)
    tk = created["model"].transcribe_kwargs
    assert (tk["language"], tk["task"], tk["beam_size"], tk["vad_filter"]) == ("en", "transcribe", 10, False)


def test_default_download_root_none(tmp_path, monkeypatch):
    src, created, _ = _setup(monkeypatch, tmp_path, [], _info())
    transcribe(src)
    assert created["kwargs"]["download_root"] is None
    assert created["kwargs"]["local_files_only"] is False


def test_gate_order(tmp_path, monkeypatch):
    src, created, events = _setup(monkeypatch, tmp_path, [_seg(0.0, 1.0, "hola")], _info())
    transcribe(src)
    assert events == ["validate", "probe", "normalize"]
    assert "model" in created


@pytest.mark.parametrize("which", ["validate", "probe", "normalize"])
def test_audio_failure_propagates(tmp_path, monkeypatch, which):
    src = tmp_path / "audio.m4a"
    src.write_bytes(b"x")

    def fail(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("transcriptor.transcriber.validate_audio_input",
                        fail if which == "validate" else (lambda p: Path(p)))
    monkeypatch.setattr("transcriptor.transcriber.probe_duration",
                        fail if which == "probe" else (lambda p: 1.0))
    monkeypatch.setattr("transcriptor.transcriber.normalize_audio",
                        fail if which == "normalize" else (lambda p, output_dir=None: Path("x.wav")))
    called = []
    monkeypatch.setattr("transcriptor.transcriber.WhisperModel", lambda *a, **k: called.append(1))

    with pytest.raises(RuntimeError):
        transcribe(src)
    assert called == []


def test_missing_dependency(tmp_path, monkeypatch):
    src, _, _ = _setup(monkeypatch, tmp_path, [], _info())
    monkeypatch.setattr("transcriptor.transcriber.WhisperModel", None)
    with pytest.raises(TranscriptionError, match="not installed"):
        transcribe(src)


def test_construction_failure_maps(tmp_path, monkeypatch):
    cause = RuntimeError("no such model")
    src, _, _ = _setup(monkeypatch, tmp_path, [], _info(), construct_error=cause)
    with pytest.raises(TranscriptionError) as ei:
        transcribe(src)
    assert ei.value.__cause__ is cause


def test_transcribe_call_failure_maps(tmp_path, monkeypatch):
    cause = RuntimeError("inference exploded")
    src, _, _ = _setup(monkeypatch, tmp_path, [], _info(), transcribe_error=cause)
    with pytest.raises(TranscriptionError) as ei:
        transcribe(src)
    assert ei.value.__cause__ is cause


def test_consumption_failure_maps(tmp_path, monkeypatch):
    def boom():
        yield _seg(0.0, 1.0, "uno")
        raise RuntimeError("stream broke")

    src, _, _ = _setup(monkeypatch, tmp_path, boom(), _info())
    with pytest.raises(TranscriptionError) as ei:
        transcribe(src)
    assert "stream broke" in str(ei.value.__cause__)


def test_offline_cache_miss(tmp_path, monkeypatch):
    cause = RuntimeError("no cached model and download disabled")
    cfg = TranscriptionConfig(download_root=Path("/cache/models"), local_files_only=True)
    src, created, _ = _setup(monkeypatch, tmp_path, [], _info(), cfg, construct_error=cause)
    with pytest.raises(TranscriptionError) as ei:
        transcribe(src, config=cfg)
    assert created["kwargs"]["local_files_only"] is True
    assert created["kwargs"]["download_root"] == "/cache/models"
    assert ei.value.__cause__ is cause


def test_segments_materialized_floats(tmp_path, monkeypatch):
    segs = [_seg(1, 2, "uno"), _seg(2.5, 4.75, "dos")]
    src, _, _ = _setup(monkeypatch, tmp_path, segs, _info())
    result = transcribe(src)
    assert isinstance(result["segments"], list)
    assert result["segments"] == [{"start": 1.0, "end": 2.0, "text": "uno"},
                                  {"start": 2.5, "end": 4.75, "text": "dos"}]
    assert all(isinstance(s["start"], float) and isinstance(s["end"], float)
               for s in result["segments"])


def test_strip_only(tmp_path, monkeypatch):
    src, _, _ = _setup(monkeypatch, tmp_path, [_seg(0.0, 1.0, "  hola   mundo\totra\n  ")], _info())
    assert transcribe(src)["segments"][0]["text"] == "hola   mundo\totra"


def test_empty_output(tmp_path, monkeypatch):
    src, _, _ = _setup(monkeypatch, tmp_path, [], _info())
    result = transcribe(src)
    assert result["segments"] == []
    assert result["metrics"]["segments_count"] == 0
    assert result["duration"] == 30.0


def test_metrics_and_source_immutability(tmp_path, monkeypatch):
    segs = [_seg(0.0, 1.0, "a"), _seg(1.0, 2.0, "b")]
    src, _, _ = _setup(monkeypatch, tmp_path, segs, _info(language_probability=0.99))
    result = transcribe(src)
    m = result["metrics"]
    assert m["audio_duration"] == 25.0
    assert m["processing_time_s"] == pytest.approx(2.25)
    assert (m["model"], m["device"], m["compute_type"]) == ("medium", "cpu", "int8")
    assert m["segments_count"] == 2
    assert m["language_detected"] == "es"
    assert m["language_probability"] == pytest.approx(0.99)
    assert m["vad_filter"] is True
    assert m["duration_after_vad"] == pytest.approx(28.5)
    assert result["language"] == "es"
    assert result["duration"] == pytest.approx(30.0)
    assert src.read_bytes() == b"original-source-bytes"


def test_duration_after_vad_absent(tmp_path, monkeypatch):
    info = _info()
    del info.duration_after_vad
    src, _, _ = _setup(monkeypatch, tmp_path, [_seg(0.0, 1.0, "x")], info)
    assert transcribe(src)["metrics"]["duration_after_vad"] is None


# --- optional real cached-tiny integration ---


def _tiny_cache_present():
    """True only when the complete Systran tiny snapshot is cached (no network)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return False
    snapshots = Path(HF_HUB_CACHE) / "models--Systran--faster-whisper-tiny" / "snapshots"
    if not snapshots.is_dir():
        return False
    required = ("config.json", "model.bin", "tokenizer.json")
    vocabulary = ("vocabulary.json", "vocabulary.txt")
    return any(
        s.is_dir()
        and all((s / f).is_file() for f in required)
        and any((s / f).is_file() for f in vocabulary)
        for s in snapshots.iterdir()
    )


def _make_wav(path, seconds=1.0, rate=16000):
    """Write a deterministic mono 16 kHz 16-bit PCM WAV; return the Path."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds) * 2)
    return Path(path)


_HAS_FASTER_WHISPER = importlib.util.find_spec("faster_whisper") is not None
_TINY_CACHED = _tiny_cache_present()


@pytest.mark.skipif(not _HAS_FASTER_WHISPER or not _TINY_CACHED,
                    reason="faster-whisper unavailable or Systran tiny model not cached")
def test_transcribe_tiny_cached_model(tmp_path):
    src = _make_wav(tmp_path / "tiny.wav")
    before = src.read_bytes()
    result = transcribe(src, TranscriptionConfig(
        model="tiny", language="es", device="cpu", compute_type="int8",
        local_files_only=True, output_dir=tmp_path / "output"))
    assert src.read_bytes() == before

    segments = result["segments"]
    assert isinstance(segments, list)
    for seg in segments:
        assert isinstance(seg, dict) and isinstance(seg["text"], str)
        assert isinstance(seg["start"], float) and isinstance(seg["end"], float)
        assert 0.0 <= seg["start"] <= seg["end"]

    metrics = result["metrics"]
    assert metrics["segments_count"] == len(segments) >= 0
    assert isinstance(result["language"], str)
    assert math.isfinite(result["duration"]) and result["duration"] >= 0.0
    assert math.isfinite(metrics["processing_time_s"]) and metrics["processing_time_s"] >= 0.0
