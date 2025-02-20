from mnemofold.evaluation import (
    MetricResult,
    MetricStatus,
    Scorecard,
    aggregate_scorecards,
    as_of_accuracy,
    budget_adherence,
    citation_validity,
    coverage_score,
    deletion_resurrection_check,
    f1_score,
    overdue_detection_accuracy,
    precision,
    precision_at_k,
    privacy_violation_count,
    recall,
    replay_determinism_score,
    stale_fact_avoidance,
)


def test_precision_at_k_perfect():
    relevant = {"a", "b", "c"}
    retrieved = ["a", "b", "c", "d", "e"]
    assert precision_at_k(relevant, retrieved, 3) == 1.0


def test_precision_at_k_half():
    relevant = {"a", "b"}
    retrieved = ["a", "x", "b", "y"]
    assert precision_at_k(relevant, retrieved, 4) == 0.5


def test_precision_at_k_zero_k():
    assert precision_at_k({"a"}, ["a"], 0) == 0.0


def test_precision_at_k_empty_retrieved():
    assert precision_at_k({"a"}, [], 5) == 0.0


def test_recall_perfect():
    assert recall({"a", "b"}, {"a", "b", "c"}) == 1.0


def test_recall_partial():
    assert abs(recall({"a", "b", "c"}, {"a", "d"}) - 1 / 3) < 1e-4


def test_recall_empty_relevant():
    assert recall(set(), {"a"}) == 1.0


def test_precision_perfect():
    assert precision({"a", "b"}, {"a"}) == 1.0


def test_precision_partial():
    assert precision({"a", "b"}, {"a", "c"}) == 0.5


def test_precision_empty_retrieved():
    assert precision({"a"}, set()) == 1.0


def test_f1_perfect():
    assert f1_score({"a", "b"}, {"a", "b"}) == 1.0


def test_f1_zero():
    assert f1_score({"a"}, {"b"}) == 0.0


def test_f1_balanced():
    p = precision({"a", "b", "c"}, {"a", "b", "d"})
    r = recall({"a", "b", "c"}, {"a", "b", "d"})
    expected = 2 * p * r / (p + r)
    assert abs(f1_score({"a", "b", "c"}, {"a", "b", "d"}) - expected) < 1e-6


def test_budget_adherence_within():
    assert budget_adherence(80, 100) == 1.0


def test_budget_adherence_exceeded():
    assert budget_adherence(101, 100) == 0.0


def test_budget_adherence_exact():
    assert budget_adherence(100, 100) == 1.0


def test_citation_validity_all_valid():
    cited = {"m1", "m2", "m3"}
    live = {"m1", "m2", "m3", "m4"}
    score, invalid = citation_validity(cited, live)
    assert score == 1.0
    assert invalid == set()


def test_citation_validity_some_invalid():
    cited = {"m1", "m2", "deleted_x"}
    live = {"m1", "m2", "m3"}
    score, invalid = citation_validity(cited, live)
    assert abs(score - 2 / 3) < 1e-4
    assert invalid == {"deleted_x"}


def test_citation_validity_empty():
    score, invalid = citation_validity(set(), {"m1"})
    assert score == 1.0
    assert invalid == set()


def test_overdue_detection_accuracy():
    actual = {"c1", "c2", "c3"}
    detected = {"c1", "c2", "c4"}
    result = overdue_detection_accuracy(actual, detected)
    assert abs(result["precision"] - 2 / 3) < 1e-4
    assert abs(result["recall"] - 2 / 3) < 1e-4
    assert "f1" in result


def test_stale_fact_avoidance_all_fresh():
    assert stale_fact_avoidance({"s1"}, {"f1", "f2"}) == 1.0


def test_stale_fact_avoidance_some_stale():
    result = stale_fact_avoidance({"s1", "s2"}, {"f1", "s1", "f2", "s2"})
    assert result == 0.5


def test_stale_fact_avoidance_empty_retrieved():
    assert stale_fact_avoidance({"s1"}, set()) == 1.0


def test_as_of_accuracy_perfect():
    expected = {"f1": "v1", "f2": "v2"}
    actual = {"f1": "v1", "f2": "v2", "f3": "v3"}
    assert as_of_accuracy(expected, actual) == 1.0


