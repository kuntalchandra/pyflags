from __future__ import annotations

import logging
from typing import Any

from pyflags.bucketing import is_in_rollout
from pyflags.config_store import ConfigStore
from pyflags.domain import EvaluationContext, Flag
from pyflags.rule_engine import NO_MATCH, evaluate_targeting_rules

logger = logging.getLogger("pyflags.evaluation")


class FlagNotFoundError(Exception):
    """Raised when the requested flag isn't configured in the given env.

    Deliberately NOT swallowed into a default-value fallback: there is no
    default to fail-safe to for a flag that was never registered. This is a
    caller/config error (asking for something that doesn't exist), distinct
    from an internal error while evaluating a flag that DOES exist - which
    is what the fail-safe path below actually covers.
    """


class FlagEvaluator:
    """Public evaluation API. Wraps ConfigStore + rule engine + bucketing."""

    def __init__(self, store: ConfigStore) -> None:
        self._store = store

    def evaluate(self, flag_name: str, env: str, context: EvaluationContext) -> Any:
        flag = self._store.get(flag_name, env)
        if flag is None:
            raise FlagNotFoundError(f"flag '{flag_name}' not found in env '{env}'")

        try:
            return self._evaluate_flag(flag, context)
        except Exception:
            # Fail-safe boundary: ANY unexpected error during evaluation of a
            # known flag returns that flag's own default, never propagates to
            # the caller. Structured log carries enough to debug without
            # needing to reproduce - flag/env/user identify the "what", the
            # traceback (via exc_info) identifies the "why".
            logger.error(
                "flag evaluation failed, returning default",
                extra={
                    "flag_name": flag_name,
                    "env": env,
                    "user_id": context.user_id,
                    "default": flag.default,
                },
                exc_info=True,
            )
            return flag.default

    def _evaluate_flag(self, flag: Flag, context: EvaluationContext) -> Any:
        # Precedence: targeting rules -> percentage rollout -> default.
        matched = evaluate_targeting_rules(flag.targeting_rules, context)
        if matched is not NO_MATCH:
            return matched

        if flag.rollout is not None:
            if is_in_rollout(flag.rollout, flag.name, context):
                return flag.rollout.rollout_value
            return flag.default

        return flag.default
