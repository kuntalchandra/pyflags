# PLAN.md — In-Process Feature Flag Service (Python)

## Purpose
Self-initiated engineering practice exercise. Goal: build hands-on fluency in
Python design-for-testability, incremental git workflow, and a Claude-Code-style
build process (PLAN.md → implementation → tests → SKILL.md), using a Feature
Flag Service as the vehicle. Not for external distribution or evaluation.

## Stack
- Python 3.11+, standard library only for the core implementation
- pytest for the test suite
- No framework (no web layer, no admin UI — matches spec's out-of-scope list)
- GitHub Codespaces as the exclusive dev environment

---

## Typing & Validation Approach

Python is dynamically typed, so "type mismatch on rule value" and similar
correctness issues aren't caught by the language itself — this is handled
deliberately in three layers, not left implicit:

1. **Type hints everywhere** (`FlagType`, dataclass fields, function
   signatures) — for readability, IDE/static-analysis support, and as
   documentation of intent. Not enforced at runtime by themselves.
2. **Runtime validation at the boundary** — anywhere external input enters
   the system (a flag config passed to `ConfigStore.set()`, an
   `EvaluationContext` built from caller-supplied attributes), validate
   shape and type explicitly in code (e.g. `isinstance` checks, explicit
   `raise ValueError`/`InvalidFlagConfigError` on mismatch) before the data
   is trusted anywhere downstream. This is what actually implements
   "fail-fast at config time" from ambiguity #3 below.
3. **Domain validation for business rules** — separate from raw type
   checking: e.g. percentage must be in [0,100], a targeting rule's
   `return_value` must match the flag's declared `FlagType` (a `str` that
   happens to type-check fine in Python but is semantically wrong for a
   BOOL flag), rule ordering must produce deterministic first-match
   behavior. These are business invariants, not type errors, and get their
   own validation functions with their own tests — not bundled into the
   type-checking step.

No `mypy`/static type-checker dependency for now — type hints are used for
clarity, but the actual safety net is the runtime + domain validation, since
that's what the spec is really asking for ("never throw a blind error,"
"reject at config time"). Can revisit `mypy` later as a linting addition if
useful, but it's not load-bearing for correctness here.

## Resolved Ambiguities (decided here, before implementation)

### 1. Bucketing key for percentage rollouts
**Decision:** `hash(bucketing_scope + ":" + user_id) % 100`, where
`bucketing_scope` defaults to the flag's own name unless the flag config
explicitly sets `shared_bucketing_key: <group_name>`.
**Why:** Gives sticky, independent buckets per flag by default (spec
requirement: same user must get consistent answer *per flag*), while allowing
flags that are deliberately correlated (e.g., two flags in the same
experiment) to opt into sharing a bucket via a common scope string.

