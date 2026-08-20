# Exploration: audio-chunking-sync

**OpenSpec change:** `audio-chunking-sync`
**Implements product specs:** `specs/audio-chunck/00_indice.md` + `01..05` + `07_prueba_e2e_yurbaco.md` (synchronous pipeline). `06_celery_ejecucion_asincrona.md` is **deferred** under AC-014 and is out of scope.
**Acceptance anchor:** AC-001..AC-013 and AC-015. AC-014 only governs the Celery deferral; it is referenced, not implemented.
**Artifact store:** OpenSpec. Technical artifacts in English.

## Current State

The Phase-1 transcription engine is shipped across three flat modules at the repo root (not the `transcriptor/src/` layout the Fase-1 SDD §5.2 sketched):

- `transcriptor/audio.py` — `validate_audio_input(path) -> Path`, `probe_duration(path) -> float` (ffprobe), `normalize_audio(path, output_dir=None) -> Path` (ffmpeg -> 16 kHz mono 16-bit PCM WAV, `<stem>.16k-mono.wav`). Domain errors `AudioProbeError`, `NormalizationError`. Source-immutability is enforced (read-only open; output staged in `tempfile.mkstemp` then promoted with `os.replace`, with `finally` cleanup of partial output).
- `transcriptor/transcriber.py` — `transcribe(path, config=None)` wires validate -> probe -> normalize -> `WhisperModel` -> `model.transcribe` -> `_build_segments`. Domain error `TranscriptionError`; typed results `TranscriptionResult`, `TranscriptionMetrics`, `Segment`.
- `transcriptor/config.py` — `TranscriptionConfig` dataclass (model / language / device / compute_type / vad_filter / beam_size / output_dir / download_root / local_files_only).
- `transcriptor/__init__.py` is empty. **`exporters.py` and any `main.py`/CLI do NOT exist** despite Fase-1 SDD §5.2/§7 listing them; they are still unshipped (README "Not in this slice").

Test architecture (pytest, `testpaths=["tests"]`, `.venv/bin/pytest`) is a three-layer pattern every new stage must mirror:

1. **Contract (mocked)** — `tests/test_audio.py`, `tests/test_transcriber.py`. Monkeypatch `shutil.which` + `subprocess.run`; assert explicit argv, `shell=False`, single-argv metacharacter safety, domain errors carrying stderr, partial output cleaned, source bytes unchanged.
2. **Integration (ffprobe/ffmpeg-gated)** — `@pytest.mark.skipif` on `shutil.which("ffprobe"/"ffmpeg")`; real probe + normalize on stdlib-`wave` synthetic WAV; asserts mono/16k/16-bit.
3. **Real-model (faster-whisper `tiny`, offline, shape-only)** — deterministic skip when the `Systran/faster-whisper-tiny` snapshot is not cached (`_tiny_cache_present()` via `huggingface_hub.constants.HF_HUB_CACHE`); `local_files_only=True`; assertions are shape/types/bounds/finiteness, never exact text.

Repo-state observations that constrain the design:

- `Yurbaco.m4a` is committed at repo root and `output/Yurbaco.16k-mono.wav` exists from a prior `normalize_audio` run. This conflicts with `01` (the job workspace MUST NOT live under `specs/`, `src/`, `output/`, etc.) and `07` (Yurbaco.m4a is an external prerequisite, not copied to the repo). The pipeline workspace MUST be an isolated `<tmp_root>/<job_id>/` (system temp / explicit `.tmp`), never `output/`, and the E2E test MUST treat the source as an out-of-repo path even though a copy currently sits in the repo.

## Affected Areas

