# OpenSpec — NomadaApolo

This directory is the **artifact store for SDD (Spec-Driven Development)** on NomadaApolo.

Initialized: 2026-08-13 by `sdd-init`.

## Layout

- `config.yaml` — project SDD configuration (stack, testing, rules per phase). SDD phases read this first.
- `specs/` — source-of-truth main specs (empty at init; populated by `sdd-archive` merging delta specs).
- `changes/` — active SDD change cycles.
  - `<change-name>/` — current change: `proposal.md`, `specs/<domain>/spec.md` (delta), `design.md`, `tasks.md`, `verify-report.md`, `state.yaml`.
  - `archive/` — completed changes, archived as `YYYY-MM-DD-<change-name>/` (audit trail; never modified).

## Existing Product Specs (NOT managed by OpenSpec)

Pre-existing human-authored specs live in `specs/audio-chunck/` and `specs/sdd_*.md` at the repo root. They are **preserved and not overwritten** by SDD phases. SDD delta specs MAY reference their requirement IDs (`AC-001`..`AC-015`, `RF-*`, `RNF-*`).

## SDD Lifecycle

`proposal` → `spec` → `design` → `tasks` → `apply` → `verify` → `archive`

Execution mode: `auto`. Delivery strategy: `force-chained` (400-line review budget per slice).

## Persistence

Engram remains available for project memory and recovery notes; OpenSpec is the primary artifact store for SDD progress (per project `AGENTS.md`).
