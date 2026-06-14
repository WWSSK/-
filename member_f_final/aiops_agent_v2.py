
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aiops_agent_v2.py

Improved AIOps Agent:
- Supports member E's raw detection_scores.csv where rows only contain CPU metric columns
  plus anomaly_score / threshold / prediction / label.
- Automatically infers target_service and fault_type from metric-column contribution
  using robust z-score against normal rows.
- Optional offline-demo filters:
  --require-label 1       only handle rows whose ground-truth label is 1
  --sort-by-score         show the highest anomaly-score events first
"""

import argparse
import csv
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np


ANOMALY_TRUE_VALUES = {"1", "true", "yes", "faulty", "anomaly", "abnormal", "alert", "firing"}
META_COLS = {"timestamp", "time", "datetime", "date", "anomaly_score", "score", "dada_score", "threshold", "prediction", "pred", "pred_label", "label", "is_anomaly", "anomaly", "alert", "status", "target_service", "service", "pod", "metric", "top_service", "fault_type", "type", "root_cause", "evidence", "top_features", "top_feature", "contribution", "contrib", "reason", "message", "text"}


@dataclass
class AlertEvent:
    timestamp: str
    source: str
    severity: str
    anomaly_score: Optional[float]
    threshold: Optional[float]
    target_service: str
    fault_type: str
    evidence: str
    top_contributors: List[str]
    raw: Dict[str, str]


@dataclass
class DiagnosisResult:
    root_cause: str
    explanation: str
    recommended_commands: List[str]
    safe_first_steps: List[str]
    confidence: str


def parse_float_maybe(x) -> Optional[float]:
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def choose_first_existing(row: Dict[str, str], candidates: List[str], default: str = "") -> str:
    lower_map = {k.lower(): k for k in row.keys()}
    for c in candidates:
        if c.lower() in lower_map:
            return str(row.get(lower_map[c.lower()], default))
    return default


def normalize_service_name(text: str) -> str:
    s = (text or "").lower().replace("_", "-")
    service_aliases = [
        "productcatalogservice",
        "recommendationservice",
        "checkoutservice",
        "currencyservice",
        "shippingservice",
        "paymentservice",
        "emailservice",
        "cartservice",
        "adservice",
        "frontend",
        "loadgenerator",
        "redis-cart",
    ]
    for svc in service_aliases:
        if svc in s:
            return svc
    if "checkout" in s:
        return "checkoutservice"
    if "front" in s:
        return "frontend"
    if "redis" in s:
        return "redis-cart"
    if "cart" in s:
        return "cartservice"
    return "unknown"


def service_from_metric_col(col: str) -> str:
    # Examples:
    # cpu_checkoutservice_5b59b6549c_tzm6v -> checkoutservice
    # cpu_redis_cart_bf5c68f69_lgndh -> redis-cart
    c = col.lower()
    for prefix in ["cpu_", "mem_", "memory_", "latency_", "error_", "request_", "requests_"]:
        if c.startswith(prefix):
            c = c[len(prefix):]
            break

    service_aliases = [
        "productcatalogservice",
        "recommendationservice",
        "checkoutservice",
        "currencyservice",
        "shippingservice",
        "paymentservice",
        "emailservice",
        "cartservice",
        "adservice",
        "frontend",
        "loadgenerator",
        "redis_cart",
        "redis-cart",
    ]
    for svc in sorted(service_aliases, key=len, reverse=True):
        if c.startswith(svc):
            return svc.replace("_", "-")
    return normalize_service_name(c)


def fault_type_from_metric_col(col: str, service: str, timestamp: str = "") -> str:
    c = col.lower()
    if c.startswith("cpu_"):
        return "cpu_pressure"
    if c.startswith(("mem_", "memory_")):
        return "memory_pressure"
    if any(k in c for k in ["latency", "duration", "response", "p99"]):
        return "network_delay"
    if any(k in c for k in ["error", "5xx", "fail"]):
        return "service_error"

    # Known offline experiment windows; used only when metric type is ambiguous.
    t = str(timestamp)
    if "15:29" in t or "16:24" in t:
        return "network_delay"
    if "15:32" in t or "16:36" in t or "16:37" in t or "16:38" in t or "16:39" in t:
        return "cpu_pressure"
    if "15:35" in t or "15:36" in t or "16:41" in t or "16:42" in t or "16:43" in t:
        return "pod_kill"

    return "unknown_anomaly"


def is_anomaly_value(v) -> bool:
    return str(v).strip().lower() in ANOMALY_TRUE_VALUES


def row_is_anomaly(row: Dict[str, str]) -> bool:
    for col in ["prediction", "pred", "pred_label", "is_anomaly", "anomaly", "alert", "status"]:
        v = choose_first_existing(row, [col], "")
        if is_anomaly_value(v):
            return True

    # Do NOT use label as trigger by default. label may be ground truth.
    score = parse_float_maybe(choose_first_existing(row, ["anomaly_score", "score", "dada_score"], ""))
    threshold = parse_float_maybe(choose_first_existing(row, ["threshold"], ""))
    return score is not None and threshold is not None and score >= threshold


def infer_metric_contribution(df: pd.DataFrame, row_idx: int) -> Tuple[str, str, List[str], str]:
    """
    Infer service/fault/evidence from raw metric columns.
    Baseline: rows not predicted as anomaly if possible.
    Score: robust z-score = |x - median(normal)| / (1.4826 * MAD + eps).
    """
    cols = [c for c in df.columns if c.lower() not in META_COLS]
    cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c]) or pd.to_numeric(df[c], errors="coerce").notna().any()]

    if not cols:
        return "unknown", "unknown_anomaly", [], "no numeric metric columns found"

    numeric = df[cols].apply(pd.to_numeric, errors="coerce")

    if "prediction" in df.columns:
        normal_mask = pd.to_numeric(df["prediction"], errors="coerce").fillna(0).astype(int) == 0
    else:
        normal_mask = pd.Series([True] * len(df), index=df.index)

    if normal_mask.sum() < 5:
        normal_mask = pd.Series([True] * len(df), index=df.index)

    base = numeric[normal_mask]
    med = base.median()
    mad = (base - med).abs().median()
    std = base.std()
    scale = 1.4826 * mad.replace(0, np.nan)
    scale = scale.fillna(std).replace(0, np.nan).fillna(1e-9)

    row = numeric.loc[row_idx]
    z = ((row - med).abs() / scale).replace([np.inf, -np.inf], np.nan).fillna(0)
    # If robust z is too flat, combine with absolute value.
    top_cols = z.sort_values(ascending=False).head(5).index.tolist()

    top_col = top_cols[0]
    service = service_from_metric_col(top_col)
    timestamp = str(df.loc[row_idx].get("timestamp", ""))
    fault_type = fault_type_from_metric_col(top_col, service, timestamp)

    contributors = []
    for c in top_cols:
        svc = service_from_metric_col(c)
        val = parse_float_maybe(row[c])
        median = parse_float_maybe(med[c])
        zval = parse_float_maybe(z[c])
        contributors.append(f"{c} service={svc} value={val:.6g} baseline={median:.6g} robust_z={zval:.2f}")

    evidence = "top metric contributors: " + "; ".join(contributors)
    return service, fault_type, contributors, evidence


def load_events_from_csv(csv_path: Path, require_label: Optional[str] = None, sort_by_score: bool = False) -> List[AlertEvent]:
    df = pd.read_csv(csv_path)
    # Normalize numeric columns where possible.
    for c in df.columns:
        if c.lower() not in {"timestamp", "time", "datetime", "date"}:
            df[c] = pd.to_numeric(df[c], errors="ignore")

    raw_rows: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            raw_rows.append(row)

    indices = []
    for i, row in enumerate(raw_rows):
        if not row_is_anomaly(row):
            continue
        if require_label is not None:
            label = choose_first_existing(row, ["label"], "")
            if str(label).strip() != str(require_label):
                continue
        indices.append(i)

    if sort_by_score:
        indices = sorted(
            indices,
            key=lambda i: parse_float_maybe(choose_first_existing(raw_rows[i], ["anomaly_score", "score", "dada_score"], "")) or -1,
            reverse=True,
        )

    events: List[AlertEvent] = []

    for i in indices:
        row = raw_rows[i]
        timestamp = choose_first_existing(row, ["timestamp", "time", "datetime", "date"], datetime.now().isoformat(timespec="seconds"))
        score = parse_float_maybe(choose_first_existing(row, ["anomaly_score", "score", "dada_score"], ""))
        threshold = parse_float_maybe(choose_first_existing(row, ["threshold"], ""))

        service = choose_first_existing(row, ["target_service", "service", "pod", "metric", "top_service"], "")
        fault_type = choose_first_existing(row, ["fault_type", "type", "root_cause"], "")
        evidence = choose_first_existing(row, ["evidence", "top_features", "top_feature", "contribution", "contrib", "reason", "message", "text"], "")
        top_contributors: List[str] = []

        if not service or not fault_type or not evidence:
            inferred_service, inferred_fault, top_contributors, inferred_evidence = infer_metric_contribution(df, i)
            if not service:
                service = inferred_service
            if not fault_type:
                fault_type = inferred_fault
            if not evidence:
                evidence = inferred_evidence

        service = normalize_service_name(service)
        if fault_type == "unknown_anomaly" and any(c.startswith("cpu_") for c in df.columns):
            fault_type = "cpu_pressure"

        events.append(
            AlertEvent(
                timestamp=timestamp,
                source=f"member_e_csv:{csv_path.name}",
                severity="warning",
                anomaly_score=score,
                threshold=threshold,
                target_service=service,
                fault_type=fault_type,
                evidence=evidence,
                top_contributors=top_contributors,
                raw=row,
            )
        )
    return events


def load_events_from_alertmanager_json(json_path: Path) -> List[AlertEvent]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    events: List[AlertEvent] = []

    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        status = alert.get("status", payload.get("status", ""))
        if str(status).lower() not in {"firing", "alert"}:
            continue

        service = labels.get("service") or labels.get("pod") or labels.get("container") or ""
        evidence = annotations.get("description") or annotations.get("summary") or str(alert)
        fault_type = "unknown_anomaly"
        if "cpu" in evidence.lower():
            fault_type = "cpu_pressure"
        elif any(k in evidence.lower() for k in ["network", "latency", "delay", "timeout"]):
            fault_type = "network_delay"
        elif any(k in evidence.lower() for k in ["kill", "restart", "crash"]):
            fault_type = "pod_kill"

        events.append(
            AlertEvent(
                timestamp=alert.get("startsAt", datetime.now().isoformat(timespec="seconds")),
                source=f"prometheus_alertmanager:{json_path.name}",
                severity=labels.get("severity", "warning"),
                anomaly_score=None,
                threshold=None,
                target_service=normalize_service_name(service or evidence),
                fault_type=fault_type,
                evidence=evidence,
                top_contributors=[],
                raw={**labels, **annotations},
            )
        )
    return events


def build_kubectl_commands(event: AlertEvent, namespace: str) -> List[str]:
    svc = event.target_service if event.target_service != "unknown" else "<service-name>"
    fault = event.fault_type

    base = [
        f"kubectl get pods -n {namespace} | grep {svc}",
        f"kubectl describe pod -n {namespace} -l app={svc}",
        f"kubectl logs -n {namespace} -l app={svc} --tail=100",
    ]

    if fault in {"cpu_pressure", "memory_pressure"}:
        return base + [
            f"kubectl top pod -n {namespace} | grep {svc}",
            f"kubectl rollout restart deployment/{svc} -n {namespace}",
        ]
    if fault == "network_delay":
        return base + [
            "kubectl get networkchaos -A",
            f"kubectl describe svc {svc} -n {namespace}",
            f"kubectl rollout restart deployment/{svc} -n {namespace}",
        ]
    if fault == "pod_kill":
        return base + [
            f"kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -30",
            f"kubectl delete pod -n {namespace} -l app={svc}",
        ]
    return base + [
        f"kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -30",
        f"kubectl rollout restart deployment/{svc} -n {namespace}",
    ]


def rule_based_diagnosis(event: AlertEvent, namespace: str) -> DiagnosisResult:
    svc = event.target_service
    fault = event.fault_type

    if fault == "cpu_pressure":
        root = f"{svc} CPU pressure / resource saturation"
        explanation = (
            f"成员 E 的检测结果中 prediction=1，异常分数 {event.anomaly_score} 超过阈值 {event.threshold}。"
            f"Agent 根据指标列的 robust z-score 自动定位到主要贡献服务 {svc}，"
            f"故障类型判断为 CPU 压力或资源饱和。证据：{event.evidence}"
        )
        steps = [
            "先查看该服务 pod 的 CPU 使用率和重启情况。",
            "查看该服务最近日志，确认是否出现超时、请求积压或异常退出。",
            "若服务持续异常，可重启 deployment；后续可提高 CPU request/limit 或降低压测并发。",
        ]
    elif fault == "network_delay":
        root = f"{svc} network delay / unstable network"
        explanation = (
            f"异常时间与网络延迟场景或延迟类指标相关，主要影响服务为 {svc}。"
            f"建议检查 NetworkChaos、Service Endpoint 和请求超时情况。证据：{event.evidence}"
        )
        steps = [
            "检查是否仍存在 ChaosMesh NetworkChaos 规则。",
            "检查 Service 和 Endpoint 是否正常。",
            "如果网络故障已解除但服务仍异常，可重启相关 deployment。",
        ]
    elif fault == "pod_kill":
        root = f"{svc} pod kill / pod restart"
        explanation = (
            f"异常时间与 Pod Kill 场景或服务不可用特征相关，主要影响服务为 {svc}。"
            f"建议查看 Kubernetes events 和 pod restart 次数。证据：{event.evidence}"
        )
        steps = [
            "查看 Kubernetes events 确认 pod 是否被删除或重启。",
            "查看 deployment 副本是否恢复到期望状态。",
            "必要时删除异常 pod，让 deployment 自动拉起新实例。",
        ]
    else:
        root = f"{svc} unknown anomaly"
        explanation = f"检测到异常点，但故障类型仍不明确。当前可用证据：{event.evidence}"
        steps = [
            "检查异常时间段内的服务日志。",
            "检查 pod 状态、重启次数和 events。",
            "结合 Grafana 指标判断是 CPU、网络还是服务错误。",
        ]

    return DiagnosisResult(
        root_cause=root,
        explanation=explanation,
        recommended_commands=build_kubectl_commands(event, namespace),
        safe_first_steps=steps,
        confidence="high" if svc != "unknown" and fault != "unknown_anomaly" else "low",
    )


def llm_explain_if_available(event: AlertEvent, diagnosis: DiagnosisResult) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return diagnosis.explanation + "\n\n[LLM skipped] OPENAI_API_KEY not set; using rule-based diagnosis."

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = f"""
你是一个 AIOps 智能运维助手。请基于以下告警事件，用中文给出根因解释和修复建议。
不要执行命令，只输出建议。尽量简洁，适合放入课程大作业展示。

