from datetime import UTC, datetime, timedelta

import pytest

from mnemofold.triggers import (
    FiredTrigger,
    QuietHours,
    TriggerEngine,
    TriggerKind,
    TriggerRule,
    TriggerSeverity,
    fired_from_dict,
    fired_to_dict,
    read_trigger_log,
    write_trigger_log,
)

NOW = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)


def test_quiet_hours_same_day():
    qh = QuietHours(start_hour=22, end_hour=23)
    assert qh.is_quiet(datetime(2026, 1, 1, 22, 30, tzinfo=UTC))
    assert not qh.is_quiet(datetime(2026, 1, 1, 10, 0, tzinfo=UTC))


def test_quiet_hours_overnight():
    qh = QuietHours(start_hour=22, end_hour=7)
    assert qh.is_quiet(datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    assert qh.is_quiet(datetime(2026, 1, 1, 3, 0, tzinfo=UTC))
    assert not qh.is_quiet(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    assert not qh.is_quiet(datetime(2026, 1, 1, 7, 30, tzinfo=UTC))


def test_quiet_hours_suppresses_low_severity():
    qh = QuietHours(start_hour=22, end_hour=7, suppress_severity_below=TriggerSeverity.CRITICAL)
    midnight = datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    assert qh.suppresses(TriggerSeverity.INFO, midnight)
    assert qh.suppresses(TriggerSeverity.WARNING, midnight)
    assert not qh.suppresses(TriggerSeverity.CRITICAL, midnight)


def test_quiet_hours_does_not_suppress_during_day():
    qh = QuietHours(start_hour=22, end_hour=7, suppress_severity_below=TriggerSeverity.CRITICAL)
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert not qh.suppresses(TriggerSeverity.INFO, noon)


def test_trigger_fires_when_due():
    engine = TriggerEngine()
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.DEADLINE_REMINDER,
            target_id="commitment-1",
            fire_at=NOW,
            message="Deadline is near",
        )
    )
    fired = engine.tick(NOW)
    assert len(fired) == 1
    assert fired[0].rule_id == "r1"
    assert not fired[0].suppressed
    assert fired[0].message == "Deadline is near"


def test_trigger_does_not_fire_before_time():
    engine = TriggerEngine()
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.DEADLINE_REMINDER,
            target_id="c1",
            fire_at=NOW + timedelta(hours=1),
        )
    )
    assert engine.tick(NOW) == []


def test_cooldown_prevents_refire():
    engine = TriggerEngine()
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.STALE_THREAD,
            target_id="t1",
            fire_at=NOW,
            cooldown=timedelta(hours=1),
        )
    )
    f1 = engine.tick(NOW)
    assert len(f1) == 1
    # Tick 30 min later — still in cooldown
    f2 = engine.tick(NOW + timedelta(minutes=30))
    assert len(f2) == 0
    # Tick after cooldown — fires again
    f3 = engine.tick(NOW + timedelta(hours=2))
    assert len(f3) == 1


def test_dedupe_same_target_and_kind():
    engine = TriggerEngine()
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.OVERDUE_ALERT,
            target_id="c1",
            fire_at=NOW,
            dedupe_window=timedelta(minutes=30),
        )
    )
    engine.add_rule(
        TriggerRule(
            rule_id="r2",
            kind=TriggerKind.OVERDUE_ALERT,
            target_id="c1",
            fire_at=NOW + timedelta(minutes=5),
            dedupe_window=timedelta(minutes=30),
        )
    )
    fired = engine.tick(NOW + timedelta(minutes=10))
    # Only one should fire because of dedupe window
    assert len(fired) == 1


def test_quiet_hours_suppression():
    qh = QuietHours(start_hour=22, end_hour=7, suppress_severity_below=TriggerSeverity.CRITICAL)
    engine = TriggerEngine(quiet_hours=qh)
    midnight = datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    engine.add_rule(
        TriggerRule(
            rule_id="info_r",
            kind=TriggerKind.FOLLOW_UP,
            target_id="t1",
            fire_at=midnight,
            severity=TriggerSeverity.INFO,
        )
    )
    engine.add_rule(
        TriggerRule(
            rule_id="crit_r",
            kind=TriggerKind.OVERDUE_ALERT,
            target_id="c1",
            fire_at=midnight,
            severity=TriggerSeverity.CRITICAL,
        )
    )
    fired = engine.tick(midnight)
    assert len(fired) == 2
    info = next(f for f in fired if f.rule_id == "info_r")
    crit = next(f for f in fired if f.rule_id == "crit_r")
    assert info.suppressed is True
    assert info.suppress_reason == "quiet_hours"
    assert crit.suppressed is False


