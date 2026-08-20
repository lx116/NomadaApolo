"""One WhisperModel per job: literal per-chunk transcription with absolute offsets (AC-007, AC-008, AC-011, AC-012)."""

import hashlib
import json
import logging
from time import perf_counter

from transcriptor.transcriber import TranscriptionError, _build_segments

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - exercised by tests via monkeypatch
    WhisperModel = None

logger = logging.getLogger("transcriptor.chunk_transcriber")

TRANSCRIPTION_CONTRACT = "audio-transcription/v1"
CONFIG_VERSION = 1
DEFAULT_MAX_RETRIES = 2


def config_fingerprint(*, model, language, device, compute_type, vad_filter, beam_size):
    """Canonical SHA-256 fingerprint of output-affecting settings and schema version."""
    payload = {
        "contract": TRANSCRIPTION_CONTRACT,
        "config_version": CONFIG_VERSION,
        "model": model,
        "language": language,
        "device": device,
        "compute_type": compute_type,
        "vad_filter": vad_filter,
        "beam_size": beam_size,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ChunkTranscriber:
    """Owns a single ``WhisperModel`` for a whole job.

    The model is constructed lazily and at most once, so all compatible chunks
    share one lifecycle. Retry is bounded and scoped to the failing chunk only;
    model-construction failures are definitive and never retried. A completed
    chunk is reused verbatim (same source and configuration) instead of being
    reprocessed, so no duplicate segment IDs are produced.
    """

    def __init__(self, job_id, source_id, *, model="medium", language="es",
                 device="cpu", compute_type="int8", vad_filter=True, beam_size=5,
                 download_root=None, local_files_only=False,
                 max_retries=DEFAULT_MAX_RETRIES):
        self.job_id = job_id
        self.source_id = source_id
        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self.beam_size = beam_size
        self.download_root = download_root
        self.local_files_only = local_files_only
        self.max_retries = max_retries
        self.fingerprint = config_fingerprint(
            model=model, language=language, device=device, compute_type=compute_type,
            vad_filter=vad_filter, beam_size=beam_size)
        self._model = None
        self._results = {}

    @property
    def model(self):
        """The job-scoped model instance; constructed at most once."""
        if self._model is None:
            if WhisperModel is None:
                raise TranscriptionError(
                    "faster-whisper not installed; install the runtime dependency to transcribe")
            try:
                self._model = WhisperModel(
                    self.model_name, device=self.device, compute_type=self.compute_type,
                    download_root=str(self.download_root) if self.download_root else None,
                    local_files_only=self.local_files_only)
            except TranscriptionError:
                raise
            except Exception as e:
                raise TranscriptionError(f"model construction failed: {e}") from e
            logger.info("chunk-transcription model-loaded: job=%s model=%s device=%s",
                        self.job_id, self.model_name, self.device)
        return self._model

    def transcribe_chunk(self, audio_path, *, chunk_index, source_start, source_end):
        """Transcribe one preprocessed chunk; reuse a completed chunk verbatim."""
        cached = self._results.get(chunk_index)
        if cached is not None:
            logger.info("chunk-transcription reuse: job=%s chunk=%s", self.job_id, chunk_index)
            return cached
        logger.info("chunk-transcription start: job=%s chunk=%s", self.job_id, chunk_index)
        model = self.model  # construction failure is definitive; never retried
        attempt = 0
        while True:
            try:
                result = self._run_inference(
                    model, audio_path, chunk_index, source_start, source_end)
            except TranscriptionError as e:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error("chunk-transcription failure: job=%s chunk=%s error=%s",
                                 self.job_id, chunk_index, e)
                    raise
                logger.warning("chunk-transcription retry: job=%s chunk=%s attempt=%s error=%s",
                               self.job_id, chunk_index, attempt, e)
                continue
            self._results[chunk_index] = result
            logger.info("chunk-transcription completion: job=%s chunk=%s segments=%s",
                        self.job_id, chunk_index, len(result["segments"]))
            return result

    def _run_inference(self, model, audio_path, chunk_index, source_start, source_end):
        t0 = perf_counter()
        try:
            segments_iter, info = model.transcribe(
                str(audio_path), language=self.language, task="transcribe",
                beam_size=self.beam_size, vad_filter=self.vad_filter)
            local_segments = _build_segments(segments_iter)
            processing_time_s = max(0.0, perf_counter() - t0)
        except TranscriptionError:
            raise
        except Exception as e:
            raise TranscriptionError(f"chunk {chunk_index}: transcription failed: {e}") from e

        segments = [
            {
                "segment_id": f"{self.job_id}:chunk-{chunk_index:06d}:segment-{i:06d}",
                "chunk_index": chunk_index,
                "start": round(float(source_start) + float(s["start"]), 6),
                "end": round(float(source_start) + float(s["end"]), 6),
                "local_start": round(float(s["start"]), 6),
                "local_end": round(float(s["end"]), 6),
                "text": s["text"],
            }
            for i, s in enumerate(local_segments)
        ]

        return {
            "contract_version": TRANSCRIPTION_CONTRACT,
            "job_id": self.job_id,
            "source_id": self.source_id,
            "config_fingerprint": self.fingerprint,
            "chunk_index": chunk_index,
            "source_start": float(source_start),
            "source_end": float(source_end),
            "segments": segments,
            "metrics": {
                "model": self.model_name,
                "device": self.device,
                "compute_type": self.compute_type,
                "processing_time_s": processing_time_s,
                "segments_count": len(segments),
                "language_detected": info.language,
                "language_probability": info.language_probability,
                "vad_filter": self.vad_filter,
                "duration_after_vad": getattr(info, "duration_after_vad", None),
            },
        }
