from __future__ import annotations

from typing import Any

from pyflags.domain import EvaluationContext, Operator, TargetingRule

# Sentinel distinct from None/False - both are legitimate return_values for
# a BOOLEAN flag, so neither can double as "no rule matched."
NO_MATCH = object()

_RESERVED_ATTRIBUTES = {"user_id", "tenant"}


def _resolve_attribute(attribute: str, context: EvaluationContext) -> Any:
    """Look up a rule's attribute against the context.

    Reserved names map to EvaluationContext's own fields; anything else is
    looked up in the free-form `attributes` dict. Returns NO_MATCH's sentinel
    marker (reused here, not just for return values) if the attribute is
    absent entirely - distinguishes "missing" from "present but None".
    """
    if attribute == "user_id":
        return context.user_id
    if attribute == "tenant":
        return context.tenant
    return context.attributes.get(attribute, NO_MATCH)


def _rule_matches(rule: TargetingRule, context: EvaluationContext) -> bool:
    actual = _resolve_attribute(rule.attribute, context)
    if actual is NO_MATCH:
        return False

    try:
        if rule.operator is Operator.EQUALS:
            return actual == rule.value
        if rule.operator is Operator.NOT_EQUALS:
            return actual != rule.value
        if rule.operator is Operator.IN:
            return actual in rule.value
        if rule.operator is Operator.NOT_IN:
            return actual not in rule.value
    except TypeError:
        # e.g. `actual in rule.value` where actual's type isn't comparable -
        # treat as no-match rather than propagating, per fail-safe principle.
        return False

    return False  # unreachable given Operator is an exhaustive enum, but explicit


def evaluate_targeting_rules(
    rules: tuple[TargetingRule, ...], context: EvaluationContext
) -> Any:
    """First-match-wins. Returns the matched rule's return_value, or the
    NO_MATCH sentinel if no rule matches (caller falls through to rollout)."""
    for rule in rules:
        if _rule_matches(rule, context):
            return rule.return_value
    return NO_MATCH
