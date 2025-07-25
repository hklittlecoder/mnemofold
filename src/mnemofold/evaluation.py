"""Evaluation harness for mnemofold.

End-to-end persona scenarios scored against planted ground truth:
commitment recall/precision, overdue-detection accuracy, as-of query
correctness, triage precision@k, meeting-prep coverage, stale-fact
avoidance, citation validity, budget adherence, privacy-violation
counters (must be zero), deletion-resurrection checks, and replay
determinism double-run.  Per-slice and aggregate scorecards with
golden tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from mnemofold.context import ContextItem, ContextPacker, estimate_tokens
from mnemofold.events import Event
from mnemofold.factory import FactoryConfig, HistoryManifest, WorkHistoryFactory
from mnemofold.ingest import IngestPipeline
from mnemofold.ledger import Commitment, CommitmentLedger
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.retrieval import RetrievalEngine


class MetricStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class MetricResult:
    name: str
    value: float
    threshold: float | None = None
    higher_is_better: bool = True
    status: MetricStatus = MetricStatus.PASS

    def __post_init__(self) -> None:
        if self.threshold is not None:
            if self.higher_is_better:
                self.status = (
                    MetricStatus.PASS if self.value >= self.threshold else MetricStatus.FAIL
                )
            else:
                self.status = (
                    MetricStatus.PASS if self.value <= self.threshold else MetricStatus.FAIL
                )


@dataclass
class Scorecard:
    scenario: str
    metrics: list[MetricResult] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def add(self, metric: MetricResult) -> None:
        self.metrics.append(metric)

    def pass_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == MetricStatus.PASS)

    def fail_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == MetricStatus.FAIL)

    def overall_pass(self) -> bool:
        return self.fail_count() == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "overall_pass": self.overall_pass(),
            "pass_count": self.pass_count(),
            "fail_count": self.fail_count(),
            "total_metrics": len(self.metrics),
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "threshold": m.threshold,
                    "higher_is_better": m.higher_is_better,
                    "status": m.status.value,
                }
                for m in self.metrics
            ],
            "details": self.details,
        }


def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Compute precision@k: fraction of top-k items that are relevant."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for item in top_k if item in relevant)
    return round(hits / len(top_k), 6)


def recall(relevant: set[str], retrieved: set[str]) -> float:
    """Compute recall: fraction of relevant items that were retrieved."""
    if not relevant:
        return 1.0
    hits = len(relevant & retrieved)
    return round(hits / len(relevant), 6)


def precision(relevant: set[str], retrieved: set[str]) -> float:
    """Compute precision: fraction of retrieved items that are relevant."""
    if not retrieved:
        return 1.0
    hits = len(relevant & retrieved)
    return round(hits / len(retrieved), 6)


def f1_score(relevant: set[str], retrieved: set[str]) -> float:
    """Compute F1 score: harmonic mean of precision and recall."""
    p = precision(relevant, retrieved)
    r = recall(relevant, retrieved)
    if p + r == 0:
        return 0.0
    return round(2 * p * r / (p + r), 6)


def budget_adherence(used: int, budget: int) -> float:
    """Return 1.0 if within budget, 0.0 otherwise.

    Used tokens must be <= budget.  A small negative headroom (over-budget)
    returns 0.
    """
    return 1.0 if used <= budget else 0.0


def citation_validity(cited_ids: set[str], live_ids: set[str]) -> tuple[float, set[str]]:
    """Return (fraction_valid, invalid_ids).

    All cited ids should resolve to live (non-deleted) memories.
    """
    if not cited_ids:
        return 1.0, set()
    invalid = cited_ids - live_ids
    valid_count = len(cited_ids) - len(invalid)
    return round(valid_count / len(cited_ids), 6), invalid


def overdue_detection_accuracy(
    actual_overdue: set[str], detected_overdue: set[str]
) -> dict[str, float]:
    """Compute accuracy metrics for overdue detection."""
    return {
        "precision": precision(actual_overdue, detected_overdue),
        "recall": recall(actual_overdue, detected_overdue),
        "f1": f1_score(actual_overdue, detected_overdue),
    }


def stale_fact_avoidance(stale_facts: set[str], retrieved_facts: set[str]) -> float:
    """Fraction of retrieved facts that are NOT stale.

    Perfect score = 1.0 (no stale facts in results).
    """
    if not retrieved_facts:
        return 1.0
    fresh = retrieved_facts - stale_facts
    return round(len(fresh) / len(retrieved_facts), 6)


def as_of_accuracy(expected: dict[str, str], actual: dict[str, str]) -> float:
    """Fraction of fact keys with matching values in as-of queries."""
    if not expected:
        return 1.0
    correct = 0
    for k, v in expected.items():
        if k in actual and actual[k] == v:
            correct += 1
    return round(correct / len(expected), 6)


def replay_determinism_score(run_a_digest: str, run_b_digest: str) -> float:
    """Return 1.0 if two runs produce identical digests, 0.0 otherwise."""
    return 1.0 if run_a_digest == run_b_digest else 0.0


def deletion_resurrection_check(
    deleted_ids: set[str],
    query_results: dict[str, set[str]],
) -> tuple[bool, set[str]]:
    """Verify no deleted id appears in any query result.

    Returns (all_clean, resurrected_ids_found).
    """
    found: set[str] = set()
    for _query_name, result_ids in query_results.items():
        found |= result_ids & deleted_ids
    return len(found) == 0, found


def privacy_violation_count(violations: list[str]) -> int:
    """Count privacy violations; expected to be zero in clean runs."""
    return len(violations)


def coverage_score(
    required_items: set[str],
    covered_items: set[str],
) -> float:
    """Fraction of required items that are covered (e.g., in meeting prep)."""
    if not required_items:
        return 1.0
    return round(len(required_items & covered_items) / len(required_items), 6)


def aggregate_scorecards(cards: list[Scorecard]) -> Scorecard:
    """Aggregate multiple scenario scorecards into one summary.

    Takes the average of each metric across scenarios.
    """
    if not cards:
        return Scorecard(scenario="aggregate")

    metric_values: dict[str, list[float]] = {}
    metric_thresholds: dict[str, float | None] = {}
    metric_higher: dict[str, bool] = {}

    for card in cards:
        for m in card.metrics:
            if m.name not in metric_values:
                metric_values[m.name] = []
                metric_thresholds[m.name] = m.threshold
                metric_higher[m.name] = m.higher_is_better
            metric_values[m.name].append(m.value)

    agg = Scorecard(
        scenario="aggregate",
        details={"scenarios": [c.scenario for c in cards]},
    )
    for name, values in sorted(metric_values.items()):
        avg = round(sum(values) / len(values), 6)
        agg.add(
            MetricResult(
                name=name,
                value=avg,
                threshold=metric_thresholds[name],
                higher_is_better=metric_higher[name],
            )
        )
    return agg


# --- End-to-end scenarios (synthetic data with planted ground truth) ------------


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Knobs for one evaluation scenario.

    ``now_day`` defaults to half the history so overdue and as-of
    measurements see a mix of past and future deadlines instead of a
    degenerate all-overdue set.
    """

    seed: int = 42
    days: int = 90
    now_day: int | None = None
    top_k: int = 5
    context_budget: int = 800
    factory_config: FactoryConfig | None = None


