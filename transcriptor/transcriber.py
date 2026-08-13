"""Local faster-whisper transcription core over the unchanged audio boundary."""

from pathlib import Path
from time import perf_counter
from typing import TypedDict

from transcriptor.audio import normalize_audio, probe_duration, validate_audio_input

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - exercised by tests via monkeypatch
    WhisperModel = None


class TranscriptionError(Exception):
    """Raised when faster-whisper is unavailable or transcription fails."""


class Segment(TypedDict):
    start: float
    end: float
    text: str


class TranscriptionMetrics(TypedDict):
    audio_duration: float
    processing_time_s: float
    model: str
    device: str
    compute_type: str
    segments_count: int
    language_detected: str
    language_probability: float
    vad_filter: bool
    duration_after_vad: float | None


class TranscriptionResult(TypedDict):
    language: str
    duration: float
    segments: list[Segment]
    metrics: TranscriptionMetrics


def _build_segments(segments_iter):
    """Materialize the generator into a list of normalized Segment dicts."""
    return [
        {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
        for s in segments_iter
    ]


def transcribe(path: str | Path, config=None) -> TranscriptionResult:
    """Validate, probe, normalize, then transcribe and return a typed result.

    Audio-domain failures (validation, probing, normalization) propagate
    unchanged and prevent model loading. Model construction, transcription, and
    generator-consumption failures become ``TranscriptionError`` with the
    original cause chained. The source path is never modified.
    """
    from transcriptor.config import TranscriptionConfig

    cfg = config or TranscriptionConfig()

    # Audio gates first: reuse the existing boundary unchanged.
    validate_audio_input(path)
    audio_duration = probe_duration(path)
    normalized = normalize_audio(path, output_dir=cfg.output_dir)

    if WhisperModel is None:
        raise TranscriptionError(
            "faster-whisper not installed; install the runtime dependency to transcribe"
        )

    try:
        model = WhisperModel(
            cfg.model,
            device=cfg.device,
            compute_type=cfg.compute_type,
            download_root=str(cfg.download_root) if cfg.download_root else None,
            local_files_only=cfg.local_files_only,
        )

        t0 = perf_counter()
        segments_iter, info = model.transcribe(
            str(normalized),
            language=cfg.language,
            task="transcribe",
            beam_size=cfg.beam_size,
            vad_filter=cfg.vad_filter,
        )
        segments = _build_segments(segments_iter)
        processing_time_s = max(0.0, perf_counter() - t0)
    except TranscriptionError:
        raise
    except Exception as e:
        raise TranscriptionError(f"transcription failed: {e}") from e

    metrics: TranscriptionMetrics = {
        "audio_duration": audio_duration,
        "processing_time_s": processing_time_s,
        "model": cfg.model,
        "device": cfg.device,
        "compute_type": cfg.compute_type,
        "segments_count": len(segments),
        "language_detected": info.language,
        "language_probability": info.language_probability,
        "vad_filter": cfg.vad_filter,
        "duration_after_vad": getattr(info, "duration_after_vad", None),
    }

    return {
        "language": info.language,
        "duration": info.duration,
        "segments": segments,
        "metrics": metrics,
    }
