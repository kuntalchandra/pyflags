# Code Review Reasoning Drill — Tracker

## Format (3 interrelated variants, can mix)
1. **Planted-defects review** — Claude takes real, working code (usually
   yours) and reintroduces deliberate bugs/smells across categories
   (concurrency, logic inversion, spec-violation, language footguns,
   debuggability). You review cold, write up findings, compare against
   what was actually planted.
2. **Unfamiliar-code review** — Claude hands over a small, plausible module
   you didn't write, for a structure/style/correctness pass. Removes the
   "this looks like my own code" false-familiarity effect.
3. **Reverse-shadowed defense** — Claude plays the engineer who wrote
   questionable code and defends it under your pushback; you play the
   reviewing EM. Tests reasoning under real-time challenge, not just
   spotting issues in a static read.

## Session log

### Session 1 — Format #1, pyflags `config_store.py` + `evaluation.py`
Planted 9 issues total (5 in config_store.py, 4 in evaluation.py) spanning:
mutable class-level default (classic Python footgun), missing lock in
get()/register_listener(), listener invoked while holding lock (deadlock
risk), inverted allow_overwrite condition, missing env validation, narrowed
except clause breaking "never blind-throw" spec requirement, truthy check
instead of NO_MATCH sentinel check (falsy-value bug), FlagNotFoundError
silently replaced with `return None`, missing exc_info in error log.

**Result: 4 of 9 found.**
- config_store.py: 3 clean catches (inverted allow_overwrite, missing env
  validation in get(), missing lock in get()) + 1 real-but-underspecified
  catch bundling two distinct bugs together (listener list not locked in
  register_listener, AND listener invoked while holding the lock in set()
  - named as one thing, should have been separated). Missed entirely: the
  mutable class-level `_listeners: list = []` shared-state footgun.
- evaluation.py: 1 of 4 found (missing exc_info). Missed: narrowed except
  clause (violates fail-safe spec requirement - the most serious miss),
  truthy check vs NO_MATCH sentinel (notable because a dedicated test for
  this exact bug class already exists in the real test suite - recognizing
  a known bug pattern while reading is harder than writing a test that
  catches it), and FlagNotFoundError silently becoming `return None`.

**Takeaway carried forward:** structural bugs (locking, validation gaps)
were caught reliably. Semantic bugs (wrong except tuple, wrong truthiness
check, wrong failure mode) that leave code *shape* unchanged were mostly
missed - familiar-looking code invites skimming, and single-token/logic
changes hide well inside a shape you recognize. Worth deliberately slowing
down on code that "looks like what I already know" rather than treating
familiarity as safety signal.

**Not yet done:** a tightened re-pass on evaluation.py specifically,
applying that lesson. Offered, deferred by user to continue with pyflags
steps first.

### Session 2 — mixed findings across four planted-defects rounds and one
### reverse-shadowed defense, roughly low to high priority

- [flag dependency PR] `depends_on_flag` missing `min_length` validation —
  cosmetic gap, same pattern as everywhere else in the domain models.
- [metrics/rate-limiter PR] `track_evaluation()`'s call counter ignores
  `env` — same flag name across different environments collapses into one
  counter; metrics become imprecise, nothing crashes.
- [evaluator registry PR] `active_environments()` returns stale entries —
  nothing removes an env after shutdown; bookkeeping-only impact.
- [flag expiration PR] `format_expiration_notice()` is unused *and* has a
  syntax error (missing closing paren) — dead code, harmless until touched,
  but blocks the whole module from importing.
- [bucket override PR] `_validate_bucket_range()` missing a colon — syntax
  error, blocks the whole module from importing.
- [bucket override PR] `register_override()` uses a mutable default dict
  argument (`overrides: dict = {}`) — silently shares state across
  unrelated calls.
- [metrics/rate-limiter PR] `EvaluationCache._cache` is a class attribute,
  not instance state (shared across every instance), and `ttl_seconds` is
  stored but never checked — entries never expire.
- [metrics/rate-limiter PR] `build_context_lookup()` — classic closure
  late-binding bug, every returned lambda captures the same loop variable
  and returns the *last* uid in the list, not its own.
