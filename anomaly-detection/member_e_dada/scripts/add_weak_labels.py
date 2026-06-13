#!/usr/bin/env python3
"""Add weak labels to a cleaned KPI CSV from visually inspected Grafana intervals."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--time-column", default="timestamp")
    parser.add_argument(
        "--anomaly-window",
        action="append",
        required=True,
        help="start,end,fault_type; local timestamps compatible with pandas.Timestamp",
    )
    return parser.parse_args()


def parse_window(raw: str) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        raise ValueError(f"expected start,end,fault_type: {raw}")
    return pd.Timestamp(parts[0]), pd.Timestamp(parts[1]), parts[2]


def main() -> None:
    args = parse_args()
    df = pd.read_csv(args.input)
    if args.time_column not in df.columns:
        raise ValueError(f"time column not found: {args.time_column}")

    times = pd.to_datetime(df[args.time_column])
    df["label"] = 0
    df["fault_type"] = "normal"
    df["label_source"] = "grafana_screenshot_weak_label"

    windows = [parse_window(raw) for raw in args.anomaly_window]
    for start, end, fault_type in windows:
        mask = (times >= start) & (times <= end)
        df.loc[mask, "label"] = 1
        df.loc[mask, "fault_type"] = fault_type

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output, index=False)
    print(f"wrote {output} with {int(df['label'].sum())} weak-label anomaly points")


if __name__ == "__main__":
    main()

