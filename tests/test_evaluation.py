import pytest

from mnemofold.evaluation import (
    MetricResult,
    MetricStatus,
    ScenarioConfig,
    ScenarioResult,
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
    run_asof_scenario,
    run_commitment_scenario,
    run_commitment_slices,
    run_privacy_deletion_scenario,
    run_suite,
    run_triage_scenario,
    stale_fact_avoidance,
)
from mnemofold.factory import FactoryConfig


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


class TestCommitmentScenario:
    def test_scenario_runs_and_passes(self):
        result = run_commitment_scenario(ScenarioConfig(seed=42, days=90))
        assert isinstance(result, ScenarioResult)
        card = result.scorecard
        assert card.scenario == "commitments-seed42-90d"
        assert card.overall_pass(), [
            (m.name, m.value, m.status) for m in card.metrics if m.status != MetricStatus.PASS
        ]

    def test_recall_and_precision_are_measured_high(self):
        result = run_commitment_scenario(ScenarioConfig(seed=42, days=90))
        values = {m.name: m.value for m in result.scorecard.metrics}
        assert values["commitment_recall"] == 1.0
        assert values["commitment_precision"] == 1.0
        assert values["citation_validity"] == 1.0
        assert values["budget_adherence"] == 1.0
        assert values["replay_determinism"] == 1.0

    def test_details_label_synthetic_ground_truth(self):
        result = run_commitment_scenario(ScenarioConfig(seed=7, days=60))
        details = result.scorecard.details
        assert details["ground_truth"] == "synthetic planted commitments"
        assert details["planted_commitments"] >= 2
        assert details["recovered"] == details["planted_commitments"]

    def test_measurements_expose_counts(self):
        result = run_commitment_scenario(ScenarioConfig(seed=7, days=60))
        measured = result.measurements
        assert measured["planted"] >= 2
        assert measured["structured_mentions"] >= measured["recovered"]
        assert measured["checksum"]

    def test_scenario_is_deterministic(self):
        config = ScenarioConfig(seed=11, days=60)
        first = run_commitment_scenario(config).scorecard.to_dict()
        second = run_commitment_scenario(config).scorecard.to_dict()
        assert first == second


class TestCommitmentScenarioRobustness:
    @pytest.mark.parametrize("seed", [3, 11, 42])
    def test_recall_holds_across_seeds(self, seed):
        result = run_commitment_scenario(ScenarioConfig(seed=seed, days=60))
        assert result.measurements["commitment_recall"] == 1.0
        assert result.scorecard.overall_pass()

    def test_longer_history_plants_more(self):
        short = run_commitment_scenario(ScenarioConfig(seed=5, days=30))
        long = run_commitment_scenario(ScenarioConfig(seed=5, days=150))
        assert long.measurements["planted"] > short.measurements["planted"]
        assert long.scorecard.overall_pass()

    def test_now_day_shifts_overdue_population(self):
        early = run_commitment_scenario(ScenarioConfig(seed=42, days=90, now_day=10))
        late = run_commitment_scenario(ScenarioConfig(seed=42, days=90, now_day=85))
        assert late.measurements["actual_overdue"] >= early.measurements["actual_overdue"]
        assert early.scorecard.overall_pass()
        assert late.scorecard.overall_pass()

    def test_scorecard_serializes_cleanly(self):
        import json

        card = run_commitment_scenario(ScenarioConfig(seed=42, days=30)).scorecard
        payload = json.dumps(card.to_dict(), sort_keys=True)
        assert "commitment_recall" in payload
        assert json.loads(payload)["scenario"] == card.scenario


class TestTriageScenario:
    def test_reports_measured_precision_without_thresholds(self):
        result = run_triage_scenario(ScenarioConfig(seed=9, days=30))
        measured = result.measurements
        assert measured["inbox_items"] > 0
        assert measured["planted_mails"] >= 2
        assert 0.0 <= measured["precision_at_1"] <= 1.0
        assert 0.0 <= measured["precision_at_k"] <= 1.0
        # informational metrics carry no threshold -> never a false FAIL
        assert result.scorecard.overall_pass()
        assert all(m.threshold is None for m in result.scorecard.metrics)

    def test_details_label_the_ground_truth(self):
        result = run_triage_scenario(ScenarioConfig(seed=9, days=30))
        assert result.scorecard.details["ground_truth"] == "synthetic planted commitment mails"

    def test_k_matches_planted_count(self):
        result = run_triage_scenario(ScenarioConfig(seed=9, days=30))
        assert result.measurements["k"] == result.measurements["planted_mails"]

    def test_deterministic(self):
        cfg = ScenarioConfig(seed=9, days=30)
        first = run_triage_scenario(cfg).scorecard.to_dict()
        second = run_triage_scenario(cfg).scorecard.to_dict()
        assert first == second


