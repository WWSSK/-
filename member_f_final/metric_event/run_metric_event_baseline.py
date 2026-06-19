import json
from pathlib import Path
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, f1_score


def find_data_dir():
    candidates = [
        Path("prelog_metric_combined_v3"),
        Path("/mnt/e/software_test_project/online_boutique_logs/prelog_metric_combined_v3"),
        Path("/mnt/e/software_test_project/PreLog/tasks/classification/prelog_metric_combined_v3"),
    ]
    for p in candidates:
        if (p / "train.json").exists() and (p / "test.json").exists():
            return p
    raise FileNotFoundError(
        "Cannot find prelog_metric_combined_v3/train.json and test.json. "
        "Please run this script from online_boutique_logs or check the data path."
    )


def load_jsonl(path):
    X, y = [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            X.append(obj["text"])
            y.append(obj["labels"])
    return X, y


def main():
    data_dir = find_data_dir()
    train_path = data_dir / "train.json"
    test_path = data_dir / "test.json"

    out_dir = data_dir.parent / "baseline_results"
    out_dir.mkdir(exist_ok=True)

    X_train, y_train = load_jsonl(train_path)
    X_test, y_test = load_jsonl(test_path)

    print("=" * 80)
    print("Metric-Event Baseline: TF-IDF + Logistic Regression")
    print("data_dir:", data_dir)
    print("train:", len(X_train), Counter(y_train))
    print("test :", len(X_test), Counter(y_test))

    vectorizer = TfidfVectorizer(
        token_pattern=r"(?u)\b[\w\-]+\b",
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
        sublinear_tf=True,
    )

    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    clf = LogisticRegression(
        max_iter=3000,
        class_weight="balanced",
        random_state=42,
        solver="liblinear",
    )

    clf.fit(X_train_vec, y_train)
    pred = clf.predict(X_test_vec)
    proba = clf.predict_proba(X_test_vec)

    report = classification_report(y_test, pred, digits=3, zero_division=0)
    cm = confusion_matrix(y_test, pred, labels=["clean normal", "faulty"])

    print("\nclassification report:")
    print(report)
    print("confusion matrix [clean normal, faulty]:")
    print(cm)

    print("accuracy:", round(accuracy_score(y_test, pred), 4))
    print("macro_f1:", round(f1_score(y_test, pred, average="macro"), 4))
    print("faulty_f1:", round(f1_score(y_test, pred, labels=["faulty"], average="macro"), 4))

    feature_names = vectorizer.get_feature_names_out()
    classes = list(clf.classes_)
    coef = clf.coef_[0]
    if len(classes) == 2 and classes[1] != "faulty":
        coef = -coef

    top_faulty = coef.argsort()[-30:][::-1]
    top_normal = coef.argsort()[:30]

    print("\nTop faulty features:")
    top_faulty_lines = []
    for i in top_faulty:
        line = f"{feature_names[i]}\t{float(coef[i]):.4f}"
        top_faulty_lines.append(line)
        print(line)

    print("\nTop normal features:")
    top_normal_lines = []
    for i in top_normal:
        line = f"{feature_names[i]}\t{float(coef[i]):.4f}"
        top_normal_lines.append(line)
        print(line)

    report_path = out_dir / "metric_event_baseline_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Metric-Event Baseline: TF-IDF + Logistic Regression\n")
        f.write(f"data_dir: {data_dir}\n")
        f.write(f"train: {len(X_train)} {Counter(y_train)}\n")
        f.write(f"test : {len(X_test)} {Counter(y_test)}\n\n")
        f.write("classification report:\n")
        f.write(report + "\n")
        f.write("confusion matrix [clean normal, faulty]:\n")
        f.write(str(cm) + "\n\n")
        f.write(f"accuracy: {accuracy_score(y_test, pred):.4f}\n")
        f.write(f"macro_f1: {f1_score(y_test, pred, average='macro'):.4f}\n")
        f.write(f"faulty_f1: {f1_score(y_test, pred, labels=['faulty'], average='macro'):.4f}\n\n")
        f.write("Top faulty features:\n")
        f.write("\n".join(top_faulty_lines) + "\n\n")
        f.write("Top normal features:\n")
        f.write("\n".join(top_normal_lines) + "\n")

    pred_path = out_dir / "metric_event_baseline_predictions.csv"
    class_to_idx = {c: i for i, c in enumerate(classes)}
    with open(pred_path, "w", encoding="utf-8") as f:
        f.write("idx,true_label,pred_label,prob_clean_normal,prob_faulty,text_preview\n")
        for idx, (true, p, prob, text) in enumerate(zip(y_test, pred, proba, X_test)):
            p_clean = prob[class_to_idx["clean normal"]] if "clean normal" in class_to_idx else 0.0
            p_faulty = prob[class_to_idx["faulty"]] if "faulty" in class_to_idx else 0.0
            preview = text[:200].replace(",", " ").replace("\n", " ")
            f.write(f"{idx},{true},{p},{p_clean:.6f},{p_faulty:.6f},{preview}\n")

    print("\nSaved:")
    print(report_path)
    print(pred_path)


if __name__ == "__main__":
    main()
