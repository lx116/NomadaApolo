# Apply Progress — audio-chunking-sync (Slices A + B + C + D)

**Status**: complete (Slices A + B + C + D of 4)
**Mode**: Strict TDD
**Delivery**: feature-branch-chain — child PR #1 targets tracker `feature/audio-chunk`
**Branch**: `feature/audio-chunk` (tracker base confirmed by user)

## Scope Implemented

- Slice A = Phase 1 tasks 1.1–1.4: synchronous chunking + preprocessing and their
  contract/integration tests.
- Slice B = Phase 2 tasks 2.1–2.2: one-model-per-job chunk transcription with literal
  text, absolute offsets, stable IDs, bounded per-chunk retry, config fingerprint, and
  logging, plus mocked contract tests.
- Slice C = Phase 3 tasks 3.1–3.5: deterministic conservative aggregation, atomic
  JSON/TXT export, versioned atomic job state with cancellation/cleanup, and a thin
  synchronous pipeline composition, plus their contract tests.
- Slice D = Phase 4 tasks 4.1–4.2: externally gated Yurbaco E2E acceptance harness
  (`tests/test_yurbaco_e2e.py`) that runs stages 01–05 through `pipeline.run` with
  an offline `tiny` model, validates every chunk/audio/state/ordering/provenance/
  cleanup invariant via a classified evidence validator, and skips deterministically
  on any missing prerequisite. Celery (AC-014) remains out of scope.

## Completed Tasks

- [x] 1.1 `transcriptor/chunker.py` — deterministic windows, SHA-256 `source_id`,
      isolated workspace with repo-ancestry + collision rejection, atomic chunk
      extraction (`mkstemp` + `os.replace`), `manifest.json` (`audio-chunk/v1`)
      emitted before downstream stages; bypass when duration < 300 s.
- [x] 1.2 `transcriptor/preprocess.py` — per-chunk ffmpeg → mono/16 kHz/16-bit WAV,
      reuses `_verify_wav`, distinct VAD vs denoising metadata (denoise off by default),
      partial-output cleanup.
- [x] 1.3 `tests/test_chunker.py` — windows boundary (299.9/300.0/601.0), bypass,
      manifest ordering/paths, workspace collision, repo rejection, interrupted-write
      atomicity, metacharacter argv safety, source immutability, real ffmpeg integration.
- [x] 1.4 `tests/test_preprocess.py` — argv flags, mono/16k/16-bit verification,
      failure reports chunk + stderr and removes partial, VAD/denoise distinct,
      default filters off, missing binary, metacharacter safety, real ffmpeg integration.
- [x] 2.1 `transcriptor/chunk_transcriber.py` — `ChunkTranscriber` lazy-loads one
      `WhisperModel` per job; `transcribe_chunk()` returns `audio-transcription/v1`
      results with literal text, absolute `start`/`end` = `source_start` + local,
      `source_start`/`source_end`, chunk index, stable `segment_id`, metrics; bounded
      per-chunk retry; canonical `config_fingerprint`; `logging` for start/completion/
      failure/reuse. Reuses `_build_segments` + `TranscriptionError`; never calls
      `transcribe()` per chunk.
- [x] 2.2 `tests/test_chunk_transcriber.py` — model constructed once across two chunks;
      offsets = chunk start + local; literal text preserved (spaces/repeats/caps); only
      failing chunk retried; compatible resume skips reprocessing with no duplicate IDs;
      construction failure not retried; fingerprint deterministic + sensitive.
- [x] 3.1 `transcriptor/aggregation.py` — rejects missing/duplicate/unknown chunks and
      invalid timestamps; deterministic sort `(start, end, chunk_index, segment_id)`;
      adjacent-pair reconciliation dedups only identical non-empty overlap text and
      records the decision; partial/empty overlap kept and marked ambiguous; emits
      `audio-transcription/v1` with provenance + chunks/segments-before/after metrics.
- [x] 3.2 `transcriptor/exporters.py` — `format_timestamp` + `render_txt` derive TXT
      `[HH:MM:SS - HH:MM:SS]` from one segment list; `export_aggregate` stages/promotes
      JSON then TXT atomically, writes `export.complete` marker only after both, and
      removes the promoted JSON sibling on TXT failure (no half-pair, no announcement).
- [x] 3.3 `transcriptor/state.py` — `JobState` enforces `created→…→completed` plus
      `failed`/`cancelled` terminals; atomic checkpoint (`mkstemp` sibling + `os.replace`);
      `load_checkpoint` rejects contract/source/config mismatch (no reuse); per-chunk
      completion with artifact hash; `request_cancel`; idempotent `cleanup` that reports
      leftovers and never touches source/finals.
- [x] 3.4 `transcriptor/pipeline.py` — thin synchronous composition of
      chunker → preprocess → ChunkTranscriber → aggregate → export with a `JobState`
      guard, cancellation check between chunks, logging, and injectable
      `transcriber_factory` (no stage logic; no model loading in tests).
