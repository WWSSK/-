import json
import random
import re
from pathlib import Path
from collections import Counter, defaultdict
import pandas as pd
import numpy as np

BASE = Path(".")
NEW_CSV = BASE / "metrics.csv"
OLD_CSV = BASE / "metrics_old.csv"
OUT_DIR = BASE / "prelog_metric_combined_v3"
OUT_DIR.mkdir(exist_ok=True, parents=True)

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

NEW_FAULT_WINDOWS = [
    ("2026-06-13 16:24:00", "2026-06-13 16:26:59", "frontend-network-delay"),
    ("2026-06-13 16:36:00", "2026-06-13 16:40:59", "checkout-cpu-stress"),
    ("2026-06-13 16:41:00", "2026-06-13 16:43:59", "cart-pod-kill"),
]

OLD_FAULT_WINDOWS = [
    ("2026-06-12 15:29:00", "2026-06-12 15:30:30", "frontend-network-delay"),
    ("2026-06-12 15:31:30", "2026-06-12 15:33:15", "checkout-cpu-stress"),
    ("2026-06-12 15:35:15", "2026-06-12 15:36:45", "cart-pod-kill"),
]

SERVICES = [
    "frontend", "checkoutservice", "cartservice", "redis-cart",
    "adservice", "currencyservice", "emailservice", "paymentservice",
    "productcatalogservice", "recommendationservice", "shippingservice",
    "loadgenerator",
]
TARGET_SERVICES = {"frontend", "checkoutservice", "cartservice", "redis-cart"}

def parse_bj_time(s):
    return pd.Timestamp(s, tz="Asia/Shanghai")

def parse_windows(windows):
    return [(parse_bj_time(s), parse_bj_time(e), name) for s, e, name in windows]

def pod_to_service(col):
    m = re.search(r'pod="([^"]+)"', str(col))
    pod = m.group(1) if m else str(col)
    for svc in sorted(SERVICES, key=len, reverse=True):
        if pod.startswith(svc):
            return svc
    return pod.split("-")[0]

def clean_numeric(series):
    return pd.to_numeric(series.replace("undefined", np.nan), errors="coerce")

def label_for_time(ts, fault_windows):
    hits = []
    for start, end, name in fault_windows:
        if start <= ts <= end:
            hits.append(name)
    if hits:
        return "faulty", ",".join(hits)
    return "clean normal", ""

def value_bucket(v):
    if pd.isna(v): return "value_missing"
    v = float(v)
    if v >= 0.20: return "value_ge_0p20"
    if v >= 0.15: return "value_ge_0p15"
    if v >= 0.10: return "value_ge_0p10"
    if v >= 0.08: return "value_ge_0p08"
    if v >= 0.04: return "value_ge_0p04"
    if v >= 0.02: return "value_ge_0p02"
    if v >= 0.01: return "value_ge_0p01"
    if v >= 0.005: return "value_ge_0p005"
    return "value_low"

def z_bucket(z):
    if pd.isna(z): return "z_missing"
    if z >= 10: return "z_extreme"
    if z >= 5: return "z_very_high"
    if z >= 3: return "z_high"
    if z >= 2: return "z_elevated"
    if z <= -3: return "z_low"
    return "z_normal"

def trend_token(curr, prev):
    if pd.isna(curr) or pd.isna(prev): return "trend_unknown"
    diff = float(curr) - float(prev)
    if diff > 0.03: return "trend_sharp_up"
    if diff > 0.01: return "trend_up"
    if diff < -0.03: return "trend_sharp_down"
    if diff < -0.01: return "trend_down"
    return "trend_flat"