- `transcriptor/audio.py` — reuse `validate_audio_input`, `probe_duration`, `_resolve_executable`, `_verify_wav`, and the ffmpeg subprocess + staged-`os.replace` pattern. `normalize_audio`'s flat `<stem>.16k-mono.wav` naming and its default `output/` dir do NOT fit per-chunk layout (`preprocessed/<chunk_index:06d>.wav`); stage 02 must add per-`chunk_index` naming into the job workspace and optional VAD/denoising filter args. Source-immutability plus the `output/`-default coupling are the two reuse boundaries.
- `transcriptor/transcriber.py` — `transcribe()` builds a fresh `WhisperModel` per call. Stage `03` requires the model loaded ONCE per job and reused across all chunks with offset correction `absolute = chunk.source_start + local`. So `03` needs a model-lifecycle wrapper around `WhisperModel` (load once -> transcribe many chunks -> release) reusing `_build_segments` shape and `TranscriptionError` mapping; it must NOT call `transcribe()` per chunk (that re-loads the model each time, violating the "loaded once per process" requirement).
- `transcriptor/exporters.py` — does NOT exist yet. Stage `04` requires TXT `[HH:MM:SS - HH:MM:SS]` + JSON aggregate with a shared sequence and provenance. New module; TXT format matches Fase-1 §6, JSON matches the `04` `audio-transcription/v1` contract.
- `transcriptor/config.py` — extend/parameterize for chunking: 300 s limit, 1-2 s overlap, `job_id`, workspace root, `config_fingerprint` inputs. Ponytail: dataclass additions only, no config-for-constants.
- New modules (minimal recommendation, fewest files that preserve single-responsibility + per-stage testability): `transcriptor/chunker.py` (01), a small `transcriptor/preprocess.py` for the per-chunk ffmpeg adapter (02), the model-lifecycle transcription (03) co-located or a small `transcriptor/segmenter.py`, `transcriptor/exporters.py` (04), and `transcriptor/state.py` (05 checkpoint + state machine + cleanup). Exact module split is a design-phase decision; exploration recommends the minimum that keeps stages isolated.
- `tests/` — add per-stage contract tests mirroring the three layers, cross-stage contract tests, and the `07` E2E gated on `Yurbaco.m4a` being supplied (out-of-repo) and weights cached. Reuse `_make_wav`, `_write_wav_at`, `_mock_which`, the `CompletedProcess` fake-runner idiom, and the `_tiny_cache_present()` gate.
- `.venv/bin/pytest` is the `apply`/`verify` command (`openspec/config.yaml`); no coverage threshold is configured (`coverage_threshold: 0`).

## Approaches

1. **Reuse + extend the Phase-1 boundary (recommended)** — chunking/preprocessing reuse `audio.py`'s subprocess + atomic-write primitives; transcription adds a once-per-job `WhisperModel` wrapper reusing offset math; new `exporters.py` + a small `state.py` for 05. Staged workspace under `<tmp>/<job_id>/`.
   - Pros: maximal reuse; preserves source-immutability and the trust-boundary error model already proven by the existing tests; no new deps; matches ponytail ladder rungs 2/3/6.
   - Cons: needs a model-lifecycle wrapper because `transcribe()` re-instantiates per call; the `output/`-default coupling in `normalize_audio` must be overridden, not refactored (refactoring risks regressing shipped Slices 1-3b).
   - Effort: Medium. Review footprint exceeds one 400-line slice -> chained PRs recommended (one per stage family).

2. **Refactor `normalize_audio` to a generic ffmpeg runner, then build stages on it** — extract a shared `ffmpeg_run(argv, staged, final, verify)` helper used by both 01 chunk extraction and 02 preprocessing.
   - Pros: removes duplication between 01 and 02; cleanest long-term core.
   - Cons: touches the shipped, tested Phase-1 boundary -> risks regressing Slices 1-3b for a speculative DRY win; larger review surface early; violates ponytail "no unrequested abstraction" until 01/02 actually duplicate.
   - Effort: Medium-High.

3. **Wrap everything behind a single `pipeline.run(source)` orchestrator from day one** — one module exposing one function; stages become private internals.
   - Cons: couples all stages into one review unit (blows the 400-line budget); hard to test per stage; contradicts the specs' "each stage testable in isolation" principle. Not recommended.

## Recommendation

Approach 1 (reuse + extend). Minimum scope for `audio-chunking-sync`:

