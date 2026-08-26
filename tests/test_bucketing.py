import pytest

from pyflags.bucketing import _bucket, is_in_rollout
from pyflags.domain import EvaluationContext, RolloutConfig


def ctx(user_id):
    return EvaluationContext(user_id=user_id)


class TestStickiness:
    def test_same_user_same_flag_always_same_result(self):
        rollout = RolloutConfig(percentage=50)
        c = ctx("user-42")
        first = is_in_rollout(rollout, "checkout-v2", c)
        for _ in range(20):
            assert is_in_rollout(rollout, "checkout-v2", c) == first

    def test_bucket_value_itself_is_deterministic(self):
        b1 = _bucket("checkout-v2", "user-42")
        b2 = _bucket("checkout-v2", "user-42")
        assert b1 == b2


class TestIndependenceAcrossFlags:
    def test_default_scope_is_flag_name_so_flags_are_independent(self):
        # Same user, same percentage, but different flag names (= different
        # default scopes) should be able to diverge - not asserting a specific
        # divergent user here (that'd be flaky), instead asserting the bucket
        # *values* differ, which they will unless the hash coincidentally ties.
        b_a = _bucket("flag-a", "user-42")
        b_b = _bucket("flag-b", "user-42")
        assert b_a != b_b  # extremely likely with md5; see distribution test for rigor

    def test_shared_bucketing_key_makes_two_flags_agree(self):
        rollout_a = RolloutConfig(percentage=50, shared_bucketing_key="experiment-x")
        rollout_b = RolloutConfig(percentage=50, shared_bucketing_key="experiment-x")
        c = ctx("user-42")
        assert is_in_rollout(rollout_a, "flag-a", c) == is_in_rollout(rollout_b, "flag-b", c)

    def test_without_shared_key_two_flags_can_disagree(self):
        # Demonstrates independence isn't guaranteed to *always* differ per
        # user (that's just how hashing works) - it's guaranteed to be
        # computed independently. Verified properly via distribution test below.
        rollout_a = RolloutConfig(percentage=50)
        rollout_b = RolloutConfig(percentage=50)
        c = ctx("user-42")
        # No fixed assertion on equality/inequality for a single user - this
        # test exists to document the property, not assert a specific outcome.
        is_in_rollout(rollout_a, "flag-a", c)
        is_in_rollout(rollout_b, "flag-b", c)


class TestDistribution:
    def test_roughly_correct_percentage_at_scale(self):
        rollout = RolloutConfig(percentage=30)
        n = 10_000
        in_rollout_count = sum(
            is_in_rollout(rollout, "checkout-v2", ctx(f"user-{i}")) for i in range(n)
        )
        pct = (in_rollout_count / n) * 100
        # Loose tolerance - this is a statistical sanity check, not an exact
        # proof. md5-based bucketing should land within a couple points of 30%.
        assert 27 <= pct <= 33

    def test_independent_flags_produce_meaningfully_different_populations(self):
        n = 10_000
        rollout = RolloutConfig(percentage=50)
        in_a = {i for i in range(n) if is_in_rollout(rollout, "flag-a", ctx(f"user-{i}"))}
        in_b = {i for i in range(n) if is_in_rollout(rollout, "flag-b", ctx(f"user-{i}"))}
        overlap = len(in_a & in_b) / len(in_a)
        # If buckets were correlated across flags, overlap would be ~1.0.
        # True independence should land near 0.5 (each user independently
        # 50/50 in each flag).
        assert 0.4 <= overlap <= 0.6


class TestBoundaries:
    def test_zero_percent_excludes_everyone(self):
        rollout = RolloutConfig(percentage=0)
        for i in range(100):
            assert is_in_rollout(rollout, "checkout-v2", ctx(f"user-{i}")) is False

    def test_hundred_percent_includes_everyone(self):
        rollout = RolloutConfig(percentage=100)
        for i in range(100):
            assert is_in_rollout(rollout, "checkout-v2", ctx(f"user-{i}")) is True