### 2. Precedence: targeting rules vs. percentage rollout
**Decision:** Targeting rules are evaluated first, in defined order,
first-match-wins. If no rule matches, fall through to the percentage rollout.
If no rollout is configured either, return the flag's default value.
**Why:** Targeting rules represent explicit, deliberate overrides (e.g. "IN
users always see true") — they should never be silently overridden by a
statistical rollout. Rollout is the fallback behavior for the unmatched
population.

### 3. Misconfiguration handling
**Decision:** Both.
- **Fail-fast at config time:** `ConfigStore.set()` validates the flag config
  (percentage in [0,100], rule value types match flag type, no duplicate rule
  keys) and raises `InvalidFlagConfigError` synchronously — bad config never
  enters the store.
- **Fail-safe at evaluation time:** any *unexpected* runtime exception during
  evaluation (e.g. a context attribute of the wrong type, a hash collision
  edge case) is caught at the evaluation boundary, logged as a structured
  error (flag name, env, context snapshot, exception), and the flag's default
  value is returned. The caller never sees an exception.
**Why:** Fail-fast keeps bad config out of the system entirely (cheap to
catch, obvious to fix). Fail-safe is the last line of defense for anything
fail-fast didn't anticipate — matches the spec's hard requirement to "never
throw a blind error to the caller."

### 4. Config update delivery: push vs poll
**Decision:** Both, layered.
- **Push:** `ConfigStore.set()` synchronously updates an in-memory version
  counter and notifies registered listeners (simple observer pattern) —
  near-instant propagation for in-process callers.
- **Poll:** the SDK evaluation layer also checks the store's version counter
  on a background thread every N seconds (default 2s) as a safety net, in
  case a listener was missed or added late.
**Why:** Push alone risks missed updates if a listener registers after a
push fires. Poll alone can't hit the <5s budget confidently under Codespaces
scheduling jitter without also having push do the heavy lifting. Together
they comfortably clear the 5-second propagation budget from two independent
paths.

---

## Steps

1. **Environment setup (Codespaces)** — Python venv, `pytest` installed,
   project skeleton (`src/ffservice/`, `tests/`), git init, `.gitignore`.
   Commit: "chore: project skeleton".

2. **Commit this PLAN.md** as the first real commit. Not modified after this
   point — deviations get logged in the tracker, not edited in here.

3. **Domain modeling** — `FlagType` enum (BOOL/STRING/INT), `Flag` dataclass
   (name, type, default, targeting_rules, rollout, bucketing_scope),
   `TargetingRule` dataclass (attribute, operator, value, return_value),
   `EvaluationContext` dataclass (user_id, tenant, attributes dict). Full
   type hints on all fields. Runtime validation in `__post_init__` for
   shape/type correctness (e.g. `attributes` is actually a dict).
   Tests: construction, and rejection of malformed input at the boundary.

4. **ConfigStore** — `set(flag_config, env)` with fail-fast *domain*
   validation (percentage in [0,100], rule return_value type matches the
   flag's declared FlagType, no duplicate rule keys — business rules, kept
   separate from the boundary type-checks in step 3), `get(flag_name, env)`
   with environment isolation, version counter + listener registration for
   push updates.
   Tests: environment isolation, invalid config rejection (one test per
   distinct business rule, not just one generic "bad config" test).

5. **Targeting rule engine** — evaluate rules against an `EvaluationContext`,
   first-match-wins, type-safe comparisons.
   Tests: matching rule, no matching rule, multiple rules order-dependence.

6. **Bucketing** — hash-based sticky bucketing per the resolved bucketing key,
   percentage threshold check.
   Tests: same user → same bucket across repeated calls, distribution
   sanity-check across many synthetic users, independent flags produce
   independent buckets, shared-scope flags produce identical buckets.

7. **Evaluation engine** — wires rule engine + bucketing + default-on-error
   into one `evaluate(flag_name, env, context)` call implementing the
   targeting-then-rollout-then-default precedence, wrapped in the fail-safe
   try/except with structured logging.
   Tests: full precedence chain, default-on-internal-error.

8. **Live update mechanism** — background poll thread + push listener hookup
   from the ConfigStore into the evaluation engine's cached view; measure
   propagation latency in a test (assert <5s, realistically near-instant for
   push).
   Tests: update visible after `set()`, no restart required.

9. **Full test suite pass + review** — run everything together, check
   coverage against the spec's required list (flag types, targeting,
   stickiness, environment isolation, default-on-error), fill gaps.

10. **Self-run timed drill** — simulate the interview clock. Do a clean
    run-through of the build from a fresh checkout, timed, to build muscle
    memory of the whole flow end-to-end.

11. **Extension drill (~last 20 min)** — see below. Introduced after step 10
    is comfortable, implemented under time pressure against the existing
    codebase.

12. **SKILL.md** — package the process (not the code) into a reusable
    SKILL.md: how to approach an in-process service design exercise, the
    ambiguity-resolution checklist, the PLAN → build → test → drill rhythm.
    Written last, after end-to-end validation, per process requirement.

13. **Reverse-shadowed EM/Sr. EM code review** — you drive the review as the
    reviewer, I reverse-shadow (play the engineer being reviewed / prompt
    your review instincts where useful). Culminating activity.

---

## Extension Drill (planned in advance, content withheld until step 11)

Candidates to introduce as the "extension" at step 11 (pick one on the day,
don't peek at this list before then if you want the surprise-pressure effect
to be genuine):
- Add a **kill switch**: a flag-level `killed: bool` that forces the default
  value regardless of targeting/rollout, checked before everything else.
- Add **flag dependencies**: flag B only evaluates if flag A resolves to a
  specific value.
- Add a **sticky-bucketing override**: allow forcing a specific user into a
  specific bucket for QA/debugging, bypassing the hash.
- Swap the poll interval to be configurable per-environment and prove it via
  a test with a shortened interval.

## Out of Scope (unchanged from spec)
Persistent store, UI/admin panel, network/transport layer, multi-region
replication.
