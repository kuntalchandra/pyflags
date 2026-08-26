import pytest
from pydantic import ValidationError

from pyflags.domain import (
    EvaluationContext,
    Flag,
    FlagType,
    Operator,
    RolloutConfig,
    TargetingRule,
)


class TestTargetingRule:
    def test_valid_equals_rule(self):
        rule = TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value=True)
        assert rule.attribute == "country"

    def test_in_operator_requires_list_like_value(self):
        with pytest.raises(ValidationError):
            TargetingRule(attribute="country", operator=Operator.IN, value="IN", return_value=True)

    def test_in_operator_accepts_list_value(self):
        rule = TargetingRule(attribute="country", operator=Operator.IN, value=["IN", "US"], return_value=True)
        assert rule.value == ["IN", "US"]

    def test_empty_attribute_rejected(self):
        with pytest.raises(ValidationError):
            TargetingRule(attribute="", operator=Operator.EQUALS, value="IN", return_value=True)


class TestRolloutConfig:
    def test_valid_percentage(self):
        assert RolloutConfig(percentage=50).percentage == 50

    def test_out_of_range_percentage_rejected(self):
        with pytest.raises(ValidationError):
            RolloutConfig(percentage=150)

    def test_negative_percentage_rejected(self):
        with pytest.raises(ValidationError):
            RolloutConfig(percentage=-1)

    def test_non_numeric_percentage_rejected(self):
        with pytest.raises(ValidationError):
            RolloutConfig(percentage="fifty")

    def test_bool_percentage_rejected(self):
        with pytest.raises(ValidationError):
            RolloutConfig(percentage=True)


class TestFlag:
    def test_valid_flag_construction(self):
        flag = Flag(name="new-checkout", flag_type=FlagType.BOOLEAN, default=False)
        assert flag.targeting_rules == ()

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            Flag(name="", flag_type=FlagType.BOOLEAN, default=False)

    def test_default_type_mismatch_rejected(self):
        with pytest.raises(ValidationError):
            Flag(name="x", flag_type=FlagType.BOOLEAN, default="not-a-bool")

    def test_integer_flag_rejects_bool_default(self):
        # bool default on an INTEGER flag is a classic type-correct-but-wrong bug
        with pytest.raises(ValidationError):
            Flag(name="x", flag_type=FlagType.INTEGER, default=True)

    def test_rule_return_value_mismatch_rejected(self):
        rule = TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value="yes")
        with pytest.raises(ValidationError):
            Flag(name="x", flag_type=FlagType.BOOLEAN, default=False, targeting_rules=(rule,))

    def test_duplicate_rules_rejected(self):
        rule = TargetingRule(attribute="country", operator=Operator.EQUALS, value="IN", return_value=True)
        with pytest.raises(ValidationError):
            Flag(name="x", flag_type=FlagType.BOOLEAN, default=False, targeting_rules=(rule, rule))


class TestEvaluationContext:
    def test_valid_context(self):
        ctx = EvaluationContext(user_id="u123", tenant="acme", attributes={"country": "IN"})
        assert ctx.user_id == "u123"

    def test_empty_user_id_rejected(self):
        with pytest.raises(ValidationError):
            EvaluationContext(user_id="")


class TestRolloutValueTypeMatching:
    def test_rollout_value_matching_flag_type_accepted(self):
        rollout = RolloutConfig(percentage=50, rollout_value=True)
        flag = Flag(
            name="checkout-v2",
            flag_type=FlagType.BOOLEAN,
            default=False,
            rollout=rollout,
        )
        assert flag.rollout.rollout_value is True

    def test_rollout_value_type_mismatch_rejected(self):
        rollout = RolloutConfig(percentage=50, rollout_value="on")  # str on a BOOLEAN flag
        with pytest.raises(ValidationError):
            Flag(name="x", flag_type=FlagType.BOOLEAN, default=False, rollout=rollout)

    def test_string_flag_rollout_value(self):
        rollout = RolloutConfig(percentage=25, rollout_value="variant-b")
        flag = Flag(
            name="button-color",
            flag_type=FlagType.STRING,
            default="variant-a",
            rollout=rollout,
        )
        assert flag.rollout.rollout_value == "variant-b"