def test_report_coverage_suppression():
    covered_targets = {"c1": {TriggerKind.DEADLINE_REMINDER}}

    def covered(target_id, kind):
        return kind in covered_targets.get(target_id, set())

    engine = TriggerEngine(is_covered_by_report=covered)
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.DEADLINE_REMINDER,
            target_id="c1",
            fire_at=NOW,
        )
    )
    engine.add_rule(
        TriggerRule(
            rule_id="r2",
            kind=TriggerKind.DEADLINE_REMINDER,
            target_id="c2",
            fire_at=NOW,
        )
    )
    fired = engine.tick(NOW)
    assert len(fired) == 2
    r1 = next(f for f in fired if f.rule_id == "r1")
    r2 = next(f for f in fired if f.rule_id == "r2")
    assert r1.suppressed
    assert r1.suppress_reason == "covered_by_report"
    assert not r2.suppressed


def test_active_triggers_excludes_suppressed():
    engine = TriggerEngine()
    engine.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.FOLLOW_UP,
            target_id="t1",
            fire_at=NOW,
            severity=TriggerSeverity.WARNING,
        )
    )
    qh = QuietHours(start_hour=0, end_hour=23, suppress_severity_below=TriggerSeverity.CRITICAL)
    engine2 = TriggerEngine(quiet_hours=qh)
    engine2.add_rule(
        TriggerRule(
            rule_id="r1",
            kind=TriggerKind.FOLLOW_UP,
            target_id="t1",
            fire_at=NOW,
            severity=TriggerSeverity.WARNING,
        )
    )
    assert len(engine.active_triggers()) == 0
    engine.tick(NOW)
    assert len(engine.active_triggers()) == 1
    engine2.tick(NOW)
    assert len(engine2.active_triggers()) == 0


def test_counts_by_kind():
    engine = TriggerEngine()
    engine.add_rule(TriggerRule("r1", TriggerKind.OVERDUE_ALERT, "c1", NOW))
    engine.add_rule(TriggerRule("r2", TriggerKind.STALE_THREAD, "t1", NOW))
    engine.add_rule(TriggerRule("r3", TriggerKind.OVERDUE_ALERT, "c2", NOW))
    engine.tick(NOW)
    counts = engine.counts_by_kind()
    assert counts["overdue_alert"] == 2
    assert counts["stale_thread"] == 1


def _fired(rule_id="r1", kind=TriggerKind.OVERDUE_ALERT, suppressed=False) -> FiredTrigger:
    return FiredTrigger(
        rule_id=rule_id,
        kind=kind,
        target_id="c1",
        fired_at=NOW,
        severity=TriggerSeverity.WARNING,
        message="overdue",
        suppressed=suppressed,
        suppress_reason="quiet_hours" if suppressed else "",
    )


