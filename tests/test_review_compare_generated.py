"""Compare reviews generated from one ledger across two weeks.

Week 1 completes c1; week 2 completes c3 while c2 slides into overdue.
Review lines carry their citations as ``description [id]``; the delta
must name exactly those movements through the cited ids.
"""

import re

from mnemofold.ledger import Commitment, CommitmentLedger, CommitmentStatus
from mnemofold.review import WeeklyReviewGenerator, compare_reviews

W1 = ("2026-03-02T00:00:00+00:00", "2026-03-09T00:00:00+00:00")
W2 = ("2026-03-09T00:00:00+00:00", "2026-03-16T00:00:00+00:00")


def cited_ids(lines: list[str]) -> set[str]:
    ids: set[str] = set()
    for line in lines:
        ids.update(re.findall(r"\[([^\]]+)\]", line))
    return ids


def make_ledger() -> CommitmentLedger:
    ledger = CommitmentLedger()
    ledger.add(
        Commitment(
            commitment_id="c1",
            owed_by="ana",
            owed_to="bo",
            description="draft spec",
            due_date="2026-03-05T17:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    ledger.add(
        Commitment(
            commitment_id="c2",
            owed_by="bo",
            owed_to="ana",
            description="review spec",
            due_date="2026-03-12T17:00:00+00:00",
            created_at="2026-03-01T09:00:00+00:00",
        )
    )
    ledger.add(
        Commitment(
            commitment_id="c3",
            owed_by="cy",
            owed_to="ana",
            description="ship fix",
            due_date="2026-03-20T17:00:00+00:00",
            created_at="2026-03-09T09:00:00+00:00",
        )
    )
    assert ledger.transition("c1", CommitmentStatus.DONE, "2026-03-04T10:00:00+00:00")
    assert ledger.transition("c3", CommitmentStatus.DONE, "2026-03-11T10:00:00+00:00")
    return ledger


class TestGeneratedComparison:
    def test_week_over_week_movements(self):
        gen = WeeklyReviewGenerator(ledger=make_ledger())
        week1 = gen.generate(*W1)
        week2 = gen.generate(*W2)
        assert "c1" in cited_ids(week1.completed)
        delta = compare_reviews(week1, week2)
        assert cited_ids(delta["completed_new"]) == {"c3"}
        assert cited_ids(delta["overdue_new"]) == {"c2"}
        assert delta["overdue_cleared"] == []

    def test_delta_is_deterministic(self):
        gen = WeeklyReviewGenerator(ledger=make_ledger())
        a = compare_reviews(gen.generate(*W1), gen.generate(*W2))
        b = compare_reviews(gen.generate(*W1), gen.generate(*W2))
        assert a == b

    def test_delta_only_cites_known_ids(self):
        gen = WeeklyReviewGenerator(ledger=make_ledger())
        week1, week2 = gen.generate(*W1), gen.generate(*W2)
        known = {"c1", "c2", "c3"}
        delta = compare_reviews(week1, week2)
        for key in (
            "completed_new",
            "completed_no_longer_listed",
            "overdue_new",
            "overdue_cleared",
            "still_open_new",
            "still_open_cleared",
        ):
            assert cited_ids(delta[key]) <= known, key
