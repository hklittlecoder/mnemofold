"""The demo command must run the full offline pipeline end to end.

Every stage the demo claims to run has to leave a measurable trace in
its output, the context pack has to respect its budget, and identical
seeds must produce byte-identical transcripts.
"""

from mnemofold.cli import main

STAGE_MARKERS = [
    "=== mnemofold demo",
    "Event type breakdown:",
    "Ingested",
    "commitments extracted:",
    "Fold:",
    "Recall:",
    "Context pack:",
    "Meeting prep:",
    "Top triaged mail items:",
    "batch plan:",
    "Standup for",
    "Measured on synthetic history",
    "commitment recall:",
    "overdue F1:",
    "Scorecard pass: True",
    "=== Demo complete ===",
]


def run_demo(capsys, seed: int, days: int) -> str:
    rc = main(["demo", "--seed", str(seed), "--days", str(days)])
    out = capsys.readouterr().out
    assert rc == 0
    return out


class TestDemoPipeline:
    def test_all_stages_appear(self, capsys):
        out = run_demo(capsys, 42, 10)
        for marker in STAGE_MARKERS:
            assert marker in out, marker

    def test_context_pack_respects_budget(self, capsys):
        out = run_demo(capsys, 42, 10)
        line = next(ln for ln in out.splitlines() if ln.startswith("Context pack:"))
        used = int(line.split(":")[1].split("/")[0].strip())
        budget = int(line.split("/")[1].split()[0])
        assert budget == 400
        assert used <= budget

    def test_demo_is_deterministic(self, capsys):
        first = run_demo(capsys, 5, 7)
        second = run_demo(capsys, 5, 7)
        assert first == second