- [bucket override PR] `apply_override()` does `overrides[user_id]` with no
  membership check — `KeyError` crash for any user without a registered
  override, i.e. the common case.
- [flag expiration PR] `is_expired()` wraps the comparison in a bare
  `except: return False` — silently treats any internal error (e.g. a
  naive-vs-timezone-aware datetime mismatch) as "not expired," permanently
  hiding a real defect rather than surfacing it.
- [evaluator registry PR] `shutdown()` wraps `cache.stop()` in a bare
  `except: pass` — masks any failure to stop a poll thread; silent
  resource leak, breaks the project's own "nothing fails silently"
  principle.
- [metrics/rate-limiter PR] `RateLimiter` never resets its counter — it's a
  lifetime cap disguised as a "window," so any legitimately high-traffic
  flag eventually gets permanently blocked, indistinguishable from an
  actual runaway loop.
- [metrics/rate-limiter PR] Both `_call_counts` and `RateLimiter.counts`
  use unlocked read-modify-write increments — real races under the
  concurrent poll/evaluation threads already in this codebase. The rate
  limiter one is worse: undercounting under load defeats the safety
  mechanism exactly when it's needed most.
- [bucket override PR] Overrides are keyed only by `user_id`, not
  `(flag_name, user_id)` — an override registered for one flag silently
  leaks into evaluation of every other flag for that same user.
- [flag expiration PR] `apply_expiration()`'s condition
  (`is_expired(...) or not fallback_to_default`) is inverted — any flag
  configured with `fallback_to_default=False` returns default
  unconditionally, even when not expired yet, and the `FlagExpiredError`
  branch becomes permanently unreachable dead code as a result.
- [evaluator registry PR] `shutdown()`'s condition
  (`not self._shutdown or force`) is inverted — `shutdown()` never
  actually shuts anything down, on any call, forced or not.
- [flag dependency PR] direct or indirect circular dependencies
  (`flag-A` → `flag-A`, or `flag-A` → `flag-B` → `flag-A`) cause infinite
  recursion in `_evaluate_flag`. Must be rejected at `ConfigStore.set()`
  via DFS cycle detection across already-stored flags for that env — not
  caught, and not catchable, at evaluation time, and a fixed max-depth
  constraint was explicitly rejected as a config-level SLA that could
  silently stop holding as configuration evolves.
- [bucket override PR] the override check in the evaluator wiring sits
  *after* the rollout block, which already returns in every branch — the
  entire override feature is dead code for any flag with a rollout
  configured.
- [flag expiration PR] the expiration check in the evaluator wiring sits
  after an unconditional `return` — the entire expiration feature is 100%
  dead code, for every flag, always.
- [evaluator registry PR] `_lock` is declared at class scope, not in
  `__init__` — shared across every registry instance, so unrelated
  registries contend on the same lock unnecessarily.
- [evaluator registry PR] `get_or_create()` checks `if env not in
  self._evaluators` *before* acquiring the lock, with no re-check inside
  it — broken double-checked locking. Concurrent calls for the same env
  can both create and start a full `LiveFlagCache` + poll thread; one
  silently overwrites the other, and the loser's poll thread leaks,
  orphaned, forever.

**Decoys correctly left unflagged, worth remembering as "not a bug"
reference points:** a module-level global counter used purely for
aggregate metrics (global scope was fine there — the *missing lock* was
the actual issue, not the scope itself); a `poll_interval` parameter that
was genuinely threaded through and used correctly; an `_evaluators` dict
correctly instance-scoped via `__init__` (not a repeat of the class-level
mutable-state bug, even though it looked similar at a glance); a decorator
using `functools.wraps` with no issues.

**Trend across sessions 1-2, worth re-reading before resuming:**
shared/global mutable state (class attributes, module globals, mutable
default arguments) was a recurring miss across the first three rounds,
each time correctly *sensed* as wrong but initially mis-named (called an
inheritance issue, an "uninitialized" issue, etc.) before landing on the
real mechanism. By the concurrency-focused round, this had fully
resolved — lock-scope and check-then-act races were found cleanly, a
boolean-inversion bug was traced at the expression level rather than
described only by its symptom, and two findings were surfaced
independently rather than matched against something already known to be
planted.
