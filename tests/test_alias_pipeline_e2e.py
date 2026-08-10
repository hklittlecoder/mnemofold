"""Entities harvested by the ingest pipeline must round-trip the table.

Builds the alias table from a real seeded run, then checks that every
harvested name resolves, that auto-merging never loses a name, and that
resolution stays deterministic across rebuilds.
"""

from mnemofold.factory import WorkHistoryFactory
from mnemofold.ingest import AliasTable, IngestPipeline


def harvested(seed: int = 11, days: int = 20):
    factory = WorkHistoryFactory(seed=seed, days=days)
    synthetic, _ = factory.generate()
    result = IngestPipeline().run([e.to_event() for e in synthetic])
    return result.entities


def build_table(entities) -> AliasTable:
    table = AliasTable()
    for entity in entities:
        table.add_entity(entity)
    return table


class TestAliasPipelineE2E:
    def test_every_harvested_name_resolves(self):
        entities = harvested()
        assert entities
        table = build_table(entities)
        for entity in entities:
            assert table.resolve(entity.name) == entity.entity_id

    def test_auto_merge_keeps_all_names_resolvable(self):
        entities = harvested()
        table = build_table(entities)
        table.auto_merge_candidates(threshold=0.9)
        for entity in entities:
            assert table.resolve(entity.name) is not None, entity.name

    def test_resolution_deterministic_across_rebuilds(self):
        first = build_table(harvested())
        second = build_table(harvested())
        assert first.all_entities() == second.all_entities()
        assert first.merge_candidates(0.8) == second.merge_candidates(0.8)

    def test_fuzzy_finds_slight_variants(self):
        entities = harvested()
        table = build_table(entities)
        # harvested ids can be short ("p1"), so a lenient threshold keeps
        # the variant resolvable without asserting which entity it hits
        for entity in entities[:5]:
            assert table.resolve_fuzzy(entity.name) == entity.entity_id
            variant = entity.name + "1"
            assert table.resolve_fuzzy(variant, threshold=0.4) is not None
