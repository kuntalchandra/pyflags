from __future__ import annotations

import hashlib

from pyflags.domain import EvaluationContext, RolloutConfig


def _bucket(scope: str, user_id: str) -> int:
    """Deterministic bucket in [0, 99] for (scope, user_id).

    Uses hashlib (not the builtin hash()) because builtin string hashing is
    randomized per-process in Python by default - it would silently break
    sticky bucketing across restarts. md5 is used purely as a fast, stable
    bit-mixer here, not for any cryptographic purpose.
    """
    key = f"{scope}:{user_id}".encode("utf-8")
    digest = hashlib.md5(key).hexdigest()
    return int(digest, 16) % 100


def is_in_rollout(
    rollout: RolloutConfig, flag_name: str, context: EvaluationContext
) -> bool:
    """True if this user falls within the rollout's percentage, for this flag.

    Scope defaults to the flag's own name (independent buckets per flag).
    If shared_bucketing_key is set, that string is used instead, so multiple
    flags configured with the same key land the same users in the same
    bucket - e.g. two flags in the same experiment that should move together.
    """
    scope = rollout.shared_bucketing_key or flag_name
    return _bucket(scope, context.user_id) < rollout.percentage
