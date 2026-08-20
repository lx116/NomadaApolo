"""Thin synchronous composition of the chunking pipeline stages (no stage logic)."""

import json
import logging
from time import perf_counter
from pathlib import Path

from transcriptor.aggregation import aggregate
from transcriptor.chunk_transcriber import ChunkTranscriber, config_fingerprint
from transcriptor.chunker import chunk_audio, source_fingerprint
from transcriptor.exporters import export_aggregate
from transcriptor.preprocess import preprocess_chunk
from transcriptor.state import JobState

logger = logging.getLogger("transcriptor.pipeline")


def run(source, tmp_root, job_id, *, output_dir, model="medium", language="es",
        device="cpu", compute_type="int8", vad_filter=True, beam_size=5,
        chunk_seconds=300.0, overlap=1.0, vad_enabled=False, denoise_enabled=False,
        transcriber_factory=None, on_chunk_completed=None):
    """Compose chunking → preprocessing → transcription → aggregation → export.

    Delegates every stage; holds no stage logic. ``transcriber_factory`` injects
    a model-lifetime owner for tests/harnesses that must not load real weights.
    """
    logger.info("pipeline start: job=%s source=%s", job_id, source)
    manifest_path = chunk_audio(source, tmp_root, job_id,
                                chunk_seconds=chunk_seconds, overlap=overlap)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    workspace = manifest_path.parent

    fingerprint = config_fingerprint(
        model=model, language=language, device=device, compute_type=compute_type,
        vad_filter=vad_filter, beam_size=beam_size)
    state = JobState(workspace, job_id=job_id, source_id=manifest["source_id"],
                     config_fingerprint=fingerprint)
    state.transition("chunking")
    state.transition("preprocessing")

    factory = transcriber_factory or (
        lambda: ChunkTranscriber(job_id, manifest["source_id"], model=model,
                                 language=language, device=device,
                                 compute_type=compute_type, vad_filter=vad_filter,
                                 beam_size=beam_size))
    transcriber = factory()

    preprocessed_dir = workspace / "preprocessed"
    results = []
    state.transition("transcribing")
    for c in manifest["chunks"]:
        if state.cancel_requested:
            state.transition("cancelled")
            break
        chunk_index = c["chunk_index"]
        chunk_started = perf_counter()
        state.mark_chunk_started(chunk_index)
        raw = workspace / c["path"] if c.get("path") else source
        pre = preprocess_chunk(raw, preprocessed_dir, chunk_index,
                               source_start=c["source_start"], source_end=c["source_end"],
                               vad_enabled=vad_enabled, denoise_enabled=denoise_enabled)
        res = transcriber.transcribe_chunk(
            pre["output_audio"], chunk_index=chunk_index,
            source_start=c["source_start"], source_end=c["source_end"])
        state.mark_chunk_completed(chunk_index, source_fingerprint(pre["output_audio"]),
                                   perf_counter() - chunk_started)
        results.append(res)
        if on_chunk_completed:
            on_chunk_completed(res, perf_counter() - chunk_started)

    if state.state == "cancelled":
        leftovers = state.cleanup()
        logger.info("pipeline cancelled: job=%s", job_id)
        return {"cancelled": True, "leftovers": leftovers}

    state.transition("aggregating")
    agg = aggregate(results, [c["chunk_index"] for c in manifest["chunks"]],
                    job_id=job_id, source_id=manifest["source_id"],
                    source_name=manifest["source_name"],
                    duration=manifest["source_duration"], language=language)
    transcription_dir = Path(output_dir) / "transcription"
    json_path, txt_path = export_aggregate(agg, transcription_dir,
                                           json_name=f"{job_id}.json",
                                           txt_name=f"{job_id}.txt")
    state.transition("completed")
    leftovers = state.cleanup()
    logger.info("pipeline complete: job=%s json=%s txt=%s", job_id, json_path, txt_path)
    return {"json": json_path, "txt": txt_path, "aggregate": agg, "leftovers": leftovers}
