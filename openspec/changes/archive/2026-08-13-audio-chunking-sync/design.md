# Design: Synchronous Audio Chunking Pipeline

## Technical Approach

Implement specs 01–05 as a synchronous filesystem pipeline and gate spec 07 on external prerequisites. Keep shipped behavior unchanged: reuse `transcriptor/audio.py` validation, probing, executable resolution, WAV verification, structured subprocesses, and staged atomic writes. Introduce no Django, database, queue, or dependency.

## Architecture Decisions

| Decision | Alternatives | Rationale |
|---|---|---|
| Add stage modules around shipped audio primitives | Refactor `audio.py` into a generic runner | Avoid regression risk and speculative abstraction while keeping stages testable. |
| Use versioned `TypedDict`/JSON contracts and SHA-256 fingerprints | ORM models | Matches existing types, remains deterministic, and keeps Django decoupled. |
| One `ChunkTranscriber` per job | Call existing `transcribe()` per chunk | `transcribe()` constructs a model per call; lifecycle ownership guarantees one model and bounded retry. |
| Deduplicate only identical text in overlapping time ranges | Fuzzy lexical alignment | The product policy for partial matches is unresolved; keeping both prevents silent text loss. |
| Publish exports through a completion marker/checkpoint | Claim a filesystem-wide atomic pair rename | Two files cannot be atomically renamed together; stage both, promote both, then announce completion atomically. |

## Data Flow and Contracts

```text
external source → chunker → chunks/manifest → preprocess → normalized chunks
     → ChunkTranscriber (one model) → per-chunk results → aggregate
     → staged JSON + TXT → atomic promotions → completed checkpoint → cleanup
                    state/checkpoint guards every stage and resume
```

Contracts are `audio-chunk/v1`, `audio-job/v1`, and `audio-transcription/v1`; floats are source-relative seconds. Stable IDs are `{job_id}:chunk-{index:06d}:segment-{local_index:06d}`. `source_id` hashes source bytes; `config_fingerprint` hashes canonical JSON of output-affecting settings and versions. Ordering is `(start, end, chunk_index, segment_id)`. Both exports consume one ordered list.

## File Plan

| File | Action | Responsibility |
|---|---|---|
| `transcriptor/chunker.py` | Create | Validate/hash source, reject unsafe workspace, compute windows, extract chunks, write manifest. |
| `transcriptor/preprocess.py` | Create | Atomic per-chunk mono/16 kHz/16-bit conversion; separate recorded VAD and denoising flags. |
| `transcriptor/chunk_transcriber.py` | Create | One-model lifecycle, literal text, absolute offsets, metrics, bounded per-chunk retry. |
| `transcriptor/aggregation.py` | Create | Validate completeness/timestamps, deterministic sort, identical-overlap reconciliation. |
| `transcriptor/exporters.py` | Create | Stage/promote JSON and TXT from one segment list; report paths only after both promotions. |
| `transcriptor/state.py` | Create | Transitions, fingerprints, checkpoints, reuse, cancellation, cleanup. |
| `transcriptor/pipeline.py` | Create | Thin synchronous composition only; no stage logic. |
| `tests/test_{chunker,preprocess,chunk_transcriber,aggregation,state}.py` | Create | Focused contract/integration tests with AC traceability. |
| `tests/test_yurbaco_e2e.py` | Create | Externally gated full-pipeline acceptance. |

## Error and Cleanup Behavior

Stage errors include job, stage, chunk, command, and bounded stderr, retaining the cause. Temporary files are invalid. Checkpoints use same-device sibling staging; incompatible source/config rejects reuse. Check cancellation before each chunk. Idempotent cleanup stays inside the owned workspace, preserves source/finals, and reports leftovers. Failed export promotion leaves no completion marker and removes its newly promoted sibling.

## Testing Strategy

| Layer | Coverage |
|---|---|
| Unit/contract | Windows, IDs/fingerprints, transitions, retry/reuse, literal text, offsets, ambiguity, pair-publication failure, cancellation/cleanup. |
| Integration | Gated real FFmpeg/ffprobe over synthetic WAV; argv/metacharacter safety, format verification, partial-write cleanup, source hash. |
| Model | Cached `tiny`, offline and shape-only; deterministic skip when absent; assert one construction. |
| E2E | Require external `YURBACO_AUDIO_PATH`, binaries, cached weights, and capacity; missing prerequisites skip, invariant violations fail. |

## Threat Matrix

| Boundary | Applicability | Safe/failure behavior | Planned RED test |
|---|---|---|---|
| FFmpeg/ffprobe subprocess | Applicable | Resolved executable plus structured argv, `shell=False`; nonzero/missing output maps to stage error and cleanup. | Metacharacter path remains one argv item; stderr and partial cleanup asserted. |
| Documentation-like paths | N/A — no executable classification | No path is executed by suffix. | None. |
| Git repository selection | N/A — no VCS automation | Repository is used only to reject workspace ancestry. | None. |
| Commit state | N/A — no Git mutation | No index interaction. | None. |
| Push state | N/A — no remote interaction | No push. | None. |
| PR commands | N/A — no PR automation | No composed PR command. | None. |

## Migration, Delivery, and Deferred Boundary

No migration required. Auto-chain four verified slices, each under 400 changed lines: **A** chunking/preprocessing; **B** lifecycle transcription; **C** aggregation/export/state/pipeline; **D** external Yurbaco E2E. Each carries tests and preserves Phase-1 APIs.

Celery/Redis (AC-014) is explicitly deferred. Stage contracts and stable artifact references are the future seam, but this change adds no task abstraction, broker configuration, concurrency API, async state, or dependency. Reconsider only after synchronous E2E records latency, memory, and cancellation evidence.

## Open Questions

None blocking. Partial overlap matching remains intentionally conservative until Yurbaco evidence supports a separate specification change.
