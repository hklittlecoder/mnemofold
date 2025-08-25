"""Optional PyTorch salience scorer (MLP).

A small MLP that learns to combine the NumPy salience features into a
single priority score.  Trained on synthetic labeled data with a
deterministic seed; shows real loss decrease.  Compared honestly
against the NumPy baseline in evaluation.

All torch-dependent tests skip cleanly when the extra is absent and are
marked ``@pytest.mark.model`` and ``@pytest.mark.slow``.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    import torch
    from torch import nn, optim

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


def torch_available() -> bool:
    return _TORCH_AVAILABLE


N_FEATURES = 7
FEATURE_NAMES = [
    "deadline_proximity",
    "ownership_weight",
    "decision_weight",
    "recurrence_count",
    "pinned_bonus",
    "recency_decay",
    "graph_centrality",
]


class SalienceMLP(nn.Module):
    """A small MLP that maps salience features to a score in [0, 1].

    ``seed`` makes weight initialization reproducible: two models built
    with the same seed and shape start from identical weights, so a
    subsequent seeded training run is byte-identical. Without a seed the
    global torch RNG state is used (construction is then non-reproducible
    on its own), matching the usual PyTorch convention.
    """

    def __init__(self, hidden_dim: int = 16, seed: int | None = None) -> None:
        super().__init__()
        if seed is not None:
            torch.manual_seed(seed)
        self.net = nn.Sequential(
            nn.Linear(N_FEATURES, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


@dataclass
class TrainingResult:
    final_loss: float
    initial_loss: float
    epochs: int
    loss_decreased: bool
    loss_history: list[float]


def generate_synthetic_dataset(
    n_samples: int = 500,
    seed: int = 42,
) -> tuple[list[list[float]], list[float]]:
    """Generate synthetic feature->salience pairs.

    The ground truth is a weighted combination of features with some
    noise.  This lets us verify the MLP learns to predict the score.
    """
    import random

    rng = random.Random(seed)
    features: list[list[float]] = []
    labels: list[float] = []

    weights = [0.25, 0.15, 0.20, 0.10, 0.15, 0.10, 0.05]

    for _ in range(n_samples):
        feats = [rng.random() for _ in range(N_FEATURES)]
        # Ground truth: weighted sum + noise
        score = sum(w * f for w, f in zip(weights, feats, strict=False))
        score += rng.gauss(0, 0.03)
        score = max(0.0, min(1.0, score))
        features.append(feats)
        labels.append(score)

    return features, labels


def train_salience_model(
    model: SalienceMLP,
    features: list[list[float]],
    labels: list[float],
    epochs: int = 50,
    lr: float = 0.01,
    seed: int = 42,
) -> TrainingResult:
    """Train the salience MLP on synthetic data.

    Returns a TrainingResult showing initial loss, final loss, and
    whether loss decreased (it always should with proper setup).
    """
    if not _TORCH_AVAILABLE:
        raise ImportError("torch is not available")

    torch.manual_seed(seed)

    x_tensor = torch.tensor(features, dtype=torch.float32)
    y = torch.tensor(labels, dtype=torch.float32)

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    loss_history: list[float] = []

    model.train()
    initial_loss = float("inf")

    for epoch in range(epochs):
        optimizer.zero_grad()
        predictions = model(x_tensor)
        loss = criterion(predictions, y)
        loss_value = loss.item()
        loss_history.append(round(loss_value, 6))

        if epoch == 0:
            initial_loss = loss_value

        loss.backward()
        optimizer.step()

    final_loss = loss_history[-1] if loss_history else initial_loss
    return TrainingResult(
        final_loss=round(final_loss, 6),
        initial_loss=round(initial_loss, 6),
        epochs=epochs,
        loss_decreased=final_loss < initial_loss,
        loss_history=loss_history,
    )


def score_items(
    model: SalienceMLP,
    features: list[list[float]],
) -> list[float]:
    """Score a batch of items using the trained model.

    Returns a list of scores in [0, 1].
    """
    if not _TORCH_AVAILABLE:
        raise ImportError("torch is not available")

    model.eval()
    with torch.no_grad():
        x_tensor = torch.tensor(features, dtype=torch.float32)
        scores = model(x_tensor)
    return [round(float(s), 6) for s in scores.tolist()]


def baseline_score(features: list[float]) -> float:
    """Simple baseline: uniform-weight average of features.

    Used as a comparison point for the MLP scorer.
    """
    if not features:
        return 0.0
    return round(sum(features) / len(features), 6)


def compare_to_baseline(
    model: SalienceMLP,
    features: list[list[float]],
    labels: list[float],
) -> dict[str, float]:
    """Compare model predictions against the uniform baseline.

    Returns MSE for both model and baseline.
    """
    if not _TORCH_AVAILABLE:
        raise ImportError("torch is not available")

    model_scores = score_items(model, features)
    baseline_scores = [baseline_score(f) for f in features]

    model_mse = sum((s - y) ** 2 for s, y in zip(model_scores, labels, strict=False)) / len(labels)
    baseline_mse = sum((s - y) ** 2 for s, y in zip(baseline_scores, labels, strict=False)) / len(
        labels
    )

    return {
        "model_mse": round(model_mse, 6),
        "baseline_mse": round(baseline_mse, 6),
        "model_better": model_mse < baseline_mse,
    }