- [x] 3.5 `tests/test_aggregation.py`, `tests/test_exporters.py`, `tests/test_state.py` —
      identical-overlap dedup, keep-on-doubt partial/empty overlap, missing chunk blocks,
      deterministic sort, provenance/metrics, invalid timestamp, atomic pair publication,
      pair-failure sibling removal, valid/invalid transitions, compatible + incompatible
      resume, cancellation, cleanup error preserves source, idempotent cleanup.
- [x] 4.1 `tests/test_yurbaco_e2e.py` — module-scoped prerequisite fixture resolving
      `YURBACO_AUDIO_PATH` (must be an out-of-repo file), `ffmpeg`/`ffprobe`, cached
      `tiny` weights (`local_files_only=True` construction), and a volume capacity floor;
      `test_yurbaco_full_pipeline` runs `pipeline.run` (stages 01–05) with an offline
      `tiny` `transcriber_factory`, then asserts source hash unchanged, source identity
      in the aggregate, JSON/TXT coherence, provenance, ordering, completion marker, and
      workspace cleanup via `validate_evidence`; outputs/intermediates never land in the
      repo. Missing prerequisites `pytest.skip` (never false-pass).
- [x] 4.2 `tests/test_yurbaco_e2e.py` — invariant classifier `validate_evidence` plus RED
      scenarios: missing chunk, changed source hash, incoherent export, surviving workspace
      → classified contract violations; clean evidence → zero violations; repo-local
      `Yurbaco.m4a` → `_PrerequisiteSkip` (out-of-repo gate).

## Files Changed

| File | Action | Lines |
|------|--------|-------|
| `transcriptor/chunker.py` | Created | 117 |
| `transcriptor/preprocess.py` | Created | 75 |
| `tests/test_chunker.py` | Created | 105 |
| `tests/test_preprocess.py` | Created | 98 |
| `transcriptor/chunk_transcriber.py` | Created | 162 |
| `tests/test_chunk_transcriber.py` | Created | 156 |
| `transcriptor/aggregation.py` | Created | 83 |
| `transcriptor/exporters.py` | Created | 61 |
| `transcriptor/state.py` | Created | 130 |
| `transcriptor/pipeline.py` | Created | 78 |
| `tests/test_aggregation.py` | Created | 114 |
| `tests/test_exporters.py` | Created | 56 |
| `tests/test_state.py` | Created | 102 |
| `tests/test_yurbaco_e2e.py` | Created | 236 |
| **Total (additions, cumulative)** | | **1573** |

## Test Evidence

### Slice A

- Focused: `.venv/bin/pytest tests/test_chunker.py tests/test_preprocess.py -q` → `10 passed in 0.12s`
- Runtime harness: synthetic 0.6 s WAV → 3 physical chunks + preprocessed WAV `(1, 16000, 2)`, source hash unchanged.

### Slice B

- Focused: `.venv/bin/pytest tests/test_chunk_transcriber.py -q` → `8 passed in 0.24s`
- Full suite: `.venv/bin/pytest -q` → `70 passed in 0.77s` (62 prior + 8 new)
- Runtime harness: `N/A` — real path needs cached `tiny` weights; mocked model is the
  prototype boundary (per tasks.md work-unit B). Logging demonstrated via a bounded demo
  run (start / model-loaded / retry / completion / reuse / failure lines all observed).

### Slice C

- Focused: `.venv/bin/pytest tests/test_aggregation.py tests/test_exporters.py tests/test_state.py -q` → `16 passed in 0.04s`
- Full suite: `.venv/bin/pytest -q` → `86 passed in 0.85s` (70 prior + 16 new)
- Runtime harness: synthetic 31 s WAV + stub transcriber → `pipeline.run` produced
  parseable JSON and matching TXT `[00:00:01 - 00:00:02]`, `export.complete` marker
  present, workspace cleaned (leftovers `[]`), source bytes unchanged.

### Slice D

- Focused: `.venv/bin/pytest tests/test_yurbaco_e2e.py -q` → `6 passed, 1 skipped`
  (skip reason: `YURBACO_AUDIO_PATH is not set` — deterministic prerequisite block).
