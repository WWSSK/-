#!/usr/bin/env python3
"""Train DADA-Lite on normal KPI data and detect anomalies in a test CSV."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from dada_lite import DADALiteConfig, DADALiteDetector
from dada_lite.data import load_kpi_csv
from dada_lite.metrics import binary_metrics
from dada_lite.svg import write_timeline_svg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-csv", required=True, help="normal KPI CSV for threshold calibration")
    parser.add_argument("--test-csv", required=True, help="KPI CSV to detect")
    parser.add_argument("--time-column", default="timestamp")
    parser.add_argument("--label-column", default=None)
    parser.add_argument("--metric-columns", default=None, help="comma-separated metric columns")
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument("--window-size", type=int, default=100)
    parser.add_argument("--step", type=int, default=20)
    parser.add_argument("--threshold-quantile", type=float, default=0.985)
    parser.add_argument("--injected-threshold-quantile", type=float, default=0.75)
    parser.add_argument("--title", default="Member E DADA-Lite on TrainTicket KPI")
    parser.add_argument("--primary-metric", default=None, help="metric column to draw in the SVG timeline")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metric_columns = args.metric_columns.split(",") if args.metric_columns else None
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    train = load_kpi_csv(
        args.train_csv,
        time_column=args.time_column,
        label_column=args.label_column,
        metric_columns=metric_columns,
    )
    test = load_kpi_csv(
        args.test_csv,
        time_column=args.time_column,
        label_column=args.label_column,
        metric_columns=metric_columns or train.metric_names,
    )

    config = DADALiteConfig(
        window_size=args.window_size,
        step=args.step,
        threshold_quantile=args.threshold_quantile,
        injected_threshold_quantile=args.injected_threshold_quantile,
    )
    detector = DADALiteDetector(config).fit(train.values)
    result = detector.detect(test.values)

    output_df = pd.DataFrame({"timestamp": test.timestamps})
    for index, metric in enumerate(test.metric_names):
        output_df[metric] = test.values[:, index]
    output_df["anomaly_score"] = result.scores
    output_df["threshold"] = result.threshold
    output_df["prediction"] = result.predictions
    if test.labels is not None:
        output_df["label"] = test.labels
    output_df.to_csv(out_dir / "detection_scores.csv", index=False)

    summary: dict[str, object] = {
        "config": asdict(config),
        "threshold": result.threshold,
        "n_points": int(len(result.scores)),
        "predicted_anomaly_points": int(result.predictions.sum()),
        "metric_names": test.metric_names,
    }
    if test.labels is not None:
        metrics = binary_metrics(test.labels, result.predictions)
        summary["metrics"] = asdict(metrics)
    (out_dir / "detection_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    bottleneck_df = pd.DataFrame(
        [{"bottleneck_dim": dim, "selected_count": count} for dim, count in sorted(result.bottleneck_usage.items())]
    )
    bottleneck_df.to_csv(out_dir / "bottleneck_usage.csv", index=False)

    primary_metric_index = 0
    if args.primary_metric:
        if args.primary_metric not in test.metric_names:
            raise ValueError(f"primary metric not found: {args.primary_metric}")
        primary_metric_index = test.metric_names.index(args.primary_metric)

    write_timeline_svg(
        out_dir / "detection_timeline.svg",
        primary_metric=test.values[:, primary_metric_index],
        scores=result.scores,
        threshold=result.threshold,
        labels=test.labels,
        predictions=result.predictions,
        title=args.title,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"wrote outputs to {out_dir}")


if __name__ == "__main__":
    main()
