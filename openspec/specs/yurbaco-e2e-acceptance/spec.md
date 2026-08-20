# Yurbaco E2E Acceptance Specification

## Purpose

Gate synchronous acceptance using an externally supplied `Yurbaco.m4a` and evidence for AC-015.

## Requirements

### Requirement: Gated full-pipeline acceptance

The E2E test MUST use `YURBACO_AUDIO_PATH` when supplied, otherwise the authorized repository-root `Yurbaco.m4a` fixture, plus local FFmpeg/ffprobe, cached local faster-whisper weights, and sufficient workspace/output capacity. It MUST never modify the source, MUST run stages 01–05 in order, preserve source hash, and emit job/config/tool versions and metrics.

#### Scenario: Prerequisites available

- GIVEN all prerequisites and an authorized readable `Yurbaco.m4a` source exist
- WHEN the E2E test runs
- THEN complete JSON and TXT outputs are produced and all chunk, audio, state, ordering, provenance, and cleanup invariants pass

#### Scenario: Prerequisite missing

- GIVEN the source, binary, weights, or capacity prerequisite is missing
- WHEN the E2E test is collected or run
- THEN it is deterministically gated as a prerequisite block, never a false pipeline pass

### Requirement: Source and output evidence

Every final segment MUST have absolute timestamps, literal text, and provenance. JSON and TXT MUST agree in sequence; the before/after source hash MUST match; temporary intermediates MUST NOT be committed. AC-014/Celery remains deferred and MUST NOT be introduced by this test.

#### Scenario: Invariant violation

- GIVEN a missing chunk, changed source hash, incoherent export, or surviving workspace
- WHEN acceptance evaluates evidence
- THEN acceptance fails and classifies the contract violation

#### Scenario: Literal ambiguity

- GIVEN overlap or model output is ambiguous
- WHEN the report is written
- THEN the literal text and ambiguity remain visible; no silent normalization is accepted
