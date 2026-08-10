"""Factory config and manifest serialization round-trips."""

import pytest

from mnemofold.factory import FactoryConfig, HistoryManifest, WorkHistoryFactory


class TestFactoryConfigSerde:
    def test_roundtrip_canonical_form(self):
        config = FactoryConfig(
            include_designer=True,
            noise_level=0.3,
            workflow_repeats=2,
            contradiction_kinds=("owner", "due_date"),
            event_types=("mail_sent", "mail_received"),
        )
        rebuilt = FactoryConfig.from_dict(config.to_dict())
        assert rebuilt.to_dict() == config.to_dict()
        # tuple fields canonicalize to sorted order
        assert rebuilt.event_types == ("mail_received", "mail_sent")

    def test_default_roundtrip(self):
        config = FactoryConfig()
        assert FactoryConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()

    def test_unknown_key_rejected(self):
        with pytest.raises(ValueError, match="unknown factory config keys"):
            FactoryConfig.from_dict({"noise_level": 0.1, "bogus": True})

    def test_invalid_values_rejected(self):
        with pytest.raises(ValueError):
            FactoryConfig.from_dict({"noise_level": 1.5})
        with pytest.raises(ValueError, match="unknown event types"):
            FactoryConfig.from_dict({"event_types": ["telepathy"]})


class TestManifestSerde:
    def test_roundtrip_real_manifest(self):
        _, manifest = WorkHistoryFactory(seed=7, days=10).generate()
        assert HistoryManifest.from_dict(manifest.to_dict()) == manifest

    def test_roundtrip_sliced_manifest(self):
        config = FactoryConfig(event_types=("note", "mail_sent"))
        _, manifest = WorkHistoryFactory(seed=7, days=10, config=config).generate()
        rebuilt = HistoryManifest.from_dict(manifest.to_dict())
        assert rebuilt == manifest
        assert FactoryConfig.from_dict(
            rebuilt["config"] if isinstance(rebuilt, dict) else rebuilt.config
        )

    def test_to_dict_is_json_safe(self):
        import json

        _, manifest = WorkHistoryFactory(seed=3, days=5).generate()
        assert json.loads(json.dumps(manifest.to_dict())) == manifest.to_dict()
