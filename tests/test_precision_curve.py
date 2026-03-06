"""precision@k curve consistency with the point metric."""

from mnemofold.evaluation import precision_at_k, precision_at_k_curve

RELEVANT = {"a", "c", "e"}
RETRIEVED = ["a", "b", "c", "d", "e", "f"]


class TestPrecisionCurve:
    def test_matches_pointwise_calls(self):
        ks = [1, 2, 3, 5, 6]
        curve = precision_at_k_curve(RELEVANT, RETRIEVED, ks)
        for point in curve:
            assert point["precision"] == precision_at_k(RELEVANT, RETRIEVED, point["k"])

    def test_known_values(self):
        curve = precision_at_k_curve(RELEVANT, RETRIEVED, [1, 2, 3, 6])
        assert [p["precision"] for p in curve] == [1.0, 0.5, round(2 / 3, 6), 0.5]

    def test_cutoffs_sorted_and_deduped(self):
        ks = [5, 1, 5, 3, 1]
        assert [p["k"] for p in precision_at_k_curve(RELEVANT, RETRIEVED, ks)] == [1, 3, 5]

    def test_non_positive_k_scores_zero(self):
        curve = precision_at_k_curve(RELEVANT, RETRIEVED, [0, -3])
        assert all(p["precision"] == 0.0 for p in curve)

    def test_k_beyond_ranking_uses_full_list(self):
        curve = precision_at_k_curve(RELEVANT, RETRIEVED, [6, 100])
        assert curve[0]["precision"] == curve[1]["precision"] == 0.5

    def test_empty_ranking_is_all_zero(self):
        curve = precision_at_k_curve(RELEVANT, [], [1, 5])
        assert all(p["precision"] == 0.0 for p in curve)

    def test_all_relevant_is_all_one(self):
        curve = precision_at_k_curve({"x", "y"}, ["x", "y"], [1, 2])
        assert all(p["precision"] == 1.0 for p in curve)

    def test_deterministic(self):
        assert precision_at_k_curve(RELEVANT, RETRIEVED, [1, 3]) == (
            precision_at_k_curve(RELEVANT, RETRIEVED, [3, 1])
        )

    def test_quantized_to_six_decimals(self):
        curve = precision_at_k_curve({"a"}, ["a", "b", "c"], [3])
        assert curve[0]["precision"] == round(1 / 3, 6)
        assert len(str(curve[0]["precision"]).split(".")[-1]) <= 6