def test_as_of_accuracy_partial():
    expected = {"f1": "v1", "f2": "v2", "f3": "v3"}
    actual = {"f1": "v1", "f2": "wrong", "f4": "v4"}
    assert abs(as_of_accuracy(expected, actual) - 1 / 3) < 1e-4


def test_as_of_accuracy_empty_expected():
    assert as_of_accuracy({}, {"a": "b"}) == 1.0


def test_replay_determinism_identical():
    assert replay_determinism_score("abc123", "abc123") == 1.0


def test_replay_determinism_different():
    assert replay_determinism_score("abc", "def") == 0.0


def test_deletion_resurrection_clean():
    deleted = {"m1", "m2"}
    queries = {"q1": {"m3", "m4"}, "q2": {"m5"}}
    clean, found = deletion_resurrection_check(deleted, queries)
    assert clean is True
    assert found == set()


def test_deletion_resurrection_found():
    deleted = {"m1", "m2"}
    queries = {"q1": {"m1", "m3"}, "q2": {"m4"}}
    clean, found = deletion_resurrection_check(deleted, queries)
    assert clean is False
    assert found == {"m1"}


def test_privacy_violation_count():
    assert privacy_violation_count([]) == 0
    assert privacy_violation_count(["leak1", "leak2"]) == 2


def test_coverage_score_full():
    assert coverage_score({"a", "b"}, {"a", "b", "c"}) == 1.0


def test_coverage_score_partial():
    assert abs(coverage_score({"a", "b", "c"}, {"a", "d"}) - 1 / 3) < 1e-4


def test_coverage_score_empty_required():
    assert coverage_score(set(), {"a"}) == 1.0


def test_metric_result_pass_threshold_high():
    m = MetricResult(name="p_at_5", value=0.9, threshold=0.8, higher_is_better=True)
    assert m.status == MetricStatus.PASS


def test_metric_result_fail_threshold_high():
    m = MetricResult(name="p_at_5", value=0.7, threshold=0.8, higher_is_better=True)
    assert m.status == MetricStatus.FAIL


def test_metric_result_pass_threshold_low():
    m = MetricResult(name="latency", value=50, threshold=100, higher_is_better=False)
    assert m.status == MetricStatus.PASS


def test_metric_result_fail_threshold_low():
    m = MetricResult(name="latency", value=150, threshold=100, higher_is_better=False)
    assert m.status == MetricStatus.FAIL


def test_scorecard_basic():
    sc = Scorecard(scenario="test")
    sc.add(MetricResult(name="m1", value=0.9, threshold=0.8))
    sc.add(MetricResult(name="m2", value=0.5, threshold=0.7))
    assert sc.pass_count() == 1
    assert sc.fail_count() == 1
    assert sc.overall_pass() is False


def test_scorecard_all_pass():
    sc = Scorecard(scenario="test")
    sc.add(MetricResult(name="m1", value=0.9, threshold=0.8))
    sc.add(MetricResult(name="m2", value=0.95, threshold=0.9))
    assert sc.overall_pass() is True


def test_scorecard_to_dict():
    sc = Scorecard(scenario="demo", details={"seed": 42})
    sc.add(MetricResult(name="m1", value=1.0))
    d = sc.to_dict()
    assert d["scenario"] == "demo"
    assert d["overall_pass"] is True
    assert d["total_metrics"] == 1
    assert d["details"]["seed"] == 42


def test_aggregate_scorecards():
    s1 = Scorecard(scenario="a")
    s1.add(MetricResult(name="p", value=0.8))
    s1.add(MetricResult(name="r", value=0.6))
    s2 = Scorecard(scenario="b")
    s2.add(MetricResult(name="p", value=0.9))
    s2.add(MetricResult(name="r", value=0.8))

    agg = aggregate_scorecards([s1, s2])
    assert agg.scenario == "aggregate"
    metrics = {m.name: m.value for m in agg.metrics}
    assert metrics["p"] == 0.85
    assert metrics["r"] == 0.7
    assert len(agg.details["scenarios"]) == 2


def test_aggregate_empty():
    agg = aggregate_scorecards([])
    assert agg.scenario == "aggregate"
    assert agg.metrics == []
