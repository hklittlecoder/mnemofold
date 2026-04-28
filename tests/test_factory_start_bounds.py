"""With a custom start date every timestamp lives inside the new window."""

from datetime import datetime, timedelta

from mnemofold.factory import WorkHistoryFactory

START = "2026-03-02"
DAYS = 21


def generated():
    return WorkHistoryFactory(seed=29, days=DAYS, start_date=START).generate()


class TestStartBounds:
    def test_events_within_window(self):
        events, _ = generated()
        lo = datetime.fromisoformat(f"{START}T00:00:00+00:00")
        hi = lo + timedelta(days=DAYS + 1)
        assert events
        for event in events:
            ts = datetime.fromisoformat(event.timestamp)
            assert lo <= ts < hi, event.timestamp

    def test_planted_deadlines_within_horizon(self):
        factory = WorkHistoryFactory(seed=29, days=DAYS, start_date=START)
        factory.generate()
        lo = datetime.fromisoformat(f"{START}T00:00:00+00:00")
        hi = lo + timedelta(days=DAYS + 40)
        commitments = [p for p in factory.planted_items() if p.kind == "commitment"]
        assert commitments
        for item in commitments:
            due = datetime.fromisoformat(item.data["due_date"])
            assert lo <= due < hi

    def test_generation_is_deterministic_for_custom_start(self):
        a = generated()[1].checksum
        b = generated()[1].checksum
        assert a == b

    def test_weekend_lightness_follows_the_new_calendar(self):
        # 2026-03-07/08 is the first weekend of the shifted window; the
        # baseline (2025-01-04/05) has weekends on different dates, so
        # per-day counts differ between the two histories
        shifted, _ = generated()
        baseline, _ = WorkHistoryFactory(seed=29, days=DAYS).generate()
        per_day_shifted: dict[str, int] = {}
        for e in shifted:
            per_day_shifted[e.timestamp[:10]] = per_day_shifted.get(e.timestamp[:10], 0) + 1
        per_day_base: dict[str, int] = {}
        for e in baseline:
            per_day_base[e.timestamp[:10]] = per_day_base.get(e.timestamp[:10], 0) + 1
        counts_shifted = [per_day_shifted.get(d, 0) for d in sorted(per_day_shifted)]
        counts_base = [per_day_base.get(d, 0) for d in sorted(per_day_base)]
        assert counts_shifted != counts_base
