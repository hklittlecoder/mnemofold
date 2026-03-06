"""Event-type slicing keeps ids, ground truth, and default bytes stable."""

import pytest

from mnemofold.factory import FactoryConfig, WorkHistoryFactory

MAIL_ONLY = ("mail_received", "mail_sent")


class TestEventTypeSlicing:
    def test_default_config_leaves_checksum_unchanged(self):
        plain = WorkHistoryFactory(seed=7, days=10).generate()[1].checksum
        explicit = (
            WorkHistoryFactory(seed=7, days=10, config=FactoryConfig()).generate()[1].checksum
        )
        assert plain == explicit

    def test_empty_event_types_means_no_filter(self):
        plain = WorkHistoryFactory(seed=7, days=10).generate()[1].checksum
        empty = (
            WorkHistoryFactory(seed=7, days=10, config=FactoryConfig(event_types=()))
            .generate()[1]
            .checksum
        )
        assert plain == empty

    def test_mail_only_slice_contains_only_mail(self):
        events, manifest = WorkHistoryFactory(
            seed=7, days=14, config=FactoryConfig(event_types=MAIL_ONLY)
        ).generate()
        assert events, "slice must not be empty for this seed"
        assert all(e.event_type in MAIL_ONLY for e in events)
        assert manifest.event_count == len(events)

    def test_slice_reduces_event_count(self):
        full = WorkHistoryFactory(seed=7, days=14).generate()[0]
        sliced = WorkHistoryFactory(
            seed=7, days=14, config=FactoryConfig(event_types=MAIL_ONLY)
        ).generate()[0]
        assert len(sliced) < len(full)

    def test_event_ids_are_preserved_from_the_full_run(self):
        full = WorkHistoryFactory(seed=7, days=14).generate()[0]
        sliced = WorkHistoryFactory(
            seed=7, days=14, config=FactoryConfig(event_types=MAIL_ONLY)
        ).generate()[0]
        full_ids = {e.event_id for e in full}
        assert {e.event_id for e in sliced} <= full_ids

    def test_planted_ground_truth_survives_slicing(self):
        full_f = WorkHistoryFactory(seed=7, days=14)
        full_f.generate()
        sliced_f = WorkHistoryFactory(seed=7, days=14, config=FactoryConfig(event_types=MAIL_ONLY))
        sliced_f.generate()
        assert [p.item_id for p in sliced_f.planted_items()] == [
            p.item_id for p in full_f.planted_items()
        ]

    def test_unknown_event_type_rejected(self):
        with pytest.raises(ValueError, match="unknown event types"):
            WorkHistoryFactory(config=FactoryConfig(event_types=("bogus",)))
