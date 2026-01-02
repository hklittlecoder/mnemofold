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
from mnemofold.deletion import DeletionReason
from mnemofold.events import Event
from mnemofold.factory import FactoryConfig, HistoryManifest, WorkHistoryFactory
from mnemofold.ingest import CommitmentExtractor, IngestPipeline
from mnemofold.ledger import Commitment, CommitmentLedger
from mnemofold.memory import MemoryItem, MemoryStore, MemoryTier
from mnemofold.privacy import RedactionVault, detect_pii
from mnemofold.retrieval import RetrievalEngine, build_deletion_engine, forget
from mnemofold.temporal import IntervalFact, TemporalStore
from mnemofold.triage import TriageItem, TriageScorer


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


def brier_score(probabilities: list[float], outcomes: list[bool]) -> float:
    """Mean squared error between predicted probabilities and 0/1 outcomes.

    Lower is better; 0.0 is perfectly calibrated. Probabilities are
    clamped to [0, 1]. Empty inputs give 0.0. This is the standard Brier
    score, used here to check whether triage/confidence scores behave like
    probabilities against planted labels.
    """
    if not probabilities:
        return 0.0
    total = 0.0
    for p, outcome in zip(probabilities, outcomes, strict=False):
        clamped = min(1.0, max(0.0, p))
        total += (clamped - (1.0 if outcome else 0.0)) ** 2
    return round(total / len(probabilities), 6)


@dataclass(slots=True)
class CalibrationBin:
    """One equal-width calibration bucket: predicted vs observed rate."""

    lower: float
    upper: float
    count: int
    mean_predicted: float
    observed_rate: float


def calibration_report(
    probabilities: list[float], outcomes: list[bool], bins: int = 10
) -> list[CalibrationBin]:
    """Bucket predictions into equal-width bins over [0, 1].

    For each non-empty bin, reports the mean predicted probability and
    the observed positive rate; a well-calibrated scorer has the two
    tracking each other along the diagonal. Empty bins are omitted.
    """
    if bins <= 0:
        raise ValueError("bins must be positive")
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for p, outcome in zip(probabilities, outcomes, strict=False):
        clamped = min(1.0, max(0.0, p))
        index = min(bins - 1, int(clamped * bins))
        buckets[index].append((clamped, 1.0 if outcome else 0.0))
    report: list[CalibrationBin] = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_predicted = sum(pred for pred, _ in bucket) / len(bucket)
        observed = sum(obs for _, obs in bucket) / len(bucket)
        report.append(
            CalibrationBin(
                lower=round(i / bins, 6),
                upper=round((i + 1) / bins, 6),
                count=len(bucket),
                mean_predicted=round(mean_predicted, 6),
                observed_rate=round(observed, 6),
            )
        )
    return report


def expected_calibration_error(bins: list[CalibrationBin], total: int | None = None) -> float:
    """Expected Calibration Error (ECE) from a calibration report.

    Weighted average of ``|mean_predicted - observed_rate|`` across bins,
    where each bin's weight is its share of samples. When ``total`` is
    None it is derived from the bins themselves. Quantized to 6 decimals
    so scores are stable across runs. An empty report yields 0.0.
    """
    n = total if total is not None else sum(b.count for b in bins)
    if n <= 0:
        return 0.0
    ece = 0.0
    for b in bins:
        if b.count <= 0:
            continue
        ece += (b.count / n) * abs(b.mean_predicted - b.observed_rate)
    return round(ece, 6)


def compare_scorecards(baseline: Scorecard, candidate: Scorecard) -> dict[str, Any]:
    """Metric-level diff between two scorecards (drift report).

    Reports every metric whose value or pass/fail status changed, with
    baseline/candidate values and a quantized delta, plus metrics that
    exist on only one side. Empty ``changed`` and ``only_*`` lists mean
    the candidate reproduced the baseline exactly — the check CI runs
    when a golden scorecard is regenerated.
    """
    base = {m.name: m for m in baseline.metrics}
    cand = {m.name: m for m in candidate.metrics}
    changed: list[dict[str, Any]] = []
    for name in sorted(set(base) & set(cand)):
        b, c = base[name], cand[name]
        if b.value != c.value or b.status != c.status:
            changed.append(
                {
                    "metric": name,
                    "baseline": round(b.value, 6),
                    "candidate": round(c.value, 6),
                    "delta": round(c.value - b.value, 6),
                    "baseline_status": b.status.value,
                    "candidate_status": c.status.value,
                }
            )
    return {
        "baseline_scenario": baseline.scenario,
        "candidate_scenario": candidate.scenario,
        "changed": changed,
        "only_in_baseline": sorted(set(base) - set(cand)),
        "only_in_candidate": sorted(set(cand) - set(base)),
    }


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


