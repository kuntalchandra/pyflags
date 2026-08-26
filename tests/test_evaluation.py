import logging

import pytest

from pyflags.config_store import ConfigStore
from pyflags.domain import EvaluationContext, Flag, FlagType, Operator, RolloutConfig, TargetingRule
from pyflags.evaluation import FlagEvaluator, FlagNotFoundError


def ctx(user_id, **attributes):
    return EvaluationContext(user_id=user_id, attributes=attributes)


class TestFlagNotFound:
    def test_unconfigured_flag_raises(self):
        evaluator = FlagEvaluator(ConfigStore())
        with pytest.raises(FlagNotFoundError):
            evaluator.evaluate("nonexistent", env="dev", context=ctx("u1"))


class TestPrecedenceChain:
    def test_targeting_rule_wins_over_rollout(self):
        store = ConfigStore()
        flag = Flag(
            name="checkout-v2",
            flag_type=FlagType.BOOLEAN,
            default=False,
            targeting_rules=(
                TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value=True),
            ),
            rollout=RolloutConfig(percentage=0, rollout_value=True),  # 0% - would never trigger anyway
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        result = evaluator.evaluate("checkout-v2", "dev", ctx("u1", country="IN"))
        assert result is True

    def test_rollout_used_when_no_targeting_rule_matches(self):
        store = ConfigStore()
        flag = Flag(
            name="checkout-v2",
            flag_type=FlagType.BOOLEAN,
            default=False,
            targeting_rules=(
                TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value=True),
            ),
            rollout=RolloutConfig(percentage=100, rollout_value=True),  # 100% - always in
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        # country=US doesn't match the targeting rule, falls through to rollout
        result = evaluator.evaluate("checkout-v2", "dev", ctx("u1", country="US"))
        assert result is True

    def test_default_used_when_no_targeting_and_not_in_rollout(self):
        store = ConfigStore()
        flag = Flag(
            name="checkout-v2",
            flag_type=FlagType.BOOLEAN,
            default=False,
            rollout=RolloutConfig(percentage=0, rollout_value=True),  # 0% - never in
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        result = evaluator.evaluate("checkout-v2", "dev", ctx("u1"))
        assert result is False

    def test_default_used_when_no_targeting_and_no_rollout(self):
        store = ConfigStore()
        flag = Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=False)
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        result = evaluator.evaluate("checkout-v2", "dev", ctx("u1"))
        assert result is False


class TestFailSafeOnInternalError:
    def test_unexpected_exception_returns_default_not_raises(self, monkeypatch):
        store = ConfigStore()
        flag = Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=False)
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr("pyflags.evaluation.evaluate_targeting_rules", boom)

        result = evaluator.evaluate("checkout-v2", "dev", ctx("u1"))
        assert result is False  # the flag's default, not a raised exception

    def test_internal_error_emits_structured_error_log(self, monkeypatch, caplog):
        store = ConfigStore()
        flag = Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=False)
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr("pyflags.evaluation.evaluate_targeting_rules", boom)

        with caplog.at_level(logging.ERROR, logger="pyflags.evaluation"):
            evaluator.evaluate("checkout-v2", "dev", ctx("u1"))

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.flag_name == "checkout-v2"
        assert record.env == "dev"
        assert record.user_id == "u1"


class TestEnvironmentIsolationThroughEvaluator:
    def test_same_flag_different_config_per_env(self):
        store = ConfigStore()
        store.set(Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=True), env="dev")
        store.set(Flag(name="checkout-v2", flag_type=FlagType.BOOLEAN, default=False), env="prod")
        evaluator = FlagEvaluator(store)

        assert evaluator.evaluate("checkout-v2", "dev", ctx("u1")) is True
        assert evaluator.evaluate("checkout-v2", "prod", ctx("u1")) is False
