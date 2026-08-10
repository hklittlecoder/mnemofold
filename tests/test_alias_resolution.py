"""Fuzzy resolution and automatic candidate merging."""

from mnemofold.ingest import AliasTable, Entity


def entity(eid: str, name: str, *aliases: str) -> Entity:
    return Entity(entity_id=eid, entity_type="person", name=name, aliases=list(aliases))


def make_table() -> AliasTable:
    table = AliasTable()
    table.add_entity(entity("e1", "Ana Chen", "ana"))
    table.add_entity(entity("e2", "Bobby Li", "bob"))
    table.add_entity(entity("e3", "Zebra Corp"))
    return table


class TestResolveFuzzy:
    def test_exact_alias_wins(self):
        assert make_table().resolve_fuzzy("ana") == "e1"
        assert make_table().resolve_fuzzy("Ana Chen") == "e1"

    def test_typo_resolves_to_best_match(self):
        assert make_table().resolve_fuzzy("Ana Chenn") == "e1"

    def test_unrelated_name_returns_none(self):
        assert make_table().resolve_fuzzy("quantum flux capacitor") is None

    def test_threshold_controls_strictness(self):
        table = make_table()
        # a very strict threshold rejects the near-miss spelling
        assert table.resolve_fuzzy("Ana C.", threshold=0.99) is None

    def test_exact_lookup_is_case_insensitive(self):
        table = AliasTable()
        table.add_entity(entity("e1", "ANA"))
        # the alias index folds case, so exact hits work in any casing
        assert table.resolve_fuzzy("ana") == "e1"
        assert table.resolve_fuzzy("ANA") == "e1"


class TestAutoMerge:
    def test_near_duplicate_names_merge(self):
        table = AliasTable()
        table.add_entity(entity("e1", "release notes"))
        table.add_entity(entity("e2", "release notes!"))
        table.add_entity(entity("e3", "budget review"))
        applied = table.auto_merge_candidates(threshold=0.8)
        assert len(applied) == 1
        record = applied[0]
        assert (record.source_id, record.target_id) == ("e2", "e1")
        assert record.reason.startswith("auto:")
        # every former name still resolves, now to the survivor
        assert table.resolve("release notes!") == "e1"
        assert table.get("e2") is None

    def test_rerun_merges_nothing_new(self):
        table = AliasTable()
        table.add_entity(entity("e1", "release notes"))
        table.add_entity(entity("e2", "release notes!"))
        table.auto_merge_candidates(threshold=0.8)
        assert table.auto_merge_candidates(threshold=0.8) == []
        assert len(table.merge_history()) == 1

    def test_dissimilar_entities_untouched(self):
        table = make_table()
        assert table.auto_merge_candidates(threshold=0.8) == []
        assert len(table.all_entities()) == 3

    def test_merge_history_records_reason(self):
        table = AliasTable()
        table.add_entity(entity("e1", "weekly sync agenda"))
        table.add_entity(entity("e2", "weekly sync agendas"))
        table.auto_merge_candidates(threshold=0.8)
        history = table.merge_history()
        assert len(history) == 1
        assert history[0].reason.startswith("auto:0.")
