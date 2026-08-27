import pytest

from pyflags.domain import EvaluationContext, Operator, TargetingRule
from pyflags.rule_engine import NO_MATCH, evaluate_targeting_rules


def rule(attribute, operator, value, return_value):
    return TargetingRule(attribute=attribute, operator=operator, value=value, return_value=return_value)


class TestBasicOperators:
    def test_equals_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "IN"})
        rules = (rule("country", Operator.EQUALS, "IN", True),)
        assert evaluate_targeting_rules(rules, ctx) is True

    def test_equals_no_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "US"})
        rules = (rule("country", Operator.EQUALS, "IN", True),)
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH

    def test_not_equals_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "US"})
        rules = (rule("country", Operator.NOT_EQUALS, "IN", True),)
        assert evaluate_targeting_rules(rules, ctx) is True

    def test_in_operator_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "US"})
        rules = (rule("country", Operator.IN, ["IN", "US"], True),)
        assert evaluate_targeting_rules(rules, ctx) is True

    def test_not_in_operator_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "FR"})
        rules = (rule("country", Operator.NOT_IN, ["IN", "US"], True),)
        assert evaluate_targeting_rules(rules, ctx) is True


class TestFirstMatchWins:
    def test_first_matching_rule_wins_over_later_ones(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "IN"})
        rules = (
            rule("country", Operator.EQUALS, "IN", "first"),
            rule("country", Operator.EQUALS, "IN", "second"),
        )
        assert evaluate_targeting_rules(rules, ctx) == "first"

    def test_earlier_non_matching_rule_falls_through_to_later_match(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "US"})
        rules = (
            rule("country", Operator.EQUALS, "IN", "first"),
            rule("country", Operator.EQUALS, "US", "second"),
        )
        assert evaluate_targeting_rules(rules, ctx) == "second"

    def test_no_rules_matched_returns_sentinel(self):
        ctx = EvaluationContext(user_id="u1", attributes={"country": "FR"})
        rules = (rule("country", Operator.EQUALS, "IN", True),)
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH

    def test_empty_rules_returns_sentinel(self):
        ctx = EvaluationContext(user_id="u1")
        assert evaluate_targeting_rules((), ctx) is NO_MATCH


class TestReservedAttributes:
    def test_targeting_on_user_id(self):
        ctx = EvaluationContext(user_id="u123")
        rules = (rule("user_id", Operator.EQUALS, "u123", True),)
        assert evaluate_targeting_rules(rules, ctx) is True

    def test_targeting_on_tenant(self):
        ctx = EvaluationContext(user_id="u1", tenant="acme")
        rules = (rule("tenant", Operator.EQUALS, "acme", True),)
        assert evaluate_targeting_rules(rules, ctx) is True

    def test_targeting_on_tenant_when_none_does_not_match(self):
        ctx = EvaluationContext(user_id="u1")  # tenant defaults to None
        rules = (rule("tenant", Operator.EQUALS, "acme", True),)
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH


class TestFailSafeOnMissingOrIncompatibleData:
    def test_missing_attribute_does_not_match_and_does_not_raise(self):
        ctx = EvaluationContext(user_id="u1", attributes={})
        rules = (rule("country", Operator.EQUALS, "IN", True),)
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH

    def test_incompatible_in_comparison_does_not_raise(self):
        # actual is an int, rule.value is a list of strings - `in` works fine
        # here (returns False), but this guards the TypeError path generally.
        ctx = EvaluationContext(user_id="u1", attributes={"age": 30})
        rules = (rule("age", Operator.IN, ["young", "old"], True),)
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH

    def test_bad_rule_does_not_block_a_later_good_rule(self):
        ctx = EvaluationContext(user_id="u1", attributes={"age": 30, "country": "IN"})
        rules = (
            rule("age", Operator.IN, ["young", "old"], "bad-match"),  # won't match, won't raise
            rule("country", Operator.EQUALS, "IN", "good-match"),
        )
        assert evaluate_targeting_rules(rules, ctx) == "good-match"


class TestGenuineTypeErrorFailSafe:
    """The earlier 'incompatible IN comparison' test didn't actually trigger
    a TypeError - `30 in ["young", "old"]` just evaluates False normally.
    This targets the real TypeError path: `in` on a set requires the left
    operand to be hashable, so an unhashable attribute value (a list) against
    a set-valued rule genuinely raises."""

    def test_unhashable_attribute_against_set_value_does_not_raise(self):
        ctx = EvaluationContext(user_id="u1", attributes={"tags": ["a", "b"]})
        rules = (rule("tags", Operator.IN, {"x", "y"}, True),)
        # Without the except TypeError guard, this would propagate a raw
        # TypeError to the caller - violating "never throw a blind error".
        assert evaluate_targeting_rules(rules, ctx) is NO_MATCH

    def test_bad_rule_via_typeerror_does_not_block_later_good_rule(self):
        ctx = EvaluationContext(user_id="u1", attributes={"tags": ["a", "b"], "country": "IN"})
        rules = (
            rule("tags", Operator.IN, {"x", "y"}, "bad-match"),  # raises internally, caught
            rule("country", Operator.EQUALS, "IN", "good-match"),
        )
        assert evaluate_targeting_rules(rules, ctx) == "good-match"
