"""Golden bytes for ContextPack.to_markdown.

The fixture is reproduced from the exact pack built in ``make_pack``;
any change to headings, ordering, priority formatting or the source
citation line fails here deliberately.
"""

from pathlib import Path

from mnemofold.context import ContextItem, ContextPack, PackingProfile

FIXTURE = Path(__file__).parent / "fixtures" / "context_pack_markdown_golden.md"


def make_pack() -> ContextPack:
    return ContextPack(
        items=[
            ContextItem(
                item_id="m1",
                content="Release checklist draft",
                title="Release checklist",
                token_estimate=12,
                priority=0.75,
                category="commitment",
            ),
            ContextItem(
                item_id="m2",
                content="Budget numbers",
                title="",
                token_estimate=8,
                priority=0.4,
                category="finance",
            ),
        ],
        total_tokens=20,
        budget=100,
        profile=PackingProfile.MEETING_PREP,
    )


class TestPackMarkdownGolden:
    def test_matches_golden_bytes(self):
        assert make_pack().to_markdown() == FIXTURE.read_text(encoding="utf-8")

    def test_untitled_items_fall_back_to_id(self):
        md = make_pack().to_markdown()
        assert "## 2. m2 [8 tokens]" in md

    def test_priority_formatted_to_three_decimals(self):
        assert "*Category: commitment | Priority: 0.750*" in make_pack().to_markdown()

    def test_regeneration_is_stable(self):
        assert make_pack().to_markdown() == make_pack().to_markdown()