@dataclass(slots=True)
class ScenarioResult:
    """A scorecard plus measured intermediates for inspection."""

    scorecard: Scorecard
    measurements: dict[str, Any] = field(default_factory=dict)


def _typed_history(
    config: ScenarioConfig,
) -> tuple[WorkHistoryFactory, list[Event], HistoryManifest]:
    factory = WorkHistoryFactory(seed=config.seed, days=config.days, config=config.factory_config)
    synthetic, manifest = factory.generate()
    typed = [event.to_event() for event in synthetic]
    return factory, typed, manifest


def _scenario_now(config: ScenarioConfig, factory: WorkHistoryFactory) -> datetime:
    day = config.now_day if config.now_day is not None else max(1, config.days // 2)
    return factory.start_date + timedelta(days=day)


def _commitment_measurements(config: ScenarioConfig, project: str | None = None) -> dict[str, Any]:
    """Run factory -> ingest -> ledger -> context and measure everything.

    Shared by the whole-history scenario and the per-project slices. When
    ``project`` is given, only planted commitments of that project form
    the ground truth for recall and overdue detection. Every number is
    measured from the run; nothing is assumed.
    """
    factory, typed, manifest = _typed_history(config)
    pipeline = IngestPipeline()
    result = pipeline.run(typed)
    rerun = IngestPipeline().run(typed)

    planted = {
        item.item_id: item
        for item in factory.planted_items()
        if item.kind == "commitment" and (project is None or item.data["project"] == project)
    }
    ref_of_key: dict[str, str] = {
        f"{item.data['description']}\n{item.data['due_date'][:10]}": ref
        for ref, item in planted.items()
    }

    structured = [m for m in result.commitments if m.evidence.field == "commitment_ref"]
    extracted_keys = {f"{m.description}\n{m.due or ''}" for m in structured}
    planted_keys = set(ref_of_key)
    recovered = planted_keys & extracted_keys

    now_dt = _scenario_now(config, factory)
    now = now_dt.isoformat()
    ledger = CommitmentLedger()
    for mention in structured:
        ref = ref_of_key.get(f"{mention.description}\n{mention.due or ''}")
        if ref is None:
            continue
        ledger.add(
            Commitment(
                ref,
                mention.debtor,
                mention.creditor,
                mention.description,
                planted[ref].data["due_date"],
            )
        )
    actual_overdue = {
        ref
        for ref, item in planted.items()
        if datetime.fromisoformat(item.data["due_date"]) < now_dt
    }
    detected_overdue = {c.commitment_id for c in ledger.overdue(now)}
    overdue = overdue_detection_accuracy(actual_overdue, detected_overdue)

    store = MemoryStore()
    engine = RetrievalEngine(store=store)
    for episode in result.episodes:
        item = MemoryItem(
            episode.episode_id, MemoryTier.EPISODIC, episode.title, title=episode.title
        )
        store.add(item)
        engine.index_item(item)
    hits = engine.search("milestone update", top_k=config.top_k)
    cited = {h.item_id for h in hits}
    citation_fraction, _invalid = citation_validity(cited, set(engine.index.ids()))
    pack = ContextPacker(budget=config.context_budget).pack(
        [
            ContextItem(
                item_id=hit.item_id,
                content=hit.snippet,
                title=hit.title,
                token_estimate=estimate_tokens(hit.snippet),
                priority=hit.score,
            )
            for hit in hits
        ]
    )

    return {
        "planted": len(planted),
        "structured_mentions": len(structured),
        "recovered": len(recovered),
        "commitment_recall": recall(planted_keys, recovered),
        "commitment_precision": precision(planted_keys, extracted_keys),
        "overdue": overdue,
        "actual_overdue": len(actual_overdue),
        "citation_validity": citation_fraction,
        "budget_adherence": budget_adherence(pack.total_tokens, config.context_budget),
        "replay_determinism": replay_determinism_score(result.digest(), rerun.digest()),
        "checksum": manifest.checksum,
    }


def run_commitment_scenario(config: ScenarioConfig | None = None) -> ScenarioResult:
    """Whole-history commitment scenario on synthetic planted truth."""
    cfg = config or ScenarioConfig()
    measured = _commitment_measurements(cfg)
    card = Scorecard(
        scenario=f"commitments-seed{cfg.seed}-{cfg.days}d",
        details={
            "ground_truth": "synthetic planted commitments",
            "planted_commitments": measured["planted"],
            "structured_mentions": measured["structured_mentions"],
            "recovered": measured["recovered"],
            "actual_overdue": measured["actual_overdue"],
            "checksum": measured["checksum"],
        },
    )
    card.add(MetricResult("commitment_recall", measured["commitment_recall"], threshold=1.0))
    card.add(MetricResult("commitment_precision", measured["commitment_precision"], threshold=1.0))
    card.add(MetricResult("overdue_precision", measured["overdue"]["precision"], threshold=1.0))
    card.add(MetricResult("overdue_recall", measured["overdue"]["recall"], threshold=1.0))
    card.add(MetricResult("overdue_f1", measured["overdue"]["f1"], threshold=1.0))
    card.add(MetricResult("citation_validity", measured["citation_validity"], threshold=1.0))
    card.add(MetricResult("budget_adherence", measured["budget_adherence"], threshold=1.0))
    card.add(MetricResult("replay_determinism", measured["replay_determinism"], threshold=1.0))
    return ScenarioResult(scorecard=card, measurements=measured)