class TestAsOfScenario:
    def test_accuracy_is_perfect_on_planted_changes(self):
        result = run_asof_scenario(ScenarioConfig(seed=42, days=180))
        assert result.measurements["probes"] >= 2
        assert result.measurements["accuracy"] == 1.0
        assert result.scorecard.overall_pass()

    def test_small_history_degrades_gracefully(self):
        result = run_asof_scenario(ScenarioConfig(seed=42, days=5))
        # degenerate or missing windows are skipped, never guessed at
        assert result.scorecard.overall_pass()
        assert result.measurements["accuracy"] == 1.0

    def test_details_label_ground_truth(self):
        result = run_asof_scenario(ScenarioConfig(seed=42, days=120))
        assert result.scorecard.details["ground_truth"] == "synthetic planted due-date changes"

    def test_deterministic(self):
        cfg = ScenarioConfig(seed=42, days=120)
        first = run_asof_scenario(cfg).scorecard.to_dict()
        second = run_asof_scenario(cfg).scorecard.to_dict()
        assert first == second


class TestScenarioSweeps:
    @pytest.mark.parametrize("seed", [3, 42])
    def test_core_scenarios_pass_across_seeds(self, seed):
        cfg = ScenarioConfig(seed=seed, days=60)
        assert run_commitment_scenario(cfg).scorecard.overall_pass()
        assert run_asof_scenario(cfg).scorecard.overall_pass()
        assert run_triage_scenario(cfg).scorecard.overall_pass()

    def test_commitment_recall_survives_noise(self):
        cfg = ScenarioConfig(seed=13, days=60, factory_config=FactoryConfig(noise_level=0.5))
        result = run_commitment_scenario(cfg)
        assert result.measurements["commitment_recall"] == 1.0
        assert result.scorecard.overall_pass()

    def test_expanded_history_with_designer_and_workflows(self):
        cfg = ScenarioConfig(
            seed=13,
            days=60,
            factory_config=FactoryConfig(include_designer=True, workflow_repeats=2),
        )
        result = run_commitment_scenario(cfg)
        assert result.measurements["commitment_recall"] == 1.0
        assert result.scorecard.overall_pass()

    def test_double_run_identical_scorecards(self):
        cfg = ScenarioConfig(seed=8, days=45)
        for runner in (run_commitment_scenario, run_asof_scenario, run_triage_scenario):
            first = runner(cfg).scorecard.to_dict()
            second = runner(cfg).scorecard.to_dict()
            assert first == second, runner.__name__


class TestPrivacyDeletionScenario:
    def test_zero_violations_and_clean_deletion(self):
        result = run_privacy_deletion_scenario(ScenarioConfig(seed=42, days=60))
        assert result.measurements["violations"] == []
        assert result.measurements["sampled"] > 0
        assert result.measurements["clean"] is True
        assert result.scorecard.overall_pass()

    def test_deletion_actually_removed_content(self):
        result = run_privacy_deletion_scenario(ScenarioConfig(seed=42, days=60))
        assert result.measurements["deleted"]

    def test_metric_directions(self):
        card = run_privacy_deletion_scenario(ScenarioConfig(seed=7, days=45)).scorecard
        by_name = {m.name: m for m in card.metrics}
        assert by_name["privacy_violations"].higher_is_better is False
        assert by_name["privacy_violations"].value == 0.0
        assert by_name["deletion_clean"].value == 1.0

    def test_deterministic(self):
        cfg = ScenarioConfig(seed=5, days=45)
        first = run_privacy_deletion_scenario(cfg).scorecard.to_dict()
        second = run_privacy_deletion_scenario(cfg).scorecard.to_dict()
        assert first == second