- Full suite: `.venv/bin/pytest -q` → `92 passed, 1 skipped in 0.75s` (86 prior + 6 new + 1 skip).
- Real E2E: **not executed** — spec requires an out-of-repository source, and the
  only `Yurbaco.m4a` is tracked at the repository root. Prerequisite block:
  `YURBACO_AUDIO_PATH` unset AND repo-local source is rejected by the out-of-repo gate
  (`test_in_repo_source_is_prerequisite_block`). Audio not copied or modified.

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_chunker.py` | Unit+Integration | N/A (new) | ✅ Written | ✅ Passed | ✅ boundary 299.9/300.0/601.0 | ✅ Compacted |
| 1.2 | `tests/test_preprocess.py` | Unit+Integration | N/A (new) | ✅ Written | ✅ Passed | ✅ vad/denoise/failure cases | ✅ Compacted |
| 1.3 | `tests/test_chunker.py` | Unit | N/A (new) | ✅ Written | ✅ Passed | ✅ 6 scenarios | ➖ |
| 1.4 | `tests/test_preprocess.py` | Unit | N/A (new) | ✅ Written | ✅ Passed | ✅ 4 scenarios | ➖ |
| 2.1 | `tests/test_chunk_transcriber.py` | Unit (mocked) | existing 62 green | ✅ Written | ✅ Passed | ✅ one-model/offsets/literal/retry/reuse/fingerprint | ✅ Compacted |
| 2.2 | `tests/test_chunk_transcriber.py` | Unit | existing 62 green | ✅ Written | ✅ Passed | ✅ 8 scenarios | ➖ |
| 3.1 | `tests/test_aggregation.py` | Unit | existing 70 green | ✅ Written | ✅ Passed | ✅ dedup/keep-on-doubt/sort/missing/invalid | ✅ Compacted |
| 3.2 | `tests/test_exporters.py` | Unit | existing 70 green | ✅ Written | ✅ Passed | ✅ sequence/timestamps/pair-failure | ✅ Compacted |
| 3.3 | `tests/test_state.py` | Unit | existing 70 green | ✅ Written | ✅ Passed | ✅ transitions/resume/cancel/cleanup | ✅ Compacted |
| 3.4 | `transcriptor/pipeline.py` | Runtime harness | existing 70 green | ➖ (composition) | ✅ Harness | ✅ bypass path E2E | ➖ |
| 3.5 | 3 test files | Unit | existing 70 green | ✅ Written | ✅ Passed | ✅ 7 required scenarios | ➖ |
| 4.1 | `tests/test_yurbaco_e2e.py` | E2E (gated) | existing 86 green | ✅ Written | ✅ Skip (prereq) | ✅ offline factory + invariant validator | ➖ |
| 4.2 | `tests/test_yurbaco_e2e.py` | Unit (classifier) | existing 86 green | ✅ Written | ✅ Passed | ✅ 4 classifications + clean + out-of-repo gate | ➖ |

## Work Unit Evidence

### Slice C

| Evidence | Value |
|---|---|
| Focused test command + result | `.venv/bin/pytest tests/test_aggregation.py tests/test_exporters.py tests/test_state.py -q` → `16 passed` |
| Runtime harness | `PYTHONPATH=. .venv/bin/python` harness: `pipeline.run` over synthetic 31 s WAV + stub transcriber → JSON/TXT agree, `export.complete` present, workspace cleaned, source unchanged |
| Rollback boundary | delete `transcriptor/aggregation.py`, `transcriptor/exporters.py`, `transcriptor/state.py`, `transcriptor/pipeline.py`, `tests/test_aggregation.py`, `tests/test_exporters.py`, `tests/test_state.py` |

### Slice D

| Evidence | Value |
|---|---|
| Focused test command + result | `.venv/bin/pytest tests/test_yurbaco_e2e.py -q` → `6 passed, 1 skipped` |
| Runtime harness | `N/A` — real path needs an out-of-repo `YURBACO_AUDIO_PATH` + cached weights + capacity; the gated E2E skips on the missing prerequisite and the classifier is exercised offline via `export_aggregate` |
| Rollback boundary | delete `tests/test_yurbaco_e2e.py` only |

## Deviations from Design

- Slice A (unchanged): `preprocess_chunk` returns the spec-02 contract dict (with
  `chunk_index` added for traceability); durations expressed via `source_start`/`source_end`
  plus inherent output WAV duration, matching the spec-02 example.
- Slice B (unchanged): reuse is instance-scoped (same `ChunkTranscriber` instance caches
  completed chunks keyed by `chunk_index`); cross-process checkpoint reuse belongs to
  `state.py` (Slice C).
- Slice C: identical-overlap dedup is conservative — only non-empty, byte-identical
  stripped text is removed; empty/silent overlaps and partial disagreements are kept and
  recorded in `metrics.ambiguities` rather than dropped. Aggregate final segments use the
  spec-04 contract field `id` (mapped from per-chunk `segment_id`) plus `provenance`
  (`chunk_index`, `source_start`, `source_end`), matching the 04 example rather than the
  per-chunk `segment_id` field name.
- Slice D: the E2E pins `model="tiny"` (per spec's "cached tiny weights" prerequisite)
  and injects an offline `transcriber_factory` with `local_files_only=True` so the
  pipeline never touches the network once the gate has confirmed cached weights — a
  refinement of the design's "cached tiny, offline" testing strategy. The capacity
  prerequisite is a single volume-wide free-space floor (256 MB) rather than per-path
  accounting. No production module was modified by this slice.

## Remaining Tasks (next slice)

- None — Slice D completes all four phases. Celery/Redis (AC-014) remains deferred by design.

## Boundary

- Work unit: Slice D (gated Yurbaco E2E)
- Start: tracker branch `feature/audio-chunk` (after Slice C)
- End: `tests/test_yurbaco_e2e.py` green; gated E2E skips deterministically when
  `YURBACO_AUDIO_PATH` is unset, with all four invariant classifications + clean-path
  + out-of-repo gate exercised offline
- Review budget: Slice D = 236 authored additions (test only), under the 400-line
  per-slice budget.
