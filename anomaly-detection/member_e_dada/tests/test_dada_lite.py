from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from dada_lite import DADALiteConfig, DADALiteDetector
from dada_lite.data import load_kpi_csv
from dada_lite.metrics import binary_metrics
from generate_synthetic_kpi import _base_kpis, _inject_faults


class DADALiteTests(unittest.TestCase):
    def test_binary_metrics(self) -> None:
        metrics = binary_metrics(np.array([0, 1, 1, 0]), np.array([0, 1, 0, 1]))
        self.assertAlmostEqual(metrics.precision, 0.5)
        self.assertAlmostEqual(metrics.recall, 0.5)
        self.assertAlmostEqual(metrics.f1, 0.5)

    def test_load_kpi_csv_selects_numeric_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            pd.DataFrame(
                {
                    "timestamp": ["t1", "t2"],
                    "latency": [100.0, 120.0],
                    "fault_type": ["normal", "cpu"],
                    "label": [0, 1],
                }
            ).to_csv(path, index=False)
            dataset = load_kpi_csv(path, label_column="label")
        self.assertEqual(dataset.metric_names, ["latency"])
        self.assertEqual(dataset.values.shape, (2, 1))
        self.assertTrue(np.array_equal(dataset.labels, np.array([0, 1])))

    def test_detector_finds_synthetic_faults(self) -> None:
        train = _base_kpis(900, seed=3)
        test = _inject_faults(_base_kpis(900, seed=4))
        metric_cols = ["latency_p99_ms", "order_success_rate", "cpu_usage", "memory_usage", "error_rate"]
        config = DADALiteConfig(window_size=80, step=10, threshold_quantile=0.975)
        detector = DADALiteDetector(config).fit(train[metric_cols].to_numpy())
        result = detector.detect(test[metric_cols].to_numpy())
        metrics = binary_metrics(test["label"].to_numpy(), result.predictions)
        self.assertGreater(metrics.f1, 0.55)
        self.assertGreater(result.threshold, 0.0)


if __name__ == "__main__":
    unittest.main()

