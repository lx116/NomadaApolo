"""Contract tests for transcriptor.chunk_transcriber (AC-007, AC-008, AC-011, AC-012)."""

from types import SimpleNamespace

import pytest

from transcriptor.chunk_transcriber import (
    ChunkTranscriber,
    TranscriptionError,
    config_fingerprint,
)


def _seg(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


def _info(**kw):
    d = dict(language="es", language_probability=0.98, duration_after_vad=28.5)
    d.update(kw)
    return SimpleNamespace(**d)


def _install_model(monkeypatch, on_transcribe, on_construct=None):
    """Install a fake WhisperModel; return a state dict tracking calls."""
    state = {"constructions": 0, "calls": []}

    class FakeModel:
        def __init__(self, *args, **kwargs):
            state["constructions"] += 1
            state["kwargs"] = kwargs
            if on_construct:
                on_construct(state)

        def transcribe(self, path, **kw):
            state["calls"].append(path)
            return on_transcribe(state, path, kw)

    monkeypatch.setattr("transcriptor.chunk_transcriber.WhisperModel", FakeModel)
    return state


def test_model_constructed_once_across_chunks(tmp_path, monkeypatch):
    state = _install_model(
        monkeypatch,
        lambda st, path, kw: (iter([_seg(0.0, 1.0, "uno")]), _info()),
    )
    t = ChunkTranscriber("job-1", "sha256:abc", model="tiny")
    c1, c2 = tmp_path / "000000.wav", tmp_path / "000001.wav"
    t.transcribe_chunk(c1, chunk_index=0, source_start=0.0, source_end=300.0)
    t.transcribe_chunk(c2, chunk_index=1, source_start=300.0, source_end=600.0)
    assert state["constructions"] == 1
    assert state["calls"] == [str(c1), str(c2)]


def test_offsets_are_chunk_start_plus_local(tmp_path, monkeypatch):
    _install_model(
        monkeypatch,
        lambda st, path, kw: (
            iter([_seg(1.5, 4.75, "a"), _seg(5.0, 9.0, "b")]), _info()),
    )
    t = ChunkTranscriber("job-2", "sha256:abc")
    res = t.transcribe_chunk(
        tmp_path / "c.wav", chunk_index=2, source_start=300.0, source_end=600.0)
    assert res["source_start"] == 300.0 and res["source_end"] == 600.0
    seg0, seg1 = res["segments"]
    assert seg0["start"] == pytest.approx(301.5)
    assert seg0["end"] == pytest.approx(304.75)
    assert seg0["local_start"] == pytest.approx(1.5)
    assert seg1["start"] == pytest.approx(305.0)
    assert seg1["end"] == pytest.approx(309.0)
    assert [s["segment_id"] for s in res["segments"]] == [
        "job-2:chunk-000002:segment-000000",
        "job-2:chunk-000002:segment-000001",
    ]


def test_literal_text_preserved(tmp_path, monkeypatch):
    text = "HOLA   hola   HOLA... ¿qué pasó?"
    _install_model(
        monkeypatch,
        lambda st, path, kw: (iter([_seg(0.0, 1.0, f"  {text}  ")]), _info()),
    )
    t = ChunkTranscriber("job-3", "sha256:abc")
    res = t.transcribe_chunk(
        tmp_path / "c.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    # internal spaces, repetition, capitalization, and punctuation preserved literally
    assert res["segments"][0]["text"] == text


def test_only_failing_chunk_retried(tmp_path, monkeypatch):
    def on_transcribe(st, path, kw):
        attempts = st["calls"].count(path)
        if "000000.wav" in path and attempts == 1:
            raise RuntimeError("transient")
        return iter([_seg(0.0, 1.0, "ok")]), _info()

    state = _install_model(monkeypatch, on_transcribe)
    t = ChunkTranscriber("job-4", "sha256:abc", max_retries=2)
    r0 = t.transcribe_chunk(
        tmp_path / "000000.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    r1 = t.transcribe_chunk(
        tmp_path / "000001.wav", chunk_index=1, source_start=300.0, source_end=600.0)
    assert state["calls"].count(str(tmp_path / "000000.wav")) == 2  # retried once
    assert state["calls"].count(str(tmp_path / "000001.wav")) == 1  # never retried
    assert len(r0["segments"]) == 1 and len(r1["segments"]) == 1


def test_retry_exhaustion_raises_diagnostic(tmp_path, monkeypatch):
    _install_model(
        monkeypatch,
        lambda st, path, kw: (_ for _ in ()).throw(RuntimeError("always fails")),
    )
    t = ChunkTranscriber("job-5", "sha256:abc", max_retries=1)
    with pytest.raises(TranscriptionError) as ei:
        t.transcribe_chunk(
            tmp_path / "c.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    assert "chunk 0" in str(ei.value)


def test_compatible_reuse_skips_reprocessing_no_duplicates(tmp_path, monkeypatch):
    state = _install_model(
        monkeypatch,
        lambda st, path, kw: (
            iter([_seg(0.0, 1.0, "uno"), _seg(1.0, 2.0, "dos")]), _info()),
    )
    t = ChunkTranscriber("job-6", "sha256:abc")
    first = t.transcribe_chunk(
        tmp_path / "c.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    second = t.transcribe_chunk(
        tmp_path / "c.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    assert len(state["calls"]) == 1  # not reprocessed on compatible resume
    assert second is first
    ids = [s["segment_id"] for s in first["segments"]]
    assert len(ids) == len(set(ids))  # no duplicate segment IDs


def test_model_construction_failure_not_retried(tmp_path, monkeypatch):
    def on_construct(st):
        raise RuntimeError("no cached model and download disabled")

    _install_model(monkeypatch, None, on_construct)
    t = ChunkTranscriber("job-7", "sha256:abc", max_retries=5)
    with pytest.raises(TranscriptionError) as ei:
        t.transcribe_chunk(
            tmp_path / "c.wav", chunk_index=0, source_start=0.0, source_end=300.0)
    assert ei.value.__cause__ is not None


def test_config_fingerprint_deterministic_and_sensitive():
    kwargs = dict(model="tiny", language="es", device="cpu",
                  compute_type="int8", vad_filter=True, beam_size=5)
    a = config_fingerprint(**kwargs)
    b = config_fingerprint(**kwargs)
    c = config_fingerprint(**{**kwargs, "model": "medium"})
    assert a == b and a != c and a.startswith("sha256:")
