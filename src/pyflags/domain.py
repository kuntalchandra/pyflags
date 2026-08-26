from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FlagType(str, Enum):
    BOOLEAN = "boolean"
    STRING = "string"
    INTEGER = "integer"


class Operator(str, Enum):
    EQUALS = "=="
    NOT_EQUALS = "!="
    IN = "in"
    NOT_IN = "not_in"


def _matches_flag_type(value: Any, flag_type: FlagType) -> bool:
    if flag_type is FlagType.BOOLEAN:
        return isinstance(value, bool)
    if flag_type is FlagType.STRING:
        return isinstance(value, str)
    if flag_type is FlagType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    return False


class TargetingRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    attribute: str = Field(min_length=1)
    operator: Operator
    value: Any
    return_value: Any

    @model_validator(mode="after")
    def _check_list_like_for_in_operators(self) -> "TargetingRule":
        if self.operator in (Operator.IN, Operator.NOT_IN) and not isinstance(
            self.value, (list, tuple, set)
        ):
            raise ValueError(
                f"Operator {self.operator} requires a list/tuple/set value, "
                f"got {type(self.value).__name__}"
            )
        return self


class RolloutConfig(BaseModel):
    """Percentage rollout for the population that matched no targeting rule.

    `rollout_value` is what's served to users who land inside the
    percentage bucket. Required (not defaulted to True) because assuming a
    boolean "on" value would be silently wrong for STRING/INTEGER flags -
    every flag type needs an explicit answer to "what does the rollout
    actually serve".
    """

    model_config = ConfigDict(frozen=True)

    percentage: float = Field(ge=0, le=100)
    rollout_value: Any
    shared_bucketing_key: Optional[str] = None

    @field_validator("percentage", mode="before")
    @classmethod
    def _reject_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("percentage must be a number, not a bool")
        return v


class Flag(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    flag_type: FlagType
    default: Any
    targeting_rules: tuple[TargetingRule, ...] = Field(default_factory=tuple)
    rollout: Optional[RolloutConfig] = None

    @model_validator(mode="after")
    def _check_default_matches_type(self) -> "Flag":
        if not _matches_flag_type(self.default, self.flag_type):
            raise ValueError(
                f"Flag '{self.name}': default={self.default!r} does not match "
                f"declared flag_type={self.flag_type}"
            )
        return self

    @model_validator(mode="after")
    def _check_rule_return_values_match_type(self) -> "Flag":
        for rule in self.targeting_rules:
            if not _matches_flag_type(rule.return_value, self.flag_type):
                raise ValueError(
                    f"Flag '{self.name}': targeting rule on '{rule.attribute}' "
                    f"has return_value={rule.return_value!r} which does not "
                    f"match declared flag_type={self.flag_type}"
                )
        return self

    @model_validator(mode="after")
    def _check_rollout_value_matches_type(self) -> "Flag":
        if self.rollout is not None and not _matches_flag_type(
            self.rollout.rollout_value, self.flag_type
        ):
            raise ValueError(
                f"Flag '{self.name}': rollout.rollout_value="
                f"{self.rollout.rollout_value!r} does not match declared "
                f"flag_type={self.flag_type}"
            )
        return self

    @model_validator(mode="after")
    def _check_no_duplicate_rules(self) -> "Flag":
        seen = set()
        for rule in self.targeting_rules:
            key = (rule.attribute, rule.operator, repr(rule.value))
            if key in seen:
                raise ValueError(
                    f"Flag '{self.name}': duplicate targeting rule for "
                    f"{rule.attribute} {rule.operator} {rule.value!r}"
                )
            seen.add(key)
        return self


class EvaluationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)
    tenant: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
