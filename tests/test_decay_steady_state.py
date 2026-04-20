"""Steady-state detection over simulation day rows."""

from mnemofold.decay import find_steady_state


def row(day: int, demoted: int = 0, tombstoned: int = 0, purged: int = 0) -> dict:
    return {"day": day, "demoted": demoted, "tombstoned": tombstoned, "purged": purged}


class TestFindSteadyState:
    def test_empty_input(self):
        assert find_steady_state([]) is None

    def test_all_quiet_from_day_zero(self):
        results = [row(0), row(1), row(2)]
        assert find_steady_state(results) == 0

    def test_activity_then_quiet_tail(self):
        results = [row(0, demoted=2), row(1, demoted=1), row(2), row(3), row(4)]
        assert find_steady_state(results) == 2

    def test_never_settles(self):
        results = [row(0, demoted=1), row(1, purged=1), row(2, tombstoned=1)]
        assert find_steady_state(results) is None

    def test_quiet_middle_does_not_fool_it(self):
        results = [row(0), row(1), row(2, demoted=1), row(3)]
        assert find_steady_state(results) == 3

    def test_rows_without_activity_keys_count_quiet(self):
        results = [{"day": 0, "total_items": 3}, {"day": 1, "total_items": 3}]
        assert find_steady_state(results) == 0
