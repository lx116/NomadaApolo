# Transcription Aggregation Specification

## Purpose

Produce deterministic, provenance-preserving JSON and TXT from completed chunk results (AC-009..AC-011).

## Requirements

### Requirement: Deterministic conservative reconciliation

The system MUST reject incomplete or invalid chunk results, sort segments by `start`, `end`, `chunk_index`, then `segment_id`, and reconcile overlap deterministically. It MAY remove only proven duplicate text. On partial or ambiguous disagreement it MUST retain both or mark the ambiguity; it MUST NOT discard silently.

#### Scenario: Identical overlap

- GIVEN adjacent chunks contain identical overlapping text with valid absolute timestamps
- WHEN aggregation runs
- THEN one duplicate is removed and the decision remains traceable

#### Scenario: Partial disagreement

- GIVEN overlapping texts are partially different or the policy is undecided
- WHEN aggregation runs
- THEN content is preserved or explicitly marked ambiguous, retaining provenance

### Requirement: Consistent atomic exports

JSON and TXT MUST derive from the same final ordered segment list, preserve provenance and absolute timestamps, include chunk/segment/duration metrics, and be published atomically together or neither announced as final.

#### Scenario: Valid complete job

- GIVEN every required chunk is completed and timestamps are valid
- WHEN exports are generated
- THEN parseable JSON and formatted `[HH:MM:SS - HH:MM:SS]` TXT contain the same sequence

#### Scenario: Missing chunk

- GIVEN a required chunk is incomplete
- WHEN aggregation is requested
- THEN final exports are blocked and the missing chunk is identified
