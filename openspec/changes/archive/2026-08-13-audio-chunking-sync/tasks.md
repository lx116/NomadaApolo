# Tasks: Synchronous Audio Chunking Pipeline

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1100–1400 across 4 slices |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (A) → PR 2 (B) → PR 3 (C) → PR 4 (D) |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High

Note: `auto-chain` resolves slicing, but `feature-branch-chain` needs tracker-branch name/base confirmation before apply mutates git — hence `Decision needed before apply: Yes`.

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| A | chunking + preprocessing | PR 1 (base: `feature/audio-chunking-sync`) | `.venv/bin/pytest tests/test_chunker.py tests/test_preprocess.py` | Run chunker+preprocess over synthetic WAV in tmp workspace with real ffmpeg; assert chunks + preprocessed WAVs exist, source unchanged | delete `transcriptor/chunker.py`, `transcriptor/preprocess.py`, `tests/test_chunker.py`, `tests/test_preprocess.py` |
| B | model-lifecycle transcription | PR 2 (base: PR 1 branch) | `.venv/bin/pytest tests/test_chunk_transcriber.py` | N/A — real path needs cached `tiny` weights; gated shape-only test | delete `transcriptor/chunk_transcriber.py`, `tests/test_chunk_transcriber.py` |
| C | aggregation/export/state/resume | PR 3 (base: PR 2 branch) | `.venv/bin/pytest tests/test_aggregation.py tests/test_exporters.py tests/test_state.py` | Run `pipeline.run` over synthetic WAV in tmp; assert JSON+TXT agree and workspace cleans | delete `transcriptor/aggregation.py`, `exporters.py`, `state.py`, `pipeline.py` + 3 test files |
| D | gated Yurbaco E2E | PR 4 (base: PR 3 branch) | `.venv/bin/pytest tests/test_yurbaco_e2e.py` | `YURBACO_AUDIO_PATH=<external path> .venv/bin/pytest tests/test_yurbaco_e2e.py` | delete `tests/test_yurbaco_e2e.py` only |

## Phase 1 — Slice A: Chunking + Preprocessing

- [x] 1.1 Create `transcriptor/chunker.py`: `validate_audio_input` + `probe_duration`, SHA-256 `source_id`, reject preexisting `<tmp_root>/<job_id>/` workspace, 300s windows with 1–2s overlap, extract `chunks/<index:06d>.<ext>` via `mkstemp` + `os.replace`, emit `manifest.json` (`audio-chunk/v1`) before transcription; skip physical chunking when duration < 300. AC-001..AC-005.
- [x] 1.2 Create `transcriptor/preprocess.py`: per-chunk ffmpeg → `preprocessed/<index:06d>.wav` (mono/16kHz/16-bit), reuse `_verify_wav`, separate recorded VAD + denoising flags (denoise default off), record metadata, clean partial output. AC-005..AC-007.
- [x] 1.3 RED `tests/test_chunker.py`: metacharacter path stays one argv item + `shell=False`; workspace collision fails; 299.9 vs 300.0 boundary; source bytes unchanged; interrupted write leaves no accepted partial. AC-001..AC-005.
- [x] 1.4 RED `tests/test_preprocess.py`: argv/flags; mono/16k/16-bit verify; FFmpeg failure reports chunk + stderr and removes partial; VAD vs denoise metadata distinct; ambiguous content kept. AC-005..AC-007.

## Phase 2 — Slice B: Model-lifecycle Transcription

- [x] 2.1 Create `transcriptor/chunk_transcriber.py`: `ChunkTranscriber` loads `WhisperModel` once per job; `transcribe_chunk()` returns literal text, absolute `start`/`end` = `source_start` + local, `source_start`/`source_end`, chunk index, stable ID, metrics; bounded per-chunk retry; `config_fingerprint`. Reuse `_build_segments` + `TranscriptionError`; never call `transcribe()` per chunk. AC-007, AC-008, AC-011, AC-012.
- [x] 2.2 RED `tests/test_chunk_transcriber.py`: model constructed once across two chunks; offsets = chunk start + local; literal text preserved (spaces/repeats/caps); only failing chunk retried; compatible resume skips reprocessing with no duplicate IDs.

## Phase 3 — Slice C: Aggregation + Export + State + Pipeline

- [x] 3.1 Create `transcriptor/aggregation.py`: reject incomplete/invalid results, sort by `(start, end, chunk_index, segment_id)`, dedup only identical overlap text (keep-on-doubt). AC-009..AC-011.
- [x] 3.2 Create `transcriptor/exporters.py`: stage + promote JSON (`audio-transcription/v1`) + TXT `[HH:MM:SS - HH:MM:SS]` from one list; announce only after both promote; pair-failure removes promoted sibling. AC-009..AC-011.
- [x] 3.3 Create `transcriptor/state.py`: `created→chunking→preprocessing→transcribing→aggregating→completed` + `failed`/`cancelled`; atomic checkpoint (sibling + `os.replace`); fingerprint-guarded reuse; cancellation; idempotent cleanup preserving source/finals. AC-005, AC-012, AC-013.
- [x] 3.4 Create `transcriptor/pipeline.py`: thin synchronous composition only (no stage logic).
- [x] 3.5 RED `tests/test_aggregation.py`, `tests/test_exporters.py`, `tests/test_state.py`: identical-overlap dedup; partial disagreement preserved; missing chunk blocks export; atomic pair publication; invalid transition rejected; incompatible resume; cleanup error leaves source untouched.

## Phase 4 — Slice D: Gated Yurbaco E2E

- [x] 4.1 Create `tests/test_yurbaco_e2e.py`: require `YURBACO_AUDIO_PATH` (out-of-repo), ffmpeg/ffprobe, cached tiny weights, capacity; run stages 01–05 in order; assert before/after source hash, JSON/TXT sequence agreement, chunk/audio/state/ordering/provenance/cleanup invariants; deterministic skip (never false pass) when prerequisites missing; never commit intermediates. AC-015.
- [x] 4.2 RED invariant scenarios: missing chunk, changed source hash, incoherent export, surviving workspace → classified contract failure.

## Dependencies

- B → A (manifest + preprocessed chunks). C → B (per-chunk results) + A. D → A+B+C.
- Chunking settings (`chunk_seconds=300`, overlap 1–2s, `job_id`, workspace root) are stage params, not `config.py` edits (no config-for-constants).
- Phase-1 APIs (`audio.py`, `transcriber.py`) unchanged. `exporters.py`/`state.py` are new; no Django/DB/queue/dependency added.
