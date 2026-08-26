from __future__ import annotations

import logging
from typing import Any

from pyflags.bucketing import is_in_rollout
from pyflags.domain import EvaluationContext, Flag
from pyflags.live_updates import FlagSource
from pyflags.rule_engine import NO_MATCH, evaluate_targeting_rules

logger = logging.getLogger("pyflags.evaluation")


class FlagNotFoundError(Exception):
    """Raised when the requested flag isn't configured in the given env."""


class FlagEvaluator:
    """Public evaluation API. Works against any FlagSource - a raw
    ConfigStore, or a LiveFlagCache wrapping one - the evaluator doesn't
    know or care which."""

    def __init__(self, source: FlagSource) -> None:
        self._source = source

    def evaluate(self, flag_name: str, env: str, context: EvaluationContext) -> Any:
        flag = self._source.get(flag_name, env)
        if flag is None:
            raise FlagNotFoundError(f"flag '{flag_name}' not found in env '{env}'")

        try:
            return self._evaluate_flag(flag, context)
        except Exception:
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
        matched = evaluate_targeting_rules(flag.targeting_rules, context)
        if matched is not NO_MATCH:
            return matched

        if flag.rollout is not None:
            if is_in_rollout(flag.rollout, flag.name, context):
                return flag.rollout.rollout_value
            return flag.default

        return flag.default