def _commitment_measurements(
    config: ScenarioConfig,
    project: str | None = None,
    owners: set[str] | None = None,
) -> dict[str, Any]:
    """Run factory -> ingest -> ledger -> context and measure everything.

    Shared by the whole-history scenario and the per-project / per-role
    slices. When ``project`` is given, only planted commitments of that
    project form the ground truth; when ``owners`` is given, only
    commitments owed by those persona ids count. Every number is
    measured from the run; nothing is assumed.
    """
    factory, typed, manifest = _typed_history(config)
    pipeline = IngestPipeline()
    result = pipeline.run(typed)
    rerun = IngestPipeline().run(typed)

    planted = {
        item.item_id: item
        for item in factory.planted_items()
        if item.kind == "commitment"
        and (project is None or item.data["project"] == project)
        and (owners is None or item.data["owed_by"] in owners)
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


def run_triage_scenario(config: ScenarioConfig | None = None) -> ScenarioResult:
    """Inbox-triage precision measured against planted commitment mails.

    Commitment flags for the scorer are derived by running the commitment
    extractor over event text — never from the labels themselves, so the
    measurement is not circular. precision@k values are reported WITHOUT
    pass/fail thresholds: they are measurements on synthetic data, and
    this framework claims no real-inbox quality.
    """
    cfg = config or ScenarioConfig()
    factory, typed, manifest = _typed_history(cfg)
    extractor = CommitmentExtractor()
    planted_refs = {p.item_id for p in factory.planted_items() if p.kind == "commitment"}

    items: list[TriageItem] = []
    labels: dict[str, bool] = {}
    for event in typed:
        if event.event_type.value not in ("mail_received", "mail_sent", "chat_message"):
            continue
        content = event.content
        mentions = extractor.extract(event)
        due = next((m.due for m in mentions if m.due), None)
        items.append(
            TriageItem(
                item_id=event.event_id,
                title=str(content.get("subject", content.get("channel", ""))),
                sender=str(content.get("sender", content.get("persona_id", ""))),
                received_at=event.timestamp.isoformat(),
                content=str(content.get("body", content.get("text", ""))),
                mentions_commitment=bool(mentions),
                has_deadline=due is not None,
                deadline=f"{due}T00:00:00+00:00" if due else "",
            )
        )
        ref = content.get("commitment_ref")
        labels[event.event_id] = isinstance(ref, str) and ref in planted_refs

    now = _scenario_now(cfg, factory).isoformat()
    ranked = TriageScorer().batch_score(items, now)
    ranked_ids = [r.item_id for r in ranked]
    relevant = {item_id for item_id, flag in labels.items() if flag}
    k = max(1, len(relevant))

    card = Scorecard(
        scenario=f"triage-seed{cfg.seed}-{cfg.days}d",
        details={
            "ground_truth": "synthetic planted commitment mails",
            "inbox_items": len(items),
            "planted_mails": len(relevant),
            "checksum": manifest.checksum,
        },
    )
    p_at_1 = precision_at_k(relevant, ranked_ids, 1)
    p_at_k = precision_at_k(relevant, ranked_ids, k)
    card.add(MetricResult("triage_precision_at_1", p_at_1))
    card.add(MetricResult(f"triage_precision_at_{k}", p_at_k))
    return ScenarioResult(
        scorecard=card,
        measurements={
            "inbox_items": len(items),
            "planted_mails": len(relevant),
            "precision_at_1": p_at_1,
            "precision_at_k": p_at_k,
            "k": k,
        },
    )


def run_asof_scenario(config: ScenarioConfig | None = None) -> ScenarioResult:
    """As-of correctness against planted due-date contradictions.

    For every planted due-date change the original due is valid from the
    commitment mail until the change notice; the new due is valid from
    the notice onward. Probes before and after the boundary must return
    the value that was known at that instant. Degenerate windows (change
    not after the original) are skipped rather than guessed at.
    """
    cfg = config or ScenarioConfig()
    factory, typed, manifest = _typed_history(cfg)

    commitment_ts: dict[str, datetime] = {}
    contradiction_ts: dict[str, datetime] = {}
    for event in typed:
        ref = event.content.get("commitment_ref")
        if isinstance(ref, str) and str(event.content.get("subject", "")).startswith("Commitment:"):
            commitment_ts[ref] = event.timestamp
        cref = event.content.get("contradiction_ref")
        if isinstance(cref, str):
            contradiction_ts[cref] = event.timestamp

    store: TemporalStore[str] = TemporalStore()
    probes: list[tuple[str, str, str, str]] = []  # label, key, when, expected
    for planted_item in factory.planted_items():
        if planted_item.kind != "contradiction":
            continue
        if planted_item.data.get("change") != "due_date":
            continue
        ref = planted_item.data["target_commitment"]
        start = commitment_ts.get(ref)
        change = contradiction_ts.get(planted_item.item_id)
        if start is None or change is None or change <= start:
            continue
        key = f"commitment:{ref}:due"
        old_value = planted_item.data["old_value"][:10]
        new_value = planted_item.data["new_value"][:10]
        store.add(IntervalFact(key, old_value, start.isoformat(), change.isoformat()))
        store.add(IntervalFact(key, new_value, change.isoformat()))
        mid = start + (change - start) / 2
        probes.append((f"{key}@before", key, mid.isoformat(), old_value))
        probes.append((f"{key}@after", key, (change + timedelta(days=1)).isoformat(), new_value))

    expected = {label: value for label, _, _, value in probes}
    actual: dict[str, str] = {}
    for label, key, when, _ in probes:
        fact = store.as_of(key, when)
        actual[label] = fact.value if fact is not None else ""
    accuracy = as_of_accuracy(expected, actual)

    card = Scorecard(
        scenario=f"asof-seed{cfg.seed}-{cfg.days}d",
        details={
            "ground_truth": "synthetic planted due-date changes",
            "probes": len(probes),
            "checksum": manifest.checksum,
        },
    )
    card.add(MetricResult("as_of_accuracy", accuracy, threshold=1.0))
    return ScenarioResult(
        scorecard=card,
        measurements={"probes": len(probes), "accuracy": accuracy},
    )


def run_privacy_deletion_scenario(config: ScenarioConfig | None = None) -> ScenarioResult:
    """Privacy sealing and right-to-forget, measured end to end.

    Privacy leg: seal sampled event text through the reversible vault and
    count raw PII occurrences that survive sealing — the count must be
    zero. Deletion leg: forget one episode memory and verify it never
    resurfaces through search, index listing, or broad queries.
    """
    cfg = config or ScenarioConfig()
    factory, typed, manifest = _typed_history(cfg)
    now_dt = _scenario_now(cfg, factory)

    vault = RedactionVault(salt=f"eval-{cfg.seed}")
    violations: list[str] = []
    sampled = 0
    for event in typed:
        parts = [str(v) for _k, v in sorted(event.content.items()) if isinstance(v, str)]
        text = " ".join(parts)
        matches = detect_pii(text)
        if not matches:
            continue
        sampled += 1
        sealed = vault.seal(text)
        for match in matches:
            if match.value in sealed:
                violations.append(f"{event.event_id}:{match.kind.value}")
        if sampled >= 120:
            break

    result = IngestPipeline().run(typed)
    store = MemoryStore()
    engine = RetrievalEngine(store=store)
    for episode in result.episodes:
        item = MemoryItem(
            episode.episode_id, MemoryTier.EPISODIC, episode.title, title=episode.title
        )
        store.add(item)
        engine.index_item(item)
    ids = engine.index.ids()
    victim_id = ids[len(ids) // 2] if ids else ""
    victim = store.peek(victim_id) if victim_id else None
    deletion = build_deletion_engine(engine)
    deleted: set[str] = set()
    if victim is not None:
        report = forget(deletion, victim_id, DeletionReason.FORGET, now_dt)
        deleted = {entry.key for entry in report.deleted}
    query_results = {
        "title_search": {
            r.item_id for r in engine.search(victim.title if victim else "", top_k=25)
        },
        "broad_search": {
            r.item_id for r in engine.search("update milestone review plan", top_k=50)
        },
        "index_listing": set(engine.index.ids()),
    }
    clean, resurrected = deletion_resurrection_check(deleted, query_results)

    card = Scorecard(
        scenario=f"privacy-deletion-seed{cfg.seed}-{cfg.days}d",
        details={
            "pii_events_sampled": sampled,
            "deleted": sorted(deleted),
            "resurrected": sorted(resurrected),
            "checksum": manifest.checksum,
        },
    )
    card.add(
        MetricResult(
            "privacy_violations",
            float(len(violations)),
            threshold=0.0,
            higher_is_better=False,
        )
    )
    card.add(MetricResult("deletion_clean", 1.0 if clean else 0.0, threshold=1.0))
    return ScenarioResult(
        scorecard=card,
        measurements={
            "violations": violations,
            "sampled": sampled,
            "deleted": sorted(deleted),
            "clean": clean,
        },
    )


def run_commitment_slices(config: ScenarioConfig | None = None) -> list[ScenarioResult]:
    """Per-project commitment scorecards, in sorted project order.

    Slices reuse the whole-history measurement machinery with the ground
    truth restricted to one project, so slice numbers and the aggregate
    never drift apart methodologically.
    """
    cfg = config or ScenarioConfig()
    factory, _typed, _manifest = _typed_history(cfg)
    projects = sorted(
        {item.data["project"] for item in factory.planted_items() if item.kind == "commitment"}
    )
    results: list[ScenarioResult] = []
    for project in projects:
        measured = _commitment_measurements(cfg, project=project)
        card = Scorecard(
            scenario=f"commitments[{project}]-seed{cfg.seed}",
            details={
                "ground_truth": f"synthetic planted commitments ({project})",
                "planted_commitments": measured["planted"],
                "recovered": measured["recovered"],
                "actual_overdue": measured["actual_overdue"],
            },
        )
        card.add(
            MetricResult("slice_commitment_recall", measured["commitment_recall"], threshold=1.0)
        )
        card.add(MetricResult("slice_overdue_f1", measured["overdue"]["f1"], threshold=1.0))
        results.append(ScenarioResult(scorecard=card, measurements=measured))
    return results


def run_role_slices(config: ScenarioConfig | None = None) -> list[ScenarioResult]:
    """Per-role commitment scorecards, in sorted role order.

    Ground truth is restricted to the planted commitments owed by
    personas holding that role, reusing the whole-history measurement
    machinery so role slices and project slices stay methodologically
    identical. Roles that own no planted commitment are skipped rather
    than reported as empty slices.
    """
    cfg = config or ScenarioConfig()
    factory, _typed, _manifest = _typed_history(cfg)
    owners_by_role: dict[str, set[str]] = {}
    for persona in factory.personas:
        owners_by_role.setdefault(str(persona.role), set()).add(persona.person_id)
    planted_owners = {
        item.data["owed_by"] for item in factory.planted_items() if item.kind == "commitment"
    }
    results: list[ScenarioResult] = []
    for role in sorted(owners_by_role):
        owners = owners_by_role[role]
        if not owners & planted_owners:
            continue
        measured = _commitment_measurements(cfg, owners=owners)
        card = Scorecard(
            scenario=f"commitments[role:{role}]-seed{cfg.seed}",
            details={
                "ground_truth": f"synthetic planted commitments (role {role})",
                "planted_commitments": measured["planted"],
                "recovered": measured["recovered"],
                "actual_overdue": measured["actual_overdue"],
            },
        )
        card.add(
            MetricResult("role_commitment_recall", measured["commitment_recall"], threshold=1.0)
        )
        card.add(MetricResult("role_overdue_f1", measured["overdue"]["f1"], threshold=1.0))
        results.append(ScenarioResult(scorecard=card, measurements=measured))
    return results


@dataclass(slots=True)
class SuiteResult:
    """Every scenario card plus the aggregate summary."""

    cards: list[Scorecard] = field(default_factory=list)
    aggregate: Scorecard = field(default_factory=lambda: Scorecard(scenario="aggregate"))

    def overall_pass(self) -> bool:
        return all(card.overall_pass() for card in self.cards)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cards": [card.to_dict() for card in self.cards],
            "aggregate": self.aggregate.to_dict(),
            "overall_pass": self.overall_pass(),
        }


def run_suite(config: ScenarioConfig | None = None) -> SuiteResult:
    """Run every scenario once and aggregate (used by the CLI eval)."""
    cfg = config or ScenarioConfig()
    results = [
        run_commitment_scenario(cfg),
        run_triage_scenario(cfg),
        run_asof_scenario(cfg),
        run_privacy_deletion_scenario(cfg),
    ]
    cards = [result.scorecard for result in results]
    return SuiteResult(cards=cards, aggregate=aggregate_scorecards(cards))
