---
name: in-process-service-design-exercise
description: Use this when designing and building a small, self-contained in-process service (no network layer, no UI) as a learning or interview-style exercise, especially one with deliberately ambiguous requirements that must be resolved before implementation. Covers the plan-first workflow, ambiguity resolution, layered validation strategy, fail-fast vs fail-safe error handling, and the incremental commit/review discipline that makes the resulting codebase genuinely reviewable.
---

# In-Process Service Design Exercise

A process for building a small, well-reasoned in-process service under a
problem statement that leaves some behavior deliberately ambiguous, in a
way that produces a *reviewable* artifact - not just working code, but code
whose decisions can be defended out loud.

## 1. Resolve ambiguity before writing code, and write down *why*

Problem statements for this kind of exercise usually list explicit open
questions ("what happens when X and Y are both configured?"). Resolve every
one of them in a `PLAN.md`, before any implementation - not as a quick
bullet list of decisions, but with a **stated reason each decision serves
the system's actual goals**, not just "seemed reasonable."

Bad: "Percentage rollouts use hash(user_id)."
Good: "Percentage rollouts use hash(scope + user_id), scope defaulting to
the flag name, because sticky-but-independent-per-flag bucketing is the
stated requirement, and a shared scope needs to be an opt-in for flags that
are deliberately correlated, not the default."

`PLAN.md` is committed once, early, and treated as append-only afterward -
see section 4.

## 2. Split "type-correct" from "domain-correct" - explicitly, in three layers

Dynamically-typed languages need this split made deliberate, not implicit:

1. **Type hints** - dev-time signal, not runtime enforcement by themselves.
2. **Runtime boundary validation** - is the shape/type of incoming data
   correct at all (e.g. a percentage is a number, not a string)? This is
   where a schema-validation library (Pydantic or equivalent) earns its
   place, colocated with the field it validates rather than buried in
   imperative `if` chains.
3. **Domain/business validation** - is the value *semantically* valid given
   context a single field can't know on its own (a percentage's numeric
   range, a rule's return value matching its owning object's declared
   type, no duplicate configuration entries)? This is cross-field or
   cross-object logic and belongs in explicit validators, not folded into
   layer 2's per-field checks.

Keeping these three named and separate - rather than one undifferentiated
"validation" blob - is what keeps the eventual code reviewable: a reviewer
can ask "is this a shape problem or a business-rule problem?" and get a
clean answer.

## 3. Fail-fast at the boundary, fail-safe at evaluation time - both, not either

For services whose whole purpose is being queried synchronously and
reliably:
- **Fail-fast**: reject bad configuration the moment it's registered/set,
  before it can ever be read back. Cheapest place to catch a mistake.
- **Fail-safe**: at the actual read/evaluation boundary, catch anything
  fail-fast didn't anticipate, log it with enough structured context to
  debug without reproducing, and return a safe fallback - never propagate
  an exception to the caller from a "the answer was requested" code path.

These are two different gates, not one. A codebase that only has one of
them either lets bad config in (no fail-fast) or can still blind-throw on
an unexpected bug (no fail-safe). Test each gate with a test that would
have failed without it - not a test that merely exercises the surrounding
code and happens to pass.

## 4. Distinguish plan changes from scope changes in the plan document

`PLAN.md`'s original body is committed once and never edited afterward.
Deviations get appended, but not into one undifferentiated log - split:

- **Plan Changes**: how you got to the same destination changed (a
  different implementation approach, a different exercise format) - the
  original goal is intact.
- **Scope Changes**: the destination itself changed (a requirement was
  dropped, narrowed, or added).

A reviewer skimming this distinction can immediately tell whether the
goalposts moved or just the path did - conflating the two makes every
deviation look like scope creep, even when it isn't.

## 5. Live-update / freshness requirements: push AND poll, not either

If a requirement says "must update without restart, within budget X
seconds," implement both an event-driven push path (near-instant, but can
miss a subscriber that registered late) and a time-based poll path (a
safety net, bounded by the poll interval). Neither alone reliably clears
the budget under all conditions; together they do, from two independent
paths. Test the poll path with the push path deliberately disabled (a test
double), not just the happy path where both are active - otherwise you've
only proven push works, not that poll independently would save you if push
failed.

## 6. Test the failure path you actually built, not an adjacent one

The most common false-confidence bug in this kind of exercise: writing a
test with a comment claiming it exercises an error/edge path, when the
specific inputs chosen don't actually trigger that path (e.g. asserting a
`TypeError` handler works using inputs that never raise `TypeError` in the
first place - the code silently returns a normal value instead). Coverage
tools will show the line as "covered" if it's reached at all, even by the
wrong route - they don't verify *which* path was taken to get there. When
writing a test for a specific exception/branch, deliberately construct the
minimal input that provably triggers *that exact* branch, and sanity-check
by temporarily removing the handler to confirm the test fails without it.

## 7. Commit and branch discipline that survives being reviewed

- One commit per meaningful unit of work, with a message that states *why*
  as well as *what* for anything non-mechanical (a design decision, a bug
  fix with a root cause) - generic messages ("updated X") on real decisions
  will draw reviewer questions a good message would have preempted.
- Work on a feature branch, push it early as a draft PR against the base
  branch - not direct commits to the main line. The PR diff, not raw
  `git log`, is the reviewable artifact a real reviewer works from.
- Tag meaningful before/after points only when they'll actually be diffed
  against later - an unused tag is harmless clutter, not a defect, but
  don't accumulate them without purpose.

## 8. Before any final review: separate "coverage exists" from "coverage means what you think"

Running a coverage tool and hitting a high percentage is necessary but not
sufficient. Go through each named requirement in the original problem
statement individually and find the *specific* test that proves it - not a
general sense that "the suite probably covers that." Gaps found this way
(a flag-type never exercised end-to-end despite type-construction tests
existing, a bool/int type-confusion edge case) are exactly the kind of
thing a reviewer finds first if you don't find it yourself.