class TestCommitmentSlices:
    def test_slices_are_sorted_and_cover_planted_total(self):
        cfg = ScenarioConfig(seed=42, days=120)
        slices = run_commitment_slices(cfg)
        names = [r.scorecard.scenario for r in slices]
        assert names == sorted(names)
        total = sum(r.measurements["planted"] for r in slices)
        whole = run_commitment_scenario(cfg).measurements["planted"]
        assert total == whole

    def test_every_slice_passes(self):
        for result in run_commitment_slices(ScenarioConfig(seed=42, days=90)):
            assert result.scorecard.overall_pass(), result.scorecard.scenario
            values = {m.name: m.value for m in result.scorecard.metrics}
            assert values["slice_commitment_recall"] == 1.0

    def test_aggregate_of_slices_averages_recall(self):
        slices = run_commitment_slices(ScenarioConfig(seed=7, days=60))
        agg = aggregate_scorecards([r.scorecard for r in slices])
        assert agg.scenario == "aggregate"
        values = {m.name: m.value for m in agg.metrics}
        assert values["slice_commitment_recall"] == 1.0
        assert agg.overall_pass()

    def test_slices_deterministic(self):
        cfg = ScenarioConfig(seed=7, days=60)
        first = [r.scorecard.to_dict() for r in run_commitment_slices(cfg)]
        second = [r.scorecard.to_dict() for r in run_commitment_slices(cfg)]
        assert first == second


class TestEvaluationSuite:
    def test_suite_runs_every_scenario(self):
        suite = run_suite(ScenarioConfig(seed=42, days=60))
        scenarios = [card.scenario for card in suite.cards]
        assert scenarios == [
            "commitments-seed42-60d",
            "triage-seed42-60d",
            "asof-seed42-60d",
            "privacy-deletion-seed42-60d",
        ]

    def test_suite_passes_and_aggregates(self):
        suite = run_suite(ScenarioConfig(seed=42, days=60))
        assert suite.overall_pass()
        assert suite.aggregate.scenario == "aggregate"
        assert suite.aggregate.overall_pass()
        names = {m.name for m in suite.aggregate.metrics}
        assert {"commitment_recall", "as_of_accuracy", "privacy_violations"} <= names

    def test_suite_dict_roundtrip_shape(self):
        suite = run_suite(ScenarioConfig(seed=7, days=30))
        payload = suite.to_dict()
        assert payload["overall_pass"] is True
        assert len(payload["cards"]) == 4
        assert payload["aggregate"]["scenario"] == "aggregate"

    def test_suite_is_deterministic(self):
        cfg = ScenarioConfig(seed=11, days=45)
        first = run_suite(cfg).to_dict()
        second = run_suite(cfg).to_dict()
        assert first == second


class TestMetricThresholdSemantics:
    def test_higher_is_better_boundary_is_inclusive(self):
        assert MetricResult("m", 0.5, threshold=0.5).status == MetricStatus.PASS
        assert MetricResult("m", 0.499999, threshold=0.5).status == MetricStatus.FAIL

    def test_lower_is_better_boundary_is_inclusive(self):
        metric = MetricResult("m", 0.0, threshold=0.0, higher_is_better=False)
        assert metric.status == MetricStatus.PASS
        worse = MetricResult("m", 0.1, threshold=0.0, higher_is_better=False)
        assert worse.status == MetricStatus.FAIL

    def test_no_threshold_never_fails(self):
        assert MetricResult("m", 123.0).status == MetricStatus.PASS

    def test_aggregate_averages_and_keeps_threshold(self):
        first = Scorecard("s1")
        first.add(MetricResult("x", 1.0, threshold=0.5))
        second = Scorecard("s2")
        second.add(MetricResult("x", 0.0, threshold=0.5))
        agg = aggregate_scorecards([first, second])
        metric = agg.metrics[0]
        assert metric.value == 0.5
        assert metric.threshold == 0.5
        assert metric.status == MetricStatus.PASS  # boundary inclusive

    def test_aggregate_records_scenario_order(self):
        first = Scorecard("s1")
        second = Scorecard("s2")
        agg = aggregate_scorecards([first, second])
        assert agg.details["scenarios"] == ["s1", "s2"]

    def test_aggregate_empty_suite(self):
        agg = aggregate_scorecards([])
        assert agg.scenario == "aggregate"
        assert agg.metrics == []
        assert agg.overall_pass()
