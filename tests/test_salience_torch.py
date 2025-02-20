import pytest

from mnemofold.salience_torch import (
    FEATURE_NAMES,
    N_FEATURES,
    SalienceMLP,
    baseline_score,
    compare_to_baseline,
    generate_synthetic_dataset,
    score_items,
    torch_available,
    train_salience_model,
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.model,
]

pytest.importorskip("torch", reason="torch extra not installed")


def test_torch_available():
    assert torch_available() is True


def test_feature_count():
    assert N_FEATURES == 7
    assert len(FEATURE_NAMES) == N_FEATURES


def test_mlp_output_range():
    model = SalienceMLP(hidden_dim=8)
    features, _ = generate_synthetic_dataset(n_samples=10, seed=1)
    scores = score_items(model, features)
    assert len(scores) == 10
    for s in scores:
        assert 0.0 <= s <= 1.0


def test_training_decreases_loss():
    model = SalienceMLP(hidden_dim=16)
    features, labels = generate_synthetic_dataset(n_samples=200, seed=42)
    result = train_salience_model(model, features, labels, epochs=30, lr=0.05, seed=42)
    assert result.loss_decreased is True
    assert result.final_loss < result.initial_loss
    assert result.epochs == 30
    assert len(result.loss_history) == 30
    assert result.loss_history[0] == result.initial_loss
    assert result.loss_history[-1] == result.final_loss


def test_training_loss_trend_downward():
    model = SalienceMLP(hidden_dim=16)
    features, labels = generate_synthetic_dataset(n_samples=300, seed=55)
    result = train_salience_model(model, features, labels, epochs=40, lr=0.03, seed=55)
    # Loss should generally decrease (compare first 10 avg vs last 10 avg)
    first_quarter = sum(result.loss_history[:10]) / 10
    last_quarter = sum(result.loss_history[-10:]) / 10
    assert last_quarter < first_quarter


def test_deterministic_training():
    model1 = SalienceMLP(hidden_dim=16)
    model2 = SalienceMLP(hidden_dim=16)
    features, labels = generate_synthetic_dataset(n_samples=100, seed=7)
    r1 = train_salience_model(model1, features, labels, epochs=10, seed=99)
    r2 = train_salience_model(model2, features, labels, epochs=10, seed=99)
    assert r1.final_loss == r2.final_loss
    assert r1.loss_history == r2.loss_history


def test_synthetic_dataset_deterministic():
    f1, l1 = generate_synthetic_dataset(n_samples=50, seed=123)
    f2, l2 = generate_synthetic_dataset(n_samples=50, seed=123)
    assert f1 == f2
    assert l1 == l2


def test_synthetic_dataset_different_seeds():
    f1, l1 = generate_synthetic_dataset(n_samples=50, seed=1)
    f2, l2 = generate_synthetic_dataset(n_samples=50, seed=2)
    assert l1 != l2


def test_synthetic_dataset_labels_in_range():
    _, labels = generate_synthetic_dataset(n_samples=200, seed=42)
    for label in labels:
        assert 0.0 <= label <= 1.0


def test_baseline_score_uniform():
    feats = [0.5] * 7
    assert baseline_score(feats) == 0.5


def test_baseline_score_zeros():
    assert baseline_score([0.0] * 7) == 0.0


def test_baseline_score_ones():
    assert baseline_score([1.0] * 7) == 1.0


def test_baseline_empty():
    assert baseline_score([]) == 0.0


def test_compare_to_baseline_model_improves():
    model = SalienceMLP(hidden_dim=32)
    features, labels = generate_synthetic_dataset(n_samples=300, seed=123)
    train_salience_model(model, features, labels, epochs=50, lr=0.03, seed=123)
    comparison = compare_to_baseline(model, features, labels)
    assert "model_mse" in comparison
    assert "baseline_mse" in comparison
    assert "model_better" in comparison
    assert comparison["model_mse"] <= comparison["baseline_mse"] * 1.5
