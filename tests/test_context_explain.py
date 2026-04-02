"""Packing explanations must reconcile with the pack itself."""

from mnemofold.context import ContextItem, ContextPacker, explain_pack


def item(item_id: str, tokens: int, priority: float) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        content="x" * max(tokens, 1) * 4,
        title=item_id,
        token_estimate=tokens,
        priority=priority,
    )


class TestExplainPack:
    def test_everything_selected_under_large_budget(self):
        items = [item("a", 10, 1.0), item("b", 20, 0.5)]
        report = explain_pack(ContextPacker(budget=100), items)
        assert [r["reason"] for r in report["rows"]] == ["selected", "selected"]
        assert report["used"] == 30
        assert report["headroom"] == 70

    def test_ineligible_candidates(self):
        items = [item("zero", 0, 5.0), item("huge", 500, 5.0), item("ok", 10, 1.0)]
        report = explain_pack(ContextPacker(budget=100), items)
        reasons = {r["item_id"]: r["reason"] for r in report["rows"]}
        assert reasons["zero"] == "ineligible"
        assert reasons["huge"] == "ineligible"
        assert reasons["ok"] == "selected"

    def test_outcompeted_is_not_about_density(self):
        # C is denser than B, but A+B (value 5.0) beats every subset with C
        items = [item("A", 10, 3.0), item("B", 10, 2.0), item("C", 15, 4.0)]
        report = explain_pack(ContextPacker(budget=20), items)
        reasons = {r["item_id"]: r["reason"] for r in report["rows"]}
        assert reasons == {"A": "selected", "B": "selected", "C": "outcompeted"}
        densities = {r["item_id"]: r["value_density"] for r in report["rows"]}
        assert densities["C"] > densities["B"]

    def test_rows_follow_input_order(self):
        items = [item(i, 10, 1.0) for i in ("z", "m", "a")]
        report = explain_pack(ContextPacker(budget=100), items)
        assert [r["item_id"] for r in report["rows"]] == ["z", "m", "a"]

    def test_totals_reconcile(self):
        items = [item("a", 30, 3.0), item("b", 40, 2.0), item("c", 50, 4.0)]
        packer = ContextPacker(budget=70)
        report = explain_pack(packer, items)
        pack = packer.pack(items)
        assert report["used"] == pack.total_tokens
        assert report["budget"] == 70
        assert report["used"] <= report["budget"]
        assert report["headroom"] == report["budget"] - report["used"]
        selected_tokens = sum(r["tokens"] for r in report["rows"] if r["selected"])
        assert selected_tokens == report["used"]

    def test_deterministic(self):
        items = [item("a", 10, 1.0), item("b", 15, 2.0)]
        assert explain_pack(ContextPacker(budget=20), items) == (
            explain_pack(ContextPacker(budget=20), items)
        )