def build_service_frame(csv_path):
    df = pd.read_csv(csv_path)
    if "Time" not in df.columns:
        raise ValueError(f"{csv_path} has no Time column")
    svc_df = pd.DataFrame()
    svc_df["TimeBJ"] = pd.to_datetime(df["Time"], unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")

    tmp = defaultdict(list)
    for c in df.columns:
        if c == "Time":
            continue
        svc = pod_to_service(c)
        name = f"__{svc}_{len(tmp[svc])}"
        svc_df[name] = clean_numeric(df[c])
        tmp[svc].append(name)

    for svc, cols in tmp.items():
        svc_df[svc] = svc_df[cols].mean(axis=1, skipna=True)

    keep = ["TimeBJ"] + sorted(tmp.keys())
    svc_df = svc_df[keep]
    metric_cols = [c for c in svc_df.columns if c != "TimeBJ"]
    svc_df = svc_df[svc_df[metric_cols].notna().any(axis=1)].reset_index(drop=True)
    return svc_df

def compute_baseline(svc_df, fault_windows):
    labels = svc_df["TimeBJ"].apply(lambda t: label_for_time(t, fault_windows)[0])
    normal_mask = labels == "clean normal"
    baseline = {}
    for svc in [c for c in svc_df.columns if c != "TimeBJ"]:
        vals = svc_df.loc[normal_mask, svc].dropna()
        if len(vals) == 0:
            med, mad = 0.0, 1e-6
        else:
            med = float(vals.median())
            mad = float((vals - med).abs().median())
            if mad < 1e-6:
                std = float(vals.std()) if len(vals) > 1 else 0.0
                mad = std if std > 1e-6 else 1e-6
        baseline[svc] = (med, mad)
    return baseline

def row_tokens(row, prev_row, baseline):
    metric_cols = [c for c in row.index if c != "TimeBJ"]
    vals = [(svc, float(row[svc])) for svc in metric_cols if not pd.isna(row[svc])]
    top_services = {svc for svc, _ in sorted(vals, key=lambda x: x[1], reverse=True)[:5]}

    tokens = ["metric_event_log", "system_online_boutique"]
    tokens += [f"top_{svc}" for svc in sorted(top_services)]

    for svc in sorted(metric_cols):
        v = row[svc]
        if pd.isna(v):
            continue
        med, mad = baseline.get(svc, (0.0, 1e-6))
        z = (float(v) - med) / (1.4826 * mad + 1e-9)
        prev_v = prev_row[svc] if prev_row is not None and svc in prev_row.index else np.nan

        include = svc in TARGET_SERVICES or svc in top_services or z >= 2
        if not include:
            continue

        tokens += [
            f"service_{svc}",
            value_bucket(v),
            z_bucket(z),
            trend_token(v, prev_v),
        ]
        if z >= 3:
            tokens.append(f"spike_{svc}")
        if float(v) >= max(0.02, med * 3):
            tokens.append(f"surge_{svc}")
    return tokens

def build_records(csv_path, fault_windows, source):
    svc_df = build_service_frame(csv_path)
    baseline = compute_baseline(svc_df, fault_windows)

    per_row_tokens = []
    prev = None
    for _, row in svc_df.iterrows():
        per_row_tokens.append(row_tokens(row, prev, baseline))
        prev = row

    rows = []
    for i, row in svc_df.iterrows():
        label, fault_type = label_for_time(row["TimeBJ"], fault_windows)

        ctx_tokens = []
        for j in [i - 1, i, i + 1]:
            if 0 <= j < len(per_row_tokens):
                ctx_tokens.extend([f"ctx{j-i}_{tok}" for tok in per_row_tokens[j]])

        rows.append({
            "text": " ".join(ctx_tokens),
            "labels": label,
            "timestamp": row["TimeBJ"].strftime("%Y-%m-%d %H:%M:%S"),
            "fault_type": fault_type,
            "source": source,
        })
    return rows

def stratified_split(rows, ratio=0.7):
    normal = [r for r in rows if r["labels"] == "clean normal"]
    faulty = [r for r in rows if r["labels"] == "faulty"]
    random.shuffle(normal)
    random.shuffle(faulty)

    def split_one(items):
        if len(items) <= 1:
            return items, []
        n = int(len(items) * ratio)
        n = max(1, min(n, len(items) - 1))
        return items[:n], items[n:]

    ntr, nts = split_one(normal)
    ftr, fts = split_one(faulty)
    train = ntr + ftr
    test = nts + fts
    random.shuffle(train)
    random.shuffle(test)
    return train, test

def oversample_train(train):
    normal = [r for r in train if r["labels"] == "clean normal"]
    faulty = [r for r in train if r["labels"] == "faulty"]
    if not normal or not faulty:
        return train
    if len(normal) > len(faulty):
        faulty = faulty + random.choices(faulty, k=len(normal) - len(faulty))
    elif len(faulty) > len(normal):
        normal = normal + random.choices(normal, k=len(faulty) - len(normal))
    out = normal + faulty
    random.shuffle(out)
    return out

def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"text": r["text"], "labels": r["labels"]}, ensure_ascii=False) + "\n")

if not NEW_CSV.exists():
    raise SystemExit("metrics.csv not found")
if not OLD_CSV.exists():
    raise SystemExit("metrics_old.csv not found")

new_records = build_records(NEW_CSV, parse_windows(NEW_FAULT_WINDOWS), "new")
old_records = build_records(OLD_CSV, parse_windows(OLD_FAULT_WINDOWS), "old")

print("new records:", len(new_records), Counter(r["labels"] for r in new_records))
print("old records:", len(old_records), Counter(r["labels"] for r in old_records))

new_train, new_test = stratified_split(new_records, 0.7)
old_train, old_test = stratified_split(old_records, 0.7)

train = oversample_train(new_train + old_train)
test = new_test + old_test
random.shuffle(test)

write_jsonl(OUT_DIR / "train.json", train)
write_jsonl(OUT_DIR / "test.json", test)

with open(OUT_DIR / "all_timeline.json", "w", encoding="utf-8") as f:
    json.dump(sorted(new_records + old_records, key=lambda r: (r["source"], r["timestamp"])), f, ensure_ascii=False, indent=2)

print("final train:", len(train), Counter(r["labels"] for r in train))
print("final test:", len(test), Counter(r["labels"] for r in test))
print("saved:")
print(" ", OUT_DIR / "train.json")
print(" ", OUT_DIR / "test.json")
print(" ", OUT_DIR / "all_timeline.json")