class TestTriggerLogPersistence:
    def test_dict_roundtrip(self):
        trigger = _fired()
        assert fired_from_dict(fired_to_dict(trigger)) == trigger

    def test_dict_roundtrip_suppressed(self):
        trigger = _fired(suppressed=True)
        restored = fired_from_dict(fired_to_dict(trigger))
        assert restored.suppressed is True
        assert restored.suppress_reason == "quiet_hours"

    def test_write_read_roundtrip(self, tmp_path):
        path = tmp_path / "triggers.jsonl"
        triggers = [_fired("r1"), _fired("r2", kind=TriggerKind.STALE_THREAD)]
        write_trigger_log(path, triggers)
        assert read_trigger_log(path) == triggers

    def test_log_is_deterministic(self, tmp_path):
        a = tmp_path / "a.jsonl"
        b = tmp_path / "b.jsonl"
        triggers = [_fired("r1"), _fired("r2")]
        write_trigger_log(a, triggers)
        write_trigger_log(b, triggers)
        assert a.read_text() == b.read_text()

    def test_tampering_is_detected(self, tmp_path):
        path = tmp_path / "triggers.jsonl"
        write_trigger_log(path, [_fired("r1"), _fired("r2")])
        lines = path.read_text().splitlines()
        lines[0] = lines[0].replace("r1", "r9")
        path.write_text("\n".join(lines) + "\n")
        with pytest.raises(ValueError, match="corrupt"):
            read_trigger_log(path)

    def test_empty_log_reads_empty(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        write_trigger_log(path, [])
        assert read_trigger_log(path) == []

    def test_suppressed_flag_survives_log(self, tmp_path):
        path = tmp_path / "triggers.jsonl"
        write_trigger_log(path, [_fired("r1", suppressed=True)])
        restored = read_trigger_log(path)
        assert restored[0].suppressed is True


def _rule(rule_id, fire_at, *, kind=TriggerKind.FOLLOW_UP, target="t1", **kwargs) -> TriggerRule:
    return TriggerRule(rule_id=rule_id, kind=kind, target_id=target, fire_at=fire_at, **kwargs)


class TestTriggerEngineSweep:
    def test_fires_exactly_at_fire_at(self):
        engine = TriggerEngine()
        engine.add_rule(_rule("r1", NOW))
        assert engine.tick(NOW - timedelta(seconds=1)) == []
        fired = engine.tick(NOW)
        assert len(fired) == 1
        assert fired[0].rule_id == "r1"

    def test_cooldown_blocks_then_allows(self):
        engine = TriggerEngine()
        engine.add_rule(_rule("r1", NOW, cooldown=timedelta(hours=1)))
        assert len(engine.tick(NOW)) == 1
        assert engine.tick(NOW + timedelta(minutes=30)) == []
        assert len(engine.tick(NOW + timedelta(hours=1))) == 1

    def test_dedupe_window_suppresses_second_rule_on_same_target(self):
        engine = TriggerEngine()
        engine.add_rule(
            _rule(
                "r1",
                NOW,
                kind=TriggerKind.STALE_THREAD,
                target="t1",
                dedupe_window=timedelta(hours=2),
            )
        )
        engine.add_rule(
            _rule(
                "r2",
                NOW,
                kind=TriggerKind.STALE_THREAD,
                target="t1",
                dedupe_window=timedelta(hours=2),
            )
        )
        fired = engine.tick(NOW)
        assert [f.rule_id for f in fired] == ["r1"]
        # within the window everything on (t1, stale_thread) stays quiet
        assert engine.tick(NOW + timedelta(minutes=30)) == []
        # after the window the first rule in order fires again and re-arms
        # the shared (target, kind) key, so r2 stays suppressed: exactly
        # one trigger per target per window
        later = engine.tick(NOW + timedelta(hours=3))
        assert [f.rule_id for f in later] == ["r1"]
        # a different target is untouched by t1's dedupe state
        engine.add_rule(_rule("r3", NOW, kind=TriggerKind.STALE_THREAD, target="t2"))
        other = engine.tick(NOW + timedelta(hours=3, minutes=1))
        assert [f.rule_id for f in other] == ["r3"]

    def test_quiet_hours_suppress_low_severity_only(self):
        quiet = QuietHours(
            start_hour=22, end_hour=7, suppress_severity_below=TriggerSeverity.CRITICAL
        )
        engine = TriggerEngine(quiet_hours=quiet)
        engine.add_rule(
            _rule("info", datetime(2026, 3, 15, 23, 0, tzinfo=UTC), severity=TriggerSeverity.INFO)
        )
        engine.add_rule(
            _rule(
                "crit", datetime(2026, 3, 15, 23, 0, tzinfo=UTC), severity=TriggerSeverity.CRITICAL
            )
        )
        fired = engine.tick(datetime(2026, 3, 15, 23, 30, tzinfo=UTC))
        by_id = {f.rule_id: f for f in fired}
        assert by_id["info"].suppressed is True
        assert by_id["info"].suppress_reason == "quiet_hours"
        assert by_id["crit"].suppressed is False

    def test_report_coverage_suppresses(self):
        engine = TriggerEngine(is_covered_by_report=lambda tid, kind: tid == "covered")
        engine.add_rule(_rule("r1", NOW, target="covered"))
        engine.add_rule(_rule("r2", NOW, target="other"))
        fired = engine.tick(NOW)
        by_id = {f.rule_id: f for f in fired}
        assert by_id["r1"].suppressed is True
        assert by_id["r1"].suppress_reason == "covered_by_report"
        assert by_id["r2"].suppressed is False

    def test_active_triggers_exclude_suppressed(self):
        quiet = QuietHours(start_hour=0, end_hour=23)
        engine = TriggerEngine(quiet_hours=quiet)
        engine.add_rule(_rule("r1", NOW, severity=TriggerSeverity.INFO))
        engine.tick(NOW)
        assert engine.active_triggers() == []
        assert len(engine.fired()) == 1

    def test_counts_by_kind(self):
        engine = TriggerEngine()
        engine.add_rule(_rule("r1", NOW, kind=TriggerKind.STALE_THREAD, target="a"))
        engine.add_rule(_rule("r2", NOW, kind=TriggerKind.STALE_THREAD, target="b"))
        engine.add_rule(_rule("r3", NOW, kind=TriggerKind.DAILY_SUMMARY, target="c"))
        engine.tick(NOW)
        assert engine.counts_by_kind() == {"stale_thread": 2, "daily_summary": 1}

    def test_fire_sequence_is_deterministic(self):
        def run() -> list[str]:
            engine = TriggerEngine()
            engine.add_rule(_rule("r1", NOW, cooldown=timedelta(hours=1)))
            log: list[str] = []
            for hours in range(4):
                for fired in engine.tick(NOW + timedelta(minutes=30 * hours)):
                    log.append(fired.rule_id)
            return log

        assert run() == run()
