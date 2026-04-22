<!--
SYNC IMPACT REPORT
==================
Version change: (none — initial constitution) → 1.0.0
Modified principles: N/A (initial authoring)
Added sections:
  - Core Principles (5 principles)
  - Performance Requirements
  - Technical Decision Governance
  - Governance

Removed sections: N/A

Template alignment:
  - .specify/templates/plan-template.md       ✅ Compatible — Constitution Check section
                                                 dynamically references this file
  - .specify/templates/spec-template.md       ✅ Compatible — Success Criteria and FR
                                                 sections align with all 5 principles
  - .specify/templates/tasks-template.md      ✅ Compatible — Phase N includes
                                                 performance, observability, and testing
                                                 tasks matching these principles
  - .specify/templates/commands/*.md          ✅ No command files present; N/A

Follow-up TODOs:
  - TODO(RATIFICATION_DATE): Confirm exact project kick-off date if different from
    today's date (2026-04-22). Update if needed.
-->

# ArXivAgent Constitution

## Core Principles

### I. Code Quality Standards

Every line of code in ArXivAgent MUST be readable, purposeful, and maintainable
without explanation. Concretely:

- Functions MUST do one thing; files MUST have a single responsibility.
- Variable and function names MUST be self-documenting; abbreviations are
  forbidden except for universally accepted conventions (e.g., `id`, `url`).
- Comments are PROHIBITED unless the **why** is non-obvious (a hidden invariant,
  a workaround for an upstream bug, or a regulatory constraint). What the code
  does is expressed by the code itself.
- Dead code, unused imports, and unreachable branches MUST be removed before
  merge; they are not left behind with `# removed` annotations.
- Complexity MUST be justified in the feature plan's Complexity Tracking table.
  Any abstraction without a concrete, present use-case is rejected.

### II. Test-First Development (NON-NEGOTIABLE)

Tests MUST be written and confirmed to fail **before** the implementation that
makes them pass. No exceptions.

- **Unit tests** are required for every non-trivial function that encodes
  business logic.
- **Integration tests** are required for every user-facing workflow and every
  external API or data-source interaction.
- The Red-Green-Refactor cycle is the only accepted implementation path.
- Tests MUST assert observable outcomes, not implementation details; mocking
  internal modules is prohibited. External I/O (network, filesystem, database)
  MAY be mocked at system boundaries only.
- A PR that reduces test coverage without an explicit waiver approved in the
  Governance section MUST NOT be merged.

### III. User Experience Consistency

Every user-facing interaction — CLI output, API responses, error messages,
and rendered content — MUST follow the same conventions throughout the project.

- Error messages MUST follow the pattern: `[context] what went wrong: why`.
- API responses MUST use a single envelope schema (`data`, `error`, `meta`);
  ad-hoc response shapes are prohibited.
- CLI output MUST support both human-readable and `--json` machine-readable
  formats wherever output is consumed programmatically.
- Terminology used in the interface (e.g., "paper", "author", "query") MUST
  match the terminology in the specification and data model — no synonyms.
- Breaking changes to any public interface require a MAJOR version bump and
  a migration note.

### IV. Performance Requirements

ArXivAgent MUST meet performance targets at every merge to `main`.

- **Latency**: All synchronous user-facing operations MUST complete in ≤ 2 s
  at p95 under normal load (single-user, test environment).
- **Throughput**: Batch operations (e.g., paper ingestion, embedding generation)
  MUST process ≥ 10 items/s on reference hardware (4-core CPU, 8 GB RAM).
- **Memory**: The resident set size of any long-running process MUST NOT
  exceed 512 MB under sustained workload.
- Performance regressions > 20 % from baseline on any tracked metric MUST
  be treated as blocking bugs, not tech-debt.
- Every feature plan MUST state explicit performance goals in the Technical
  Context section; "NEEDS CLARIFICATION" is only acceptable pre-research phase.

### V. Observability & Maintainability

The system MUST be debuggable in production without source-level access.

- Structured logging (JSON) is REQUIRED for all service-level events; log
  level MUST be configurable via environment variable (`LOG_LEVEL`).
- Every external call (arXiv API, LLM API, database) MUST emit a log entry
  at `DEBUG` level on entry and `INFO` or `ERROR` on exit, including
  elapsed time.
- Metrics (request counts, error rates, latencies) MUST be exposed via a
  standard endpoint or stdout format (e.g., Prometheus text exposition) when
  the project is deployed as a service.
- Dependencies MUST be pinned to exact versions in lock files; floating
  ranges are prohibited in production configurations.

## Performance Requirements

The targets in Principle IV are derived from the following reference hardware
and usage profile. They MUST be re-evaluated when the deployment target or
expected usage changes substantially.

| Metric               | Target        | Measurement Method            |
|----------------------|---------------|-------------------------------|
| p95 response latency | ≤ 2 000 ms    | Integration test timing       |
| Batch throughput     | ≥ 10 items/s  | Benchmark script in `tests/`  |
| Peak memory (RSS)    | ≤ 512 MB      | `memory_profiler` / `/proc`   |
| Test suite runtime   | ≤ 60 s        | CI timer on full `pytest` run |

Any feature that cannot meet these targets without architectural changes MUST
document the trade-off in the Complexity Tracking table and obtain approval
via the amendment procedure below.

## Technical Decision Governance

These principles govern every technical decision made during design, review,
and implementation:

1. **Constitution-First Gate**: Every implementation plan MUST include a
   Constitution Check section verifying compliance with all five principles
   before Phase 0 research begins. The plan is invalid without it.

2. **Principle Hierarchy**: When principles conflict, resolve in this order:
   Test-First (II) > Code Quality (I) > UX Consistency (III) >
   Performance (IV) > Observability (V). Deviations MUST be documented.

3. **Amendment Before Deviation**: No principle may be violated without first
   amending this constitution. Shipping non-compliant code is not an
   acceptable workaround for an inconvenient principle.

4. **Review Obligation**: Every PR reviewer MUST verify constitution compliance
   as a hard gate — not a soft suggestion. A PR that violates a principle
   MUST NOT receive approval until the violation is resolved or an amendment
   is ratified.

5. **Complexity Justification**: Any design that adds indirection, abstraction,
   or layers beyond the minimum needed MUST justify itself in writing in the
   plan's Complexity Tracking table. YAGNI applies by default.

6. **Tooling Alignment**: Linters, formatters, and static analysis tools MUST
   be configured to enforce Code Quality and Observability principles
   automatically. Manual enforcement is a fallback, not the primary gate.

## Governance

This constitution supersedes all other project conventions, style guides, or
verbal agreements. Where it conflicts with a dependency's documentation or
community convention, this constitution takes precedence within this project.

**Amendment Procedure**:

1. Open a PR with the proposed change to this file.
2. Provide a written rationale explaining why the current principle is
   insufficient or incorrect.
3. Identify all dependent artifacts that require updates (templates, docs,
   CI config) and include those changes in the same PR.
4. At least one other contributor MUST review and approve before merge.
5. Update `LAST_AMENDED_DATE` and increment `CONSTITUTION_VERSION` according
   to the semantic versioning rules defined below.

**Versioning Policy**:

- **MAJOR** — A principle is removed, renamed, or its non-negotiable rules
  are relaxed in a backward-incompatible way.
- **MINOR** — A new principle or mandatory section is added, or existing
  guidance is materially expanded.
- **PATCH** — Wording is clarified, typos fixed, or non-semantic refinements
  made without changing intent.

**Compliance Review**:

Constitution compliance MUST be reviewed at the start of each new feature
(Constitution Check in plan.md) and again after Phase 1 design completes.
A retrospective note MUST be added to the plan if any principle required
a deviation that was not caught at the gate.

**Version**: 1.0.0 | **Ratified**: 2026-04-22 | **Last Amended**: 2026-04-22