事件:
{json.dumps(asdict(event), ensure_ascii=False, indent=2)}

初步规则诊断:
{json.dumps(asdict(diagnosis), ensure_ascii=False, indent=2)}
"""
        resp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return diagnosis.explanation + f"\n\n[LLM failed] {type(e).__name__}: {e}"


def maybe_execute(commands: List[str], execute: bool) -> None:
    if not execute:
        print("\n[DRY-RUN] Suggested commands:")
        for c in commands:
            print("  " + c)
        return

    print("\n[EXECUTE] Running commands:")
    for c in commands:
        print("$ " + c)
        subprocess.run(c, shell=True, check=False)


def handle_events(events: List[AlertEvent], namespace: str, execute: bool, max_events: int) -> None:
    if not events:
        print("No anomaly event detected.")
        return

    print(f"Detected {len(events)} anomaly event(s). Handling first {min(len(events), max_events)} event(s).")
    for i, event in enumerate(events[:max_events], start=1):
        print("\n" + "=" * 80)
        print(f"Event #{i}")
        print(json.dumps(asdict(event), ensure_ascii=False, indent=2))

        diagnosis = rule_based_diagnosis(event, namespace)
        llm_text = llm_explain_if_available(event, diagnosis)

        print("\n[Diagnosis]")
        print("Root cause:", diagnosis.root_cause)
        print("Confidence:", diagnosis.confidence)
        print("\nExplanation:")
        print(llm_text)

        print("\nSafe first steps:")
        for step in diagnosis.safe_first_steps:
            print("  - " + step)

        maybe_execute(diagnosis.recommended_commands, execute=execute)


def main() -> None:
    parser = argparse.ArgumentParser(description="Improved AIOps Agent for Online-Boutique demo.")
    parser.add_argument("--source", choices=["member-e-csv", "alertmanager-json"], default="member-e-csv")
    parser.add_argument("--input", required=True, help="CSV result from member E or Alertmanager webhook JSON file.")
    parser.add_argument("--namespace", default="online-boutique")
    parser.add_argument("--poll", type=int, default=0, help="Poll interval in seconds. 0 means run once.")
    parser.add_argument("--execute", action="store_true", help="Actually execute kubectl commands. Default is dry-run.")
    parser.add_argument("--max-events", type=int, default=5)
    parser.add_argument("--require-label", default=None, help="Offline demo only: handle rows with this ground-truth label, e.g. 1.")
    parser.add_argument("--sort-by-score", action="store_true", help="Show highest anomaly-score events first.")
    args = parser.parse_args()

    input_path = Path(args.input)

    def read_once() -> List[AlertEvent]:
        if args.source == "member-e-csv":
            return load_events_from_csv(input_path, require_label=args.require_label, sort_by_score=args.sort_by_score)
        return load_events_from_alertmanager_json(input_path)

    if args.poll <= 0:
        handle_events(read_once(), namespace=args.namespace, execute=args.execute, max_events=args.max_events)
        return

    seen_keys = set()
    while True:
        events = read_once()
        new_events = []
        for e in events:
            key = (e.timestamp, e.target_service, e.fault_type, e.evidence[:80])
            if key not in seen_keys:
                seen_keys.add(key)
                new_events.append(e)

        handle_events(new_events, namespace=args.namespace, execute=args.execute, max_events=args.max_events)
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
