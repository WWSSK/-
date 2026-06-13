"""Evaluation helpers for binary anomaly labels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> BinaryMetrics:
    """Return precision, recall, and F1 for point-level anomaly detection."""
    truth = np.asarray(y_true).astype(int).reshape(-1)
    pred = np.asarray(y_pred).astype(int).reshape(-1)
    if truth.shape != pred.shape:
        raise ValueError(f"shape mismatch: truth={truth.shape}, pred={pred.shape}")

    tp = int(np.sum((truth == 1) & (pred == 1)))
    fp = int(np.sum((truth == 0) & (pred == 1)))
    fn = int(np.sum((truth == 1) & (pred == 0)))
    tn = int(np.sum((truth == 0) & (pred == 0)))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return BinaryMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
    )

