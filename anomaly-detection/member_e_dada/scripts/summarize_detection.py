#!/usr/bin/env python3
"""Summarize DADA-Lite detection scores into intervals and top KPI contributors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores-csv", required=True)
    parser.add_argument("--train-csv", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--time-column", default="timestamp")
    parser.add_argument("--max-gap-points", type=int, default=2, help="merge anomaly intervals separated by <= this gap")
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def metric_columns(df: pd.DataFrame, time_column: str) -> list[str]:
    excluded = {time_column, "anomaly_score", "threshold", "prediction", "label", "fault_type", "target_service"}
    return [column for column in df.columns if column not in excluded and pd.api.types.is_numeric_dtype(df[column])]


def anomaly_intervals(predictions: np.ndarray, max_gap_points: int) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    start: int | None = None
    last_anomaly: int | None = None
    for index, flag in enumerate(predictions.tolist()):
        if int(flag) == 1:
            if start is None:
                start = index
            last_anomaly = index
        elif start is not None and last_anomaly is not None and index - last_anomaly > max_gap_points:
            intervals.append((start, last_anomaly))
            start = None
            last_anomaly = None
    if start is not None and last_anomaly is not None:
        intervals.append((start, last_anomaly))
    return intervals


def robust_contributors(train: pd.DataFrame, segment: pd.DataFrame, columns: list[str], top_k: int) -> list[dict[str, float | str]]:
    train_values = train[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    segment_values = segment[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    median = train_values.median(axis=0)
    mad = (train_values - median).abs().median(axis=0)
    scale = mad.replace(0.0, np.nan).fillna(train_values.std(axis=0)).replace(0.0, 1.0)
    z = ((segment_values - median).abs() / scale).mean(axis=0)
    top = z.sort_values(ascending=False).head(top_k)
    return [{"metric": metric, "mean_robust_z": float(value)} for metric, value in top.items()]


def main() -> None:
    args = parse_args()
    scores = pd.read_csv(args.scores_csv)
    train = pd.read_csv(args.train_csv)
    columns = metric_columns(scores, args.time_column)
    if not columns:
        raise ValueError("no numeric KPI columns found in scores CSV")

    predictions = scores["prediction"].to_numpy(dtype=int)
    intervals = anomaly_intervals(predictions, args.max_gap_points)
    interval_records = []
    for start, end in intervals:
        segment = scores.iloc[start : end + 1]
        interval_records.append(
            {
                "start": str(segment[args.time_column].iloc[0]),
                "end": str(segment[args.time_column].iloc[-1]),
                "points": int(len(segment)),
                "max_score": float(segment["anomaly_score"].max()),
                "mean_score": float(segment["anomaly_score"].mean()),
                "top_contributors": robust_contributors(train, segment, columns, args.top_k),
            }
        )

    summary = {
        "n_points": int(len(scores)),
        "predicted_anomaly_points": int(scores["prediction"].sum()),
        "threshold": float(scores["threshold"].iloc[0]),
        "interval_count": len(interval_records),
        "intervals": interval_records,
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# C 同学真实数据检测结果摘要",
        "",
        f"- 总时间点：{summary['n_points']}",
        f"- 检测异常点：{summary['predicted_anomaly_points']}",
        f"- 阈值：{summary['threshold']:.4f}",
        f"- 合并后的异常时间段数：{summary['interval_count']}",
        "",
        "| 异常段 | 开始时间 | 结束时间 | 点数 | 最高分数 | 主要贡献指标 |",
        "|---:|---|---|---:|---:|---|",
    ]
    for index, record in enumerate(interval_records, start=1):
        contributors = ", ".join(
            f"{item['metric']}({item['mean_robust_z']:.1f})" for item in record["top_contributors"][:3]
        )
        lines.append(
            f"| {index} | {record['start']} | {record['end']} | {record['points']} | "
            f"{record['max_score']:.2f} | {contributors} |"
        )
    lines.extend(
        [
            "",
            "说明：C 同学 CSV 未提供故障 label，因此本摘要为无监督检测结果，不能计算 Precision/Recall/F1。",
            "主要贡献指标使用相对训练段的 robust z-score 排序，用于辅助解释异常来源。",
        ]
    )
    output_md = Path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {output_md}")
    print(f"wrote {output_json}")


if __name__ == "__main__":
    main()

