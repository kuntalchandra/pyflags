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


class TestAllFlagTypesEndToEnd:
    """Explicit spec requirement: flag TYPES are a first-class thing to test,
    not just BOOLEAN by default. Each type gets its own full precedence-chain
    proof, not just a construction check."""

    def test_string_flag_full_precedence_chain(self):
        store = ConfigStore()
        flag = Flag(
            name="button-color",
            flag_type=FlagType.STRING,
            default="blue",
            targeting_rules=(
                TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value="orange"),
            ),
            rollout=RolloutConfig(percentage=100, rollout_value="green"),
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        # targeting rule wins
        assert evaluator.evaluate("button-color", "dev", ctx("u1", country="IN")) == "orange"
        # falls through targeting to 100% rollout
        assert evaluator.evaluate("button-color", "dev", ctx("u2", country="US")) == "green"

    def test_string_flag_default_on_error(self, monkeypatch):
        store = ConfigStore()
        flag = Flag(name="button-color", flag_type=FlagType.STRING, default="blue")
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        monkeypatch.setattr(
            "pyflags.evaluation.evaluate_targeting_rules",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert evaluator.evaluate("button-color", "dev", ctx("u1")) == "blue"

    def test_integer_flag_full_precedence_chain(self):
        store = ConfigStore()
        flag = Flag(
            name="max-retries",
            flag_type=FlagType.INTEGER,
            default=3,
            targeting_rules=(
                TargetingRule(attribute="tier", operator=Operator.EQUALS, value="premium", return_value=10),
            ),
            rollout=RolloutConfig(percentage=100, rollout_value=5),
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        assert evaluator.evaluate("max-retries", "dev", ctx("u1", tier="premium")) == 10
        assert evaluator.evaluate("max-retries", "dev", ctx("u2", tier="basic")) == 5

    def test_integer_flag_default_on_error(self, monkeypatch):
        store = ConfigStore()
        flag = Flag(name="max-retries", flag_type=FlagType.INTEGER, default=3)
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        monkeypatch.setattr(
            "pyflags.evaluation.evaluate_targeting_rules",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert evaluator.evaluate("max-retries", "dev", ctx("u1")) == 3

    def test_integer_zero_is_a_valid_value_not_confused_with_falsy_default(self):
        # Guards against a real Python bug class: `if value:` style checks
        # would treat 0 as "missing" - evaluate() must return 0 itself, not
        # silently fall through to default because 0 is falsy.
        store = ConfigStore()
        flag = Flag(
            name="retry-delay",
            flag_type=FlagType.INTEGER,
            default=100,
            targeting_rules=(
                TargetingRule(attribute="fast_path", operator=Operator.EQUALS, value=True, return_value=0),
            ),
        )
        store.set(flag, env="dev")
        evaluator = FlagEvaluator(store)

        assert evaluator.evaluate("retry-delay", "dev", ctx("u1", fast_path=True)) == 0
