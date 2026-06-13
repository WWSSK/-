"""A lightweight DADA-style detector for TrainTicket KPI time series.

This implementation mirrors the paper's core ideas with linear components so it
can run in a constrained course-project environment without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import (
    Standardizer,
    WindowedSeries,
    fit_standardizer,
    make_windows,
)


@dataclass(frozen=True)
class DADALiteConfig:
    window_size: int = 100
    step: int = 20
    patch_size: int = 5
    bottleneck_dims: tuple[int, ...] = (2, 4, 8, 12, 16)
    top_k: int = 3
    mask_pairs: int = 5
    mask_ratio: float = 0.5
    threshold_quantile: float = 0.985
    injected_threshold_quantile: float = 0.75
    anomaly_weight: float = 0.15
    random_seed: int = 42


@dataclass(frozen=True)
class LinearBottleneck:
    mean: np.ndarray
    components: np.ndarray
    dim: int

    def reconstruct(self, values: np.ndarray) -> np.ndarray:
        centered = np.asarray(values, dtype=float) - self.mean
        return self.mean + centered @ self.components.T @ self.components


@dataclass(frozen=True)
class DetectionResult:
    scores: np.ndarray
    predictions: np.ndarray
    threshold: float
    bottleneck_usage: dict[int, int]


def _fit_linear_bottleneck(windows: np.ndarray, dim: int) -> LinearBottleneck:
    data = np.asarray(windows, dtype=float)
    mean = np.mean(data, axis=0)
    centered = data - mean
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    actual_dim = max(1, min(int(dim), vt.shape[0]))
    return LinearBottleneck(mean=mean, components=vt[:actual_dim], dim=actual_dim)


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values)
    exp_values = np.exp(shifted)
    return exp_values / np.sum(exp_values)


def _inject_common_anomalies(windows: np.ndarray, seed: int, n_channels: int = 1) -> np.ndarray:
    """Generate DADA-style synthetic anomalies: spike, scale, noise, and pattern shifts."""
    rng = np.random.default_rng(seed)
    injected = np.asarray(windows, dtype=float).copy()
    n_rows, n_features = injected.shape
    if n_features < 4:
        return injected + rng.normal(0.0, 2.0, size=injected.shape)

    for row_index in range(n_rows):
        row = injected[row_index].copy().reshape(-1, max(1, n_channels))
        time_steps = row.shape[0]
        fault_type = row_index % 4
        start = int(rng.integers(0, max(1, time_steps // 2)))
        width = int(rng.integers(max(3, time_steps // 8), max(4, time_steps // 3)))
        end = min(time_steps, start + width)
        if fault_type == 0:
            row[start:end, 0] += rng.normal(22.0, 2.0, size=end - start)
            row[start:end, -1] += rng.normal(28.0, 2.0, size=end - start)
        elif fault_type == 1:
            row[start:end, :] *= rng.choice([6.0, -5.0])
        elif fault_type == 2:
            row[start:end, :] += rng.normal(0.0, 15.0, size=(end - start, row.shape[1]))
        else:
            row[start:end, :] = row[start:end, :][::-1]
            row[start:end, 0] += 18.0
            row[start:end, -1] += 24.0
        if row.shape[1] > 1:
            row[start:end, 1] -= 22.0
        if row.shape[1] > 2:
            row[start:end, 2] += 18.0
        injected[row_index] = row.reshape(-1)
    return injected


class DADALiteDetector:
    """DADA-inspired anomaly detector using adaptive linear bottlenecks."""

    def __init__(self, config: DADALiteConfig | None = None) -> None:
        self.config = config or DADALiteConfig()
        self.standardizer: Standardizer | None = None
        self.normal_bottlenecks: list[LinearBottleneck] = []
        self.anomaly_bottlenecks: list[LinearBottleneck] = []
        self.threshold: float | None = None
        self.n_features: int | None = None
        self._usage: dict[int, int] = {}

    def fit(self, normal_values: np.ndarray) -> "DADALiteDetector":
        data = np.asarray(normal_values, dtype=float)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        self.n_features = data.shape[1]
        self.standardizer = fit_standardizer(data)
        normalized = self.standardizer.transform(data)
        windowed = make_windows(normalized, self.config.window_size, self.config.step)

        max_dim = windowed.windows.shape[1]
        dims = tuple(dim for dim in self.config.bottleneck_dims if dim < max_dim)
        if not dims:
            dims = (max(1, min(max_dim - 1, 2)),)

        self.normal_bottlenecks = [_fit_linear_bottleneck(windowed.windows, dim) for dim in dims]
        synthetic_anomalies = _inject_common_anomalies(
            windowed.windows,
            self.config.random_seed,
            n_channels=data.shape[1],
        )
        self.anomaly_bottlenecks = [_fit_linear_bottleneck(synthetic_anomalies, dim) for dim in dims]

        normal_scores = self._score_points_for_windowed(windowed)
        synthetic_windowed = WindowedSeries(
            windows=synthetic_anomalies,
            starts=windowed.starts,
            ends=windowed.ends,
            n_points=windowed.n_points,
        )
        injected_scores = self._score_points_for_windowed(synthetic_windowed)
        normal_threshold = float(np.quantile(normal_scores, self.config.threshold_quantile))
        injected_threshold = float(np.quantile(injected_scores, self.config.injected_threshold_quantile))
        self.threshold = max(normal_threshold, injected_threshold)
        self._usage = {}
        return self

    def detect(self, values: np.ndarray) -> DetectionResult:
        self._require_fitted()
        data = np.asarray(values, dtype=float)
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        normalized = self.standardizer.transform(data)  # type: ignore[union-attr]
        windowed = make_windows(normalized, self.config.window_size, self.config.step)
        self._usage = {}
        point_scores = self._score_points_for_windowed(windowed)[: data.shape[0]]
        predictions = (point_scores > float(self.threshold)).astype(int)
        return DetectionResult(
            scores=point_scores,
            predictions=predictions,
            threshold=float(self.threshold),
            bottleneck_usage=dict(self._usage),
        )

    def _require_fitted(self) -> None:
        if self.standardizer is None or self.threshold is None or not self.normal_bottlenecks:
            raise RuntimeError("fit must be called before detect")

    def _score_windows(self, windows: np.ndarray) -> np.ndarray:
        """Return one scalar score per window for diagnostics."""
        point_scores = [np.mean(self._score_window_pointwise(window, index)) for index, window in enumerate(windows)]
        return np.asarray(point_scores, dtype=float)

    def _score_points_for_windowed(self, windowed: WindowedSeries) -> np.ndarray:
        scores = np.zeros(windowed.n_points, dtype=float)
        counts = np.zeros(windowed.n_points, dtype=float)
        for index, (window, start, end) in enumerate(
            zip(windowed.windows, windowed.starts, windowed.ends, strict=True)
        ):
            point_scores = self._score_window_pointwise(window, index)
            scores[start:end] += point_scores
            counts[start:end] += 1.0
        safe_counts = np.where(counts == 0.0, 1.0, counts)
        return scores / safe_counts

    def _score_window_pointwise(self, window: np.ndarray, index: int) -> np.ndarray:
        n_features = max(1, int(self.n_features or 1))
        rng = np.random.default_rng(self.config.random_seed + index)
        normal_recon, chosen_dims = self._adaptive_reconstruct(window, self.normal_bottlenecks)
        anomaly_recon, _ = self._adaptive_reconstruct(window, self.anomaly_bottlenecks)
        for dim in chosen_dims:
            self._usage[dim] = self._usage.get(dim, 0) + 1

        value_error = (window - normal_recon) ** 2
        anomaly_error = (window - anomaly_recon) ** 2
        masked_variance = self._complementary_mask_variance_values(window, rng)
        dual_signal = value_error / (anomaly_error + 1e-6)
        flat_scores = value_error + masked_variance + self.config.anomaly_weight * np.clip(dual_signal, 0.0, 10.0)
        return flat_scores.reshape(-1, n_features).mean(axis=1)

    def _score_windows_legacy(self, windows: np.ndarray) -> np.ndarray:
        scores = []
        for index, window in enumerate(np.asarray(windows, dtype=float)):
            rng = np.random.default_rng(self.config.random_seed + index)
            normal_recon, chosen_dims = self._adaptive_reconstruct(window, self.normal_bottlenecks)
            anomaly_recon, _ = self._adaptive_reconstruct(window, self.anomaly_bottlenecks)
            for dim in chosen_dims:
                self._usage[dim] = self._usage.get(dim, 0) + 1

            normal_error = float(np.mean((window - normal_recon) ** 2))
            anomaly_error = float(np.mean((window - anomaly_recon) ** 2))
            masked_variance = self._complementary_mask_variance(window, rng)
            dual_signal = normal_error / (anomaly_error + 1e-6)
            scores.append(normal_error + masked_variance + self.config.anomaly_weight * min(10.0, dual_signal))
        return np.asarray(scores, dtype=float)

    def _adaptive_reconstruct(
        self,
        window: np.ndarray,
        bottlenecks: list[LinearBottleneck],
    ) -> tuple[np.ndarray, list[int]]:
        reconstructions = []
        errors = []
        for bottleneck in bottlenecks:
            reconstruction = bottleneck.reconstruct(window.reshape(1, -1))[0]
            reconstructions.append(reconstruction)
            errors.append(float(np.mean((window - reconstruction) ** 2)))

        error_array = np.asarray(errors, dtype=float)
        k = max(1, min(self.config.top_k, len(bottlenecks)))
        selected = np.argsort(error_array)[:k]
        weights = _softmax(-error_array[selected])
        fused = np.sum([weights[i] * reconstructions[idx] for i, idx in enumerate(selected)], axis=0)
        selected_dims = [bottlenecks[int(idx)].dim for idx in selected]
        return np.asarray(fused, dtype=float), selected_dims

    def _complementary_mask_variance(self, window: np.ndarray, rng: np.random.Generator) -> float:
        return float(np.mean(self._complementary_mask_variance_values(window, rng)))

    def _complementary_mask_variance_values(self, window: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        reconstructions = []
        for _ in range(self.config.mask_pairs):
            mask = self._patch_mask(len(window), rng)
            masked_a = np.where(mask, window, 0.0)
            masked_b = np.where(mask, 0.0, window)
            recon_a, _ = self._adaptive_reconstruct(masked_a, self.normal_bottlenecks)
            recon_b, _ = self._adaptive_reconstruct(masked_b, self.normal_bottlenecks)
            combined = np.where(mask, recon_b, recon_a)
            reconstructions.append(combined)
        stacked = np.vstack(reconstructions)
        return np.var(stacked, axis=0)

    def _patch_mask(self, n_values: int, rng: np.random.Generator) -> np.ndarray:
        n_features = max(1, int(self.n_features or 1))
        time_steps = max(1, n_values // n_features)
        patch_size = max(1, self.config.patch_size)
        n_patches = int(np.ceil(time_steps / patch_size))
        n_mask = max(1, int(round(n_patches * self.config.mask_ratio)))
        selected_patches = set(rng.choice(n_patches, size=min(n_mask, n_patches), replace=False).tolist())

        mask = np.zeros((time_steps, n_features), dtype=bool)
        for patch in range(n_patches):
            start = patch * patch_size
            end = min(time_steps, start + patch_size)
            if patch in selected_patches:
                mask[start:end, :] = True
        return mask.reshape(-1)[:n_values]