- **01** chunking (`chunker.py`): reuse `validate_audio_input` + `probe_duration`; workspace `<tmp>/<job_id>/` creation that FAILS if it preexists; deterministic `chunks/<chunk_index:06d>.<ext>`; atomic write (`mkstemp` + `os.replace`); per-chunk contract metadata; job manifest emitted before transcription. AC-001..AC-005; bypass for `duration < 300`.
- **02** preprocessing (`preprocess.py`): per-chunk ffmpeg -> `preprocessed/<chunk_index:06d>.wav`, mono/16k/16-bit; VAD vs denoising as SEPARATE recorded flags (AC-006/AC-007); reuse `_verify_wav`; partial output cleaned before error.
- **03** transcription (model-lifecycle wrapper): `WhisperModel` instantiated ONCE per job; per-chunk `model.transcribe`; offset correction `absolute = chunk.source_start + local`; literal text preserved; metrics; retry bounded to the failing chunk; `config_fingerprint` for idempotency (AC-008/AC-011/AC-012).
- **04** aggregation + `exporters.py`: deterministic sort by `(start, end, chunk_index, segment_id)`; conservative overlap dedup (keep-on-doubt; partial-edge policy stays `[Pendingiente de decision]` per spec until measured on `Yurbaco.m4a`); atomic TXT `[HH:MM:SS - HH:MM:SS]` + JSON `audio-transcription/v1` from one shared list (AC-009/AC-010/AC-011).
- **05** progress/resume (`state.py`): `created -> chunking -> preprocessing -> transcribing -> aggregating -> completed` (terminals `failed`, `cancelled`); `config_fingerprint`-guarded chunk reuse; atomic checkpoint (sibling file + `os.replace`); idempotent cleanup that never deletes the source or confirmed finals (AC-005/AC-012/AC-013).
- **07** E2E: gated contract over real `Yurbaco.m4a` supplied as an out-of-repo path; invariants + before/after source hash; deterministic skip when ffmpeg/weights/Yurbaco are missing; never commits intermediates (AC-015).

Split delivery (`auto-chain`, 400-line budget) — forecast for sdd-tasks:

- Slice A: 01 chunking + 02 preprocessing + contract/integration tests (shared ffmpeg pattern).
- Slice B: 03 transcription lifecycle + offset/metrics/retry.
- Slice C: 04 aggregation/exporters + 05 state machine/checkpoint/cleanup + cross-stage contract tests.
- Slice D: 07 E2E acceptance harness (gated, real-binary).

`sdd-tasks` MUST emit the guard lines `Decision needed before apply: Yes`, `Chained PRs recommended: Yes`, `400-line budget risk: High`.

## Risks

- `transcribe()` re-instantiates `WhisperModel` per call; building `03` on it directly re-loads the model per chunk (violates AC-008 / 03 "loaded once per process"). A lifecycle wrapper is mandatory, not optional.
- Repo currently commits `Yurbaco.m4a` and `output/Yurbaco.16k-mono.wav`; the pipeline workspace must never be `output/` and the `07` E2E test must source Yurbaco from outside the repo — otherwise AC-005/01 and AC-015 invariant checks deceive themselves.
- Overlap (1-2 s) can duplicate words; `04`'s dedup is conservative and the partial-edge policy is explicitly undecided. Implementing it prematurely risks silent text loss (violates the "conservacion literal" principle).
- Atomic rename on a non-local filesystem can corrupt the checkpoint; `05` MUST restrict the workspace to a local filesystem (spec states this; enforce in tests).
- Over-modularization risk: keep to the fewest files that let each stage be tested in isolation (ponytail).
- `large-v3` memory is configurable; concurrency is bounded only later (06). Single-job sync execution MUST NOT assume bounded concurrency now.

## Ready for Proposal

Yes. The change scope is well-bounded by `specs/audio-chunck/01..05` + `07`, the existing engine gives clear reuse boundaries, and the only real design forks (module split, dedup edge policy, Yurbaco sourcing) are all resolvable inside proposal/spec/design. Recommend the orchestrator tell the user: scope is sync stages 01-05 + E2E 07; Celery (06) stays deferred under AC-014; delivery will likely be chained PRs across ~4 slices given the 400-line review budget at `auto-chain`.
