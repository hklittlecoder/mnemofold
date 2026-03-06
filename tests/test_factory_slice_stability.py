"""Sliced histories must be as deterministic as full ones."""

from mnemofold.factory import FactoryConfig, WorkHistoryFactory

MAIL_ONLY = ("mail_received", "mail_sent")


def sliced(seed: int = 11, days: int = 14):
    return WorkHistoryFactory(
        seed=seed, days=days, config=FactoryConfig(event_types=MAIL_ONLY)
    ).generate()


class TestSliceStability:
    def test_same_slice_is_byte_stable(self):
        assert sliced()[1].checksum == sliced()[1].checksum

    def test_slice_checksum_differs_from_full(self):
        full = WorkHistoryFactory(seed=11, days=14).generate()[1]
        assert sliced()[1].checksum != full.checksum

    def test_manifest_config_records_the_slice(self):
        manifest = sliced()[1]
        assert manifest.config["event_types"] == list(MAIL_ONLY)

    def test_manifest_config_sorts_event_types(self):
        manifest = WorkHistoryFactory(
            seed=11,
            days=14,
            config=FactoryConfig(event_types=("mail_sent", "mail_received")),
        ).generate()[1]
        assert manifest.config["event_types"] == ["mail_received", "mail_sent"]

    def test_sliced_events_stay_time_sorted(self):
        events = sliced()[0]
        stamps = [e.timestamp for e in events]
        assert stamps == sorted(stamps)

    def test_different_seeds_diverge(self):
        assert sliced(seed=11)[1].checksum != sliced(seed=12)[1].checksum
