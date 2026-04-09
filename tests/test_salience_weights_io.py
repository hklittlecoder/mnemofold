"""Weight export/import roundtrips for the optional torch scorer."""

import json

import pytest

from mnemofold.salience_torch import (
    SalienceMLP,
    export_weights,
    generate_synthetic_dataset,
    import_weights,
    score_items,
    train_salience_model,
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.model,
]

pytest.importorskip("torch", reason="torch extra not installed")


def trained_model(seed: int = 7) -> SalienceMLP:
    features, labels = generate_synthetic_dataset(n_samples=64, seed=seed)
    model = SalienceMLP(hidden_dim=8, seed=seed)
    train_salience_model(model, features, labels, epochs=5, lr=0.01, seed=seed)
    return model


class TestWeightsIO:
    def test_export_is_json_serializable(self):
        data = export_weights(trained_model())
        text = json.dumps(data, sort_keys=True)
        assert json.loads(text) == data
        assert data["format"] == "salience_mlp_v1"
        assert data["hidden_dim"] == 8

    def test_import_reproduces_scores(self):
        model = trained_model()
        features, _ = generate_synthetic_dataset(n_samples=16, seed=99)
        original = score_items(model, features)
        restored = score_items(import_weights(export_weights(model)), features)
        assert len(original) == len(restored)
        for a, b in zip(original, restored, strict=True):
            assert abs(a - b) < 1e-5

    def test_double_export_is_idempotent(self):
        model = trained_model()
        once = export_weights(model)
        twice = export_weights(import_weights(once))
        assert once == twice

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError, match="unknown weight export format"):
            import_weights({"format": "salience_mlp_v9", "hidden_dim": 8, "weights": {}})

    def test_export_covers_every_parameter(self):
        model = trained_model()
        data = export_weights(model)
        assert set(data["weights"]) == set(model.state_dict().keys())
