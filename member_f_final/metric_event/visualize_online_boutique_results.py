import json
import re
from pathlib import Path
from collections import Counter

import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay


BASE = Path("/mnt/e/software_test_project/online_boutique_logs")
DATA_DIR = BASE / "prelog_metric_combined_v3"
RESULT_DIR = BASE / "baseline_results"
FIG_DIR = BASE / "figures"
FIG_DIR.mkdir(exist_ok=True, parents=True)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def parse_feature_section(report_text, title, max_n=15):
    if title not in report_text:
        return []

    part = report_text.split(title, 1)[1]
    for stop in ["Top normal features:", "Top faulty features:"]:
        if stop != title and stop in part:
            part = part.split(stop, 1)[0]

    items = []
    for line in part.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"(.+?)\s+(-?\d+(?:\.\d+)?)$", line)
        if m:
            items.append((m.group(1).strip(), float(m.group(2))))
    return items[:max_n]


def save_label_distribution():
    train = load_jsonl(DATA_DIR / "train.json")
    test = load_jsonl(DATA_DIR / "test.json")

    labels = ["clean normal", "faulty"]
    train_counter = Counter(x["labels"] for x in train)
    test_counter = Counter(x["labels"] for x in test)

    x = range(len(labels))
    width = 0.35

    plt.figure(figsize=(7, 4))
    plt.bar([i - width / 2 for i in x], [train_counter[l] for l in labels], width=width, label="Train")
    plt.bar([i + width / 2 for i in x], [test_counter[l] for l in labels], width=width, label="Test")
    plt.xticks(list(x), labels)
    plt.ylabel("Number of samples")
    plt.title("Label Distribution of Metric-Event Dataset")
    plt.legend()
    plt.tight_layout()
    out = FIG_DIR / "01_label_distribution.png"
    plt.savefig(out, dpi=200)
    plt.close()
    print("saved", out)


def save_confusion_matrix_and_metrics():
    pred_path = RESULT_DIR / "metric_event_baseline_predictions.csv"
    if not pred_path.exists():
        raise FileNotFoundError(f"Missing {pred_path}. Run run_metric_event_baseline.py first.")

    df = pd.read_csv(pred_path)
    labels = ["clean normal", "faulty"]

    cm = confusion_matrix(df["true_label"], df["pred_label"], labels=labels)

    plt.figure(figsize=(5, 4))
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=labels)
    disp.plot(values_format="d")
    plt.title("Confusion Matrix: Metric-Event Baseline")
    plt.tight_layout()
    out = FIG_DIR / "02_confusion_matrix.png"
    plt.savefig(out, dpi=200)
    plt.close()
    print("saved", out)

    report = classification_report(df["true_label"], df["pred_label"], labels=labels, output_dict=True, zero_division=0)

    metric_names = ["precision", "recall", "f1-score"]
    x = range(len(metric_names))
    width = 0.35

    plt.figure(figsize=(7, 4))
    plt.bar([i - width / 2 for i in x], [report["clean normal"][m] for m in metric_names], width=width, label="clean normal")
    plt.bar([i + width / 2 for i in x], [report["faulty"][m] for m in metric_names], width=width, label="faulty")
    plt.xticks(list(x), metric_names)
    plt.ylim(0, 1.05)
    plt.ylabel("Score")
    plt.title("Precision / Recall / F1-score")
    plt.legend()
    plt.tight_layout()
    out = FIG_DIR / "03_metrics_bar.png"
    plt.savefig(out, dpi=200)
    plt.close()
    print("saved", out)

    y_true = df["true_label"].map({"clean normal": 0, "faulty": 1})
    y_pred = df["pred_label"].map({"clean normal": 0, "faulty": 1})

    plt.figure(figsize=(10, 3.5))
    plt.plot(df["idx"], y_true, marker="o", linestyle="-", label="Ground Truth")
    plt.plot(df["idx"], y_pred, marker="x", linestyle="--", label="Prediction")
    plt.yticks([0, 1], ["clean normal", "faulty"])
    plt.xlabel("Test sample index")
    plt.title("Ground Truth vs Prediction by Test Index")
    plt.legend()
    plt.tight_layout()
    out = FIG_DIR / "04_prediction_sequence.png"
    plt.savefig(out, dpi=200)
    plt.close()
    print("saved", out)

    plt.figure(figsize=(7, 4))
    for label in labels:
        subset = df[df["true_label"] == label]
        plt.hist(subset["prob_faulty"], bins=30, alpha=0.65, label=f"true {label}")
    plt.xlabel("Predicted faulty probability")
    plt.ylabel("Number of samples")
    plt.title("Distribution of Faulty Probability")
    plt.legend()
    plt.tight_layout()
    out = FIG_DIR / "05_faulty_probability_distribution.png"
    plt.savefig(out, dpi=200)
    plt.close()
    print("saved", out)


def save_feature_importance():
    report_path = RESULT_DIR / "metric_event_baseline_report.txt"
    if not report_path.exists():
        print(f"skip feature importance: missing {report_path}")
        return

    text = report_path.read_text(encoding="utf-8", errors="ignore")

    for section, filename, title in [
        ("Top faulty features:", "06_top_faulty_features.png", "Top Faulty Features"),
        ("Top normal features:", "07_top_normal_features.png", "Top Normal Features"),
    ]:
        items = parse_feature_section(text, section, max_n=15)
        if not items:
            print(f"skip {section}: no parsed items")
            continue

        names = [x[0] for x in items][::-1]
        values = [x[1] for x in items][::-1]

        plt.figure(figsize=(9, 6))
        plt.barh(names, values)
        plt.xlabel("Logistic regression coefficient")
        plt.title(title)
        plt.tight_layout()
        out = FIG_DIR / filename
        plt.savefig(out, dpi=200)
        plt.close()
        print("saved", out)


def save_true_timeline():
    timeline_path = DATA_DIR / "all_timeline.json"
    if not timeline_path.exists():
        print(f"skip timeline: missing {timeline_path}")
        return

    data = json.loads(timeline_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    if df.empty or "timestamp" not in df.columns:
        print("skip timeline: no timestamp")
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["label_value"] = df["labels"].map({"clean normal": 0, "faulty": 1})

    for source, g in df.groupby("source"):
        g = g.sort_values("timestamp")
        plt.figure(figsize=(10, 3.5))
        plt.plot(g["timestamp"], g["label_value"], marker="o", linestyle="-")
        plt.yticks([0, 1], ["clean normal", "faulty"])
        plt.xlabel("Time")
        plt.title(f"Ground Truth Timeline ({source})")
        plt.tight_layout()
        safe_source = re.sub(r"[^A-Za-z0-9_-]+", "_", str(source))
        out = FIG_DIR / f"08_ground_truth_timeline_{safe_source}.png"
        plt.savefig(out, dpi=200)
        plt.close()
        print("saved", out)


def main():
    print("Output directory:", FIG_DIR)
    save_label_distribution()
    save_confusion_matrix_and_metrics()
    save_feature_importance()
    save_true_timeline()
    print("\nAll figures saved to:", FIG_DIR)


if __name__ == "__main__":
    main()
