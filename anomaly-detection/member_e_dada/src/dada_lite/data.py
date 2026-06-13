"""CSV loading and windowing utilities for KPI anomaly detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TimeSeriesDataset:
    values: np.ndarray
    timestamps: list[str]
    metric_names: list[str]
    labels: np.ndarray | None = None


@dataclass(frozen=True)
class WindowedSeries:
    windows: np.ndarray
    starts: np.ndarray
    ends: np.ndarray
    n_points: int


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    def transform(self, values: np.ndarray) -> np.ndarray:
        return (np.asarray(values, dtype=float) - self.mean) / self.scale


def load_kpi_csv(
    path: str | Path,
    time_column: str = "timestamp",
    label_column: str | None = "label",
    metric_columns: Iterable[str] | None = None,
) -> TimeSeriesDataset:
    """Load a wide KPI CSV exported from Prometheus/Grafana processing."""
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError(f"CSV is empty: {path}")

    timestamps = (
        df[time_column].astype(str).tolist()
        if time_column in df.columns
        else [str(index) for index in range(len(df))]
    )
    labels = None
    if label_column and label_column in df.columns:
        labels = pd.to_numeric(df[label_column], errors="coerce").fillna(0).astype(int).to_numpy()

    excluded = {time_column}
    if label_column:
        excluded.add(label_column)
    excluded.update({"fault", "fault_type", "scenario"})

    if metric_columns is None:
        numeric_candidates = []
        for column in df.columns:
            if column in excluded:
                continue
            numeric = pd.to_numeric(df[column], errors="coerce")
            if numeric.notna().any():
                numeric_candidates.append(column)
        selected_columns = numeric_candidates
    else:
        selected_columns = list(metric_columns)

    if not selected_columns:
        raise ValueError("no numeric metric columns found")

    values_df = df[selected_columns].apply(pd.to_numeric, errors="coerce")
    values_df = values_df.ffill().bfill()
    values_df = values_df.fillna(values_df.median(numeric_only=True))
    values_df = values_df.fillna(0.0)

    return TimeSeriesDataset(
        values=values_df.to_numpy(dtype=float),
        timestamps=timestamps,
        metric_names=selected_columns,
        labels=labels,
    )


def fit_standardizer(values: np.ndarray) -> Standardizer:
    data = np.asarray(values, dtype=float)
    mean = np.mean(data, axis=0)
    scale = np.std(data, axis=0)
    safe_scale = np.where(scale < 1e-8, 1.0, scale)
    return Standardizer(mean=mean, scale=safe_scale)


def make_windows(values: np.ndarray, window_size: int, step: int) -> WindowedSeries:
    """Create flattened sliding windows and remember point spans."""
    if window_size <= 0 or step <= 0:
        raise ValueError("window_size and step must be positive")

    data = np.asarray(values, dtype=float)
    if data.ndim == 1:
        data = data.reshape(-1, 1)

    n_points = data.shape[0]
    if n_points < window_size:
        pad_count = window_size - n_points
        pad_values = np.repeat(data[-1:, :], pad_count, axis=0)
        data = np.vstack([data, pad_values])
        n_points = data.shape[0]

    starts = list(range(0, n_points - window_size + 1, step))
    if starts[-1] != n_points - window_size:
        starts.append(n_points - window_size)

    window_list = [data[start : start + window_size].reshape(-1) for start in starts]
    return WindowedSeries(
        windows=np.asarray(window_list, dtype=float),
        starts=np.asarray(starts, dtype=int),
        ends=np.asarray([start + window_size for start in starts], dtype=int),
        n_points=n_points,
    )


def aggregate_window_scores(
    window_scores: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    n_points: int,
) -> np.ndarray:
    """Average overlapping window scores back to point-level scores."""
    scores = np.zeros(n_points, dtype=float)
    counts = np.zeros(n_points, dtype=float)
    for score, start, end in zip(window_scores, starts, ends, strict=True):
        scores[start:end] += float(score)
        counts[start:end] += 1.0
    safe_counts = np.where(counts == 0.0, 1.0, counts)
    return scores / safe_counts

