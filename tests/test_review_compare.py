"""Week-over-week review deltas."""

from mnemofold.review import WeeklyReview, compare_reviews


def review(week_start, week_end, **kwargs) -> WeeklyReview:
    return WeeklyReview(week_start=week_start, week_end=week_end, **kwargs)


W1 = ("2026-03-02", "2026-03-09")
W2 = ("2026-03-09", "2026-03-16")


class TestCompareReviews:
    def test_empty_reviews_produce_empty_delta(self):
        delta = compare_reviews(review(*W1), review(*W2))
        assert delta["completed_new"] == []
        assert delta["overdue_new"] == []
        assert delta["stats_delta"] == {}
        assert delta["previous_week"] == list(W1)
        assert delta["current_week"] == list(W2)

    def test_new_and_cleared_overdue(self):
        prev = review(*W1, overdue=["c1", "c2"])
        curr = review(*W2, overdue=["c2", "c3"])
        delta = compare_reviews(prev, curr)
        assert delta["overdue_new"] == ["c3"]
        assert delta["overdue_cleared"] == ["c1"]

    def test_completed_flows(self):
        prev = review(*W1, completed=["c1"])
        curr = review(*W2, completed=["c2", "c3"])
        delta = compare_reviews(prev, curr)
        assert delta["completed_new"] == ["c2", "c3"]
        assert delta["completed_no_longer_listed"] == ["c1"]

    def test_risk_changes(self):
        prev = review(*W1, risks=["slipping release", "unstaffed on-call"])
        curr = review(*W2, risks=["slipping release"])
        delta = compare_reviews(prev, curr)
        assert delta["risks_added"] == []
        assert delta["risks_removed"] == ["unstaffed on-call"]

    def test_stats_delta_covers_union_of_keys(self):
        prev = review(*W1, stats={"completed": 3, "overdue": 1})
        curr = review(*W2, stats={"overdue": 4, "added": 2})
        delta = compare_reviews(prev, curr)
        assert delta["stats_delta"] == {"added": 2, "completed": -3, "overdue": 3}

    def test_lists_are_sorted(self):
        prev = review(*W1, still_open=["z", "a"])
        curr = review(*W2, still_open=["m", "b"])
        delta = compare_reviews(prev, curr)
        assert delta["still_open_new"] == ["b", "m"]
        assert delta["still_open_cleared"] == ["a", "z"]

    def test_identical_reviews_have_empty_delta(self):
        same = review(*W1, completed=["c1"], overdue=["c2"], stats={"x": 1})
        delta = compare_reviews(same, same)
        for key in (
            "completed_new",
            "overdue_new",
            "overdue_cleared",
            "still_open_new",
            "risks_added",
        ):
            assert delta[key] == [], key
        assert delta["stats_delta"] == {"x": 0}
