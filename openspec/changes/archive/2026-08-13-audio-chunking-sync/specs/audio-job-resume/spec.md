# Audio Job Resume Specification

## Purpose

Provide local progress, compatible resume, cancellation, and safe cleanup (AC-005, AC-012, AC-013).

## Requirements

### Requirement: Versioned atomic job state

The system MUST enforce `created → chunking → preprocessing → transcribing → aggregating → completed`, with `failed` and `cancelled` terminals. It MUST atomically checkpoint source identity, configuration fingerprint, chunk states/hashes, errors, timestamps, and metrics after relevant transitions, rejecting invalid transitions.

#### Scenario: Process abort

- GIVEN a process aborts after a valid checkpoint
- WHEN the job is reopened
- THEN the checkpoint supplies diagnostic progress and only pending compatible work is eligible

#### Scenario: Incompatible resume

- GIVEN the source hash or configuration fingerprint differs
- WHEN resume is requested
- THEN prior artifacts are not reused and the mismatch is reported

### Requirement: Cancellation and cleanup

Cancellation MUST prevent new work, mark the job `cancelled`, and clean temporary artifacts. Success, failure, and cancellation MUST be idempotently cleaned while preserving the source and confirmed final outputs; a minimal diagnostic summary MAY remain outside the workspace.

#### Scenario: Cancellation between chunks

- GIVEN cancellation is requested after a chunk completes
- WHEN the next transition is evaluated
- THEN no later chunk starts, the job becomes `cancelled`, and cleanup runs

#### Scenario: Cleanup error

- GIVEN cleanup cannot remove one temporary artifact
- WHEN the terminal state is recorded
- THEN the source is untouched and the remaining diagnostic is reported rather than hidden (AC-005)
