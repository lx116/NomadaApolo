# Proposal: Synchronous Audio Chunking Pipeline

## Intent

Implement the synchronous pipeline from `specs/audio-chunck/01..05` plus `07` E2E acceptance. Long-file transcription becomes bounded, resumable, and traceable while preserving the original and literal model output. Preserve AC-001..AC-013 and AC-015; defer Celery under AC-014.

## Scope

### In Scope
- Implement stages 01-05: chunking, preprocessing, per-chunk transcription, deterministic aggregation/export, and local resume/cancellation.
- Add contract, integration, cross-stage, resume, and cleanup tests.
- Add gated E2E 07 for external `Yurbaco.m4a`, prerequisites, invariants, metrics, and JSON/TXT outputs.
- Deliver in chained slices under 400 lines: A (01-02), B (03), C (04-05), D (07).

### Out of Scope
- Celery/Redis stage 06 and AC-014 implementation.
- Django, API, database, authentication, Flutter, diarization, summarization, or redaction.
- Copying `Yurbaco.m4a` or committing temporary/intermediate artifacts.

## Capabilities

### New Capabilities
- `audio-chunking`: Deterministic isolated chunks, manifests, offsets, and source immutability (AC-001..AC-005).
- `audio-preprocessing`: Mono/16 kHz/16-bit conversion with separate VAD and denoising (AC-006..AC-007).
- `chunk-transcription`: One model lifecycle, offsets, literal text, metrics, retries, and reuse (AC-008, AC-011..AC-012).
- `transcription-aggregation`: Deterministic overlap reconciliation and TXT/JSON exports (AC-009..AC-011).
- `audio-job-resume`: Atomic checkpoints, transitions, cancellation, and cleanup (AC-005, AC-012..AC-013).
- `yurbaco-e2e-acceptance`: Gated end-to-end acceptance and invariant evidence (AC-015).

### Modified Capabilities
- None.

## Approach

Reuse `transcriptor/audio.py` validation, FFmpeg safety, WAV verification, staged writes, and errors. Add minimum stage modules under `transcriptor/`; keep Django untouched. Load `WhisperModel` once per job, use deterministic manifests/checkpoints, and stage work under `<tmp_root>/<job_id>/`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `transcriptor/` | Modified/New | Add stages, contracts, exports, state, and orchestration. |
| `tests/` | New/Modified | Stage, contract, resume, cleanup, and E2E coverage. |
| `openspec/changes/audio-chunking-sync/` | New | Proposal and subsequent SDD artifacts. |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Model reloads per chunk or memory grows | High | One lifecycle wrapper per job and targeted tests. |
| Overlap reconciliation loses text | Med | Deduplicate only on strong evidence; keep ambiguity. |
| Repo-local Yurbaco/output masks invariants | Med | Require external source and isolated temporary workspace. |
| Review overload | High | Four chained slices under 400 changed lines. |

## Rollback Plan

Revert slices in reverse order. Existing Phase-1 modules remain usable; remove new stages/tests and unreferenced exports. The pipeline does not mutate source audio.

## Dependencies

- Python/pytest, local FFmpeg/ffprobe, faster-whisper weights, and external `Yurbaco.m4a` for gated E2E.

## Success Criteria

- [ ] AC-001..AC-013 and AC-015 have passing, traceable tests; AC-014 remains deferred.
- [ ] Sync pipeline produces coherent deterministic JSON/TXT, supports compatible resume/cancel, and preserves the source hash.
- [ ] E2E 07 passes all invariants or reports a classified prerequisite block without false acceptance.
