#!/usr/bin/env python3
"""Generate TrainTicket-like KPI data for member E offline experiments."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd


def _base_kpis(n_points: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n_points)
    daily = np.sin(2.0 * np.pi * t / 144.0)
    burst = np.sin(2.0 * np.pi * t / 37.0)

    latency = 145.0 + 22.0 * daily + 8.0 * burst + rng.normal(0.0, 5.0, n_points)
    success_rate = 0.985 - 0.012 * np.maximum(0.0, daily) + rng.normal(0.0, 0.004, n_points)
    cpu = 0.43 + 0.12 * np.maximum(0.0, daily) + 0.04 * burst + rng.normal(0.0, 0.015, n_points)
    memory = 0.58 + 0.03 * np.sin(2.0 * np.pi * t / 220.0) + rng.normal(0.0, 0.01, n_points)
    error_rate = 0.006 + 0.004 * np.maximum(0.0, daily) + rng.normal(0.0, 0.002, n_points)

    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-12 09:00:00", periods=n_points, freq="15s").astype(str),
            "latency_p99_ms": np.maximum(latency, 1.0),
            "order_success_rate": np.clip(success_rate, 0.0, 1.0),
            "cpu_usage": np.clip(cpu, 0.0, 1.2),
            "memory_usage": np.clip(memory, 0.0, 1.2),
            "error_rate": np.clip(error_rate, 0.0, 1.0),
        }
    )


def _inject_faults(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["label"] = 0
    result["fault_type"] = "normal"

    fault_windows = [
        (220, 285, "network_loss"),
        (520, 610, "cpu_pressure"),
        (820, 875, "pod_kill"),
    ]
    for start, end, fault_type in fault_windows:
        indexer = result.index[start:end]
        result.loc[indexer, "label"] = 1
        result.loc[indexer, "fault_type"] = fault_type
        if fault_type == "network_loss":
            result.loc[indexer, "latency_p99_ms"] *= 4.5
            result.loc[indexer, "order_success_rate"] -= 0.22
            result.loc[indexer, "error_rate"] += 0.16
        elif fault_type == "cpu_pressure":
            result.loc[indexer, "cpu_usage"] += 0.52
            result.loc[indexer, "latency_p99_ms"] *= 2.2
            result.loc[indexer, "error_rate"] += 0.055
        elif fault_type == "pod_kill":
            result.loc[indexer, "order_success_rate"] -= 0.34
            result.loc[indexer, "error_rate"] += 0.24
            result.loc[indexer, "memory_usage"] -= 0.18

    result["order_success_rate"] = np.clip(result["order_success_rate"], 0.0, 1.0)
    result["cpu_usage"] = np.clip(result["cpu_usage"], 0.0, 1.5)
    result["memory_usage"] = np.clip(result["memory_usage"], 0.0, 1.5)
    result["error_rate"] = np.clip(result["error_rate"], 0.0, 1.0)
    return result


def main() -> None:
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    train_parts = [_base_kpis(900, seed=seed) for seed in (7, 11, 13)]
    train = pd.concat(train_parts, ignore_index=True)
    train["timestamp"] = pd.date_range("2026-06-11 09:00:00", periods=len(train), freq="15s").astype(str)
    train["label"] = 0
    train["fault_type"] = "normal"
    test = _inject_faults(_base_kpis(1100, seed=17))

    train.to_csv(data_dir / "train_normal.csv", index=False)
    test.to_csv(data_dir / "test_with_faults.csv", index=False)
    print(f"wrote {data_dir / 'train_normal.csv'}")
    print(f"wrote {data_dir / 'test_with_faults.csv'}")


if __name__ == "__main__":
    main()
