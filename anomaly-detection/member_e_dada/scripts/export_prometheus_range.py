#!/usr/bin/env python3
"""Export Prometheus query_range results into a wide KPI CSV."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prometheus-url", required=True, help="Prometheus base URL, e.g. http://127.0.0.1:9090")
    parser.add_argument("--queries-json", required=True, help="JSON object mapping output column to PromQL")
    parser.add_argument("--start", required=True, help="start time, ISO string or Unix timestamp")
    parser.add_argument("--end", required=True, help="end time, ISO string or Unix timestamp")
    parser.add_argument("--step", default="15s", help="Prometheus query_range step, e.g. 15s or 1m")
    parser.add_argument("--output", required=True, help="output wide CSV path")
    parser.add_argument("--label", type=int, default=None, help="constant label for every row")
    parser.add_argument("--fault-type", default=None, help="constant fault_type for every row")
    parser.add_argument("--target-service", default=None, help="constant target_service for every row")
    parser.add_argument(
        "--fault-window",
        action="append",
        default=[],
        help="start,end,fault_type,target_service; can be provided multiple times",
    )
    return parser.parse_args()


def parse_time(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        pass
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def request_query_range(
    prometheus_url: str,
    query: str,
    start: float,
    end: float,
    step: str,
) -> list[list[Any]]:
    base = prometheus_url.rstrip("/") + "/api/v1/query_range"
    params = urlencode({"query": query, "start": start, "end": end, "step": step})
    with urlopen(f"{base}?{params}", timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {payload}")
    result = payload.get("data", {}).get("result", [])
    if not result:
        return []
    # The recommended queries aggregate to one series. If Prometheus returns
    # multiple series, average them by timestamp to keep a wide CSV shape.
    values_by_time: dict[float, list[float]] = {}
    for series in result:
        for timestamp, value in series.get("values", []):
            values_by_time.setdefault(float(timestamp), []).append(float(value))
    return [[timestamp, sum(values) / len(values)] for timestamp, values in sorted(values_by_time.items())]


def parse_fault_windows(values: list[str]) -> list[tuple[float, float, str, str]]:
    windows = []
    for raw in values:
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 4:
            raise ValueError(f"fault-window must be start,end,fault_type,target_service: {raw}")
        windows.append((parse_time(parts[0]), parse_time(parts[1]), parts[2], parts[3]))
    return windows


def labels_for_timestamp(
    timestamp: float,
    default_label: int | None,
    default_fault_type: str | None,
    default_target_service: str | None,
    fault_windows: list[tuple[float, float, str, str]],
) -> tuple[int, str, str]:
    for start, end, fault_type, target_service in fault_windows:
        if start <= timestamp <= end:
            return 1, fault_type, target_service
    label = int(default_label) if default_label is not None else 0
    fault_type = default_fault_type if default_fault_type is not None else ("normal" if label == 0 else "fault")
    target_service = default_target_service if default_target_service is not None else "-"
    return label, fault_type, target_service


def main() -> None:
    args = parse_args()
    queries = json.loads(Path(args.queries_json).read_text(encoding="utf-8"))
    if not isinstance(queries, dict) or not queries:
        raise ValueError("queries-json must be a non-empty JSON object")

    start = parse_time(args.start)
    end = parse_time(args.end)
    fault_windows = parse_fault_windows(args.fault_window)

    columns = list(queries.keys())
    rows_by_time: dict[float, dict[str, float | str | int]] = {}
    for column, query in queries.items():
        values = request_query_range(args.prometheus_url, str(query), start, end, args.step)
        for timestamp, value in values:
            row = rows_by_time.setdefault(timestamp, {"timestamp": format_timestamp(timestamp)})
            row[column] = value

    if not rows_by_time:
        raise RuntimeError("all Prometheus queries returned no data")

    for timestamp, row in rows_by_time.items():
        label, fault_type, target_service = labels_for_timestamp(
            timestamp,
            args.label,
            args.fault_type,
            args.target_service,
            fault_windows,
        )
        row["label"] = label
        row["fault_type"] = fault_type
        row["target_service"] = target_service

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", *columns, "label", "fault_type", "target_service"]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for timestamp in sorted(rows_by_time):
            row = rows_by_time[timestamp]
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    print(f"wrote {output_path} with {len(rows_by_time)} rows")


if __name__ == "__main__":
    main()

