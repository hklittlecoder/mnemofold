"""Fold knobs flow from the CLI into merge and mining behavior."""

import json

from mnemofold.cli import main


def ingest(db, seed: int = 5, days: int = 10) -> None:
    assert main(["ingest", "--db", str(db), "--seed", str(seed), "--days", str(days)]) == 0


class TestFoldKnobs:
    def test_similarity_one_disables_merging(self, tmp_path, capsys):
        db_a, db_b = tmp_path / "a", tmp_path / "b"
        ingest(db_a)
        ingest(db_b)
        capsys.readouterr()
        main(["fold", "--db", str(db_a), "--json"])
        default_report = json.loads(capsys.readouterr().out)
        main(["fold", "--db", str(db_b), "--similarity", "1.01", "--json"])
        strict_report = json.loads(capsys.readouterr().out)
        # similarity > 1 can never be met: no merges regardless of content
        assert strict_report["merges"] == 0
        assert strict_report["items_after"] == strict_report["items_before"]
        assert default_report["items_before"] == strict_report["items_before"]

    def test_min_repeats_high_raises_mining_floor(self, tmp_path, capsys):
        db_a, db_b = tmp_path / "a", tmp_path / "b"
        ingest(db_a, seed=23, days=60)
        ingest(db_b, seed=23, days=60)
        capsys.readouterr()
        main(["fold", "--db", str(db_a), "--min-repeats", "3", "--json"])
        low = json.loads(capsys.readouterr().out)
        # a floor no tag group can reach: mining must come back empty
        main(["fold", "--db", str(db_b), "--min-repeats", "1000000000", "--json"])
        high = json.loads(capsys.readouterr().out)
        assert high["recurrence_proposals"] == 0
        assert low["recurrence_proposals"] >= high["recurrence_proposals"]

    def test_demo_mode_accepts_knobs(self, capsys):
        rc = main(["fold", "--seed", "5", "--days", "10", "--similarity", "0.9", "--json"])
        assert rc == 0
        assert "fold_id" in json.loads(capsys.readouterr().out)
