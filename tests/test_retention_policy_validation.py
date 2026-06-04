"""Retention policy parameters are validated at construction."""

import pytest

from mnemofold.decay import DEFAULT_POLICIES, RetentionPolicy
from mnemofold.memory import MemoryTier


class TestPolicyValidation:
    def test_defaults_are_valid(self):
        for policy in DEFAULT_POLICIES.values():
            assert policy.half_life_days > 0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"half_life_days": 0},
            {"half_life_days": -1.0},
            {"grace_days": -1},
            {"max_age_days": 0},
            {"min_salience": -0.1},
            {"min_salience": 1.5},
            {"access_boost": -0.5},
            {"max_access_boosts": -1},
        ],
    )
    def test_invalid_parameters_raise(self, kwargs):
        with pytest.raises(ValueError):
            RetentionPolicy(MemoryTier.EPISODIC, **kwargs)

    def test_valid_custom_policy_accepted(self):
        policy = RetentionPolicy(
            MemoryTier.SEMANTIC,
            half_life_days=45.0,
            grace_days=0.0,
            min_salience=0.0,
            max_age_days=90.0,
            access_boost=0.0,
            max_access_boosts=0,
        )
        assert policy.decay_factor(45.0) == pytest.approx(0.5, abs=1e-9)
