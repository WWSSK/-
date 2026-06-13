#!/usr/bin/env python3
"""Convert Grafana "series to columns" pod CSV into clean DADA-Lite input."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


POD_RE = re.compile(r'pod="([^"]+)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Grafana CSV exported as series to columns")
    parser.add_argument("--output", required=True, help="clean wide CSV path")
    parser.add_argument("--train-output", default=None, help="optional normal training CSV path")
    parser.add_argument("--train-fraction", type=float, default=0.45, help="first fraction of clean rows used as normal train")
    return parser.parse_args()


def clean_column_name(column: str) -> str:
    match = POD_RE.search(column)
    if match:
        pod = match.group(1)
        return "cpu_" + re.sub(r"[^A-Za-z0-9]+", "_", pod).strip("_")
    return re.sub(r"[^A-Za-z0-9]+", "_", column).strip("_").lower()


def convert(input_path: str | Path, output_path: str | Path, train_output: str | Path | None, train_fraction: float) -> None:
    raw = pd.read_csv(input_path)
    if "Time" not in raw.columns:
        raise ValueError("expected a Grafana CSV with a Time column")

    metric_columns = [column for column in raw.columns if column != "Time"]
    valid = raw[metric_columns].notna().any(axis=1)
    clean = raw.loc[valid].copy()
    clean = clean.dropna(axis=1, how="all")

    metric_columns = [column for column in clean.columns if column != "Time"]
    renamed = {column: clean_column_name(column) for column in metric_columns}
    clean = clean.rename(columns=renamed)
    clean.insert(0, "timestamp", pd.to_datetime(clean.pop("Time"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").astype(str))

    numeric_columns = [column for column in clean.columns if column != "timestamp"]
    clean[numeric_columns] = clean[numeric_columns].apply(pd.to_numeric, errors="coerce")
    clean[numeric_columns] = clean[numeric_columns].fillna(0.0)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(output_path, index=False)

    if train_output is not None:
        n_train = max(20, int(len(clean) * train_fraction))
        n_train = min(n_train, len(clean))
        train = clean.iloc[:n_train].copy()
        train_output_path = Path(train_output)
        train_output_path.parent.mkdir(parents=True, exist_ok=True)
        train.to_csv(train_output_path, index=False)
        print(f"wrote {train_output_path} with {len(train)} train rows")

    print(f"wrote {output_path} with {len(clean)} rows and {len(numeric_columns)} metrics")


def main() -> None:
    args = parse_args()
    convert(args.input, args.output, args.train_output, args.train_fraction)


if __name__ == "__main__":
    main()
