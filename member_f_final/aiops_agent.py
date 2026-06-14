#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aiops_agent.py

A lightweight AIOps Agent for the software testing & maintenance project.

Recommended trigger:
    Watch member E's DADA-Lite / KPI anomaly detection CSV result.
    When prediction == 1 or label == faulty/anomaly, generate diagnosis and kubectl repair suggestions.

Optional trigger:
    Accept a Prometheus Alertmanager webhook payload JSON file for offline demo.

Default behavior is DRY-RUN: it only prints suggested commands and does not execute kubectl.
"""

import argparse
import csv
import json
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


ANOMALY_TRUE_VALUES = {"1", "true", "yes", "faulty", "anomaly", "abnormal", "alert", "firing"}


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
    raw: Dict[str, str]


@dataclass
class DiagnosisResult:
    root_cause: str
    explanation: str
    recommended_commands: List[str]
    safe_first_steps: List[str]
    confidence: str


def normalize_service_name(text: str) -> str:
    s = (text or "").lower()
    service_aliases = [
        "checkoutservice",
        "frontend",
        "cartservice",
        "productcatalogservice",
        "recommendationservice",
        "currencyservice",
        "paymentservice",
        "shippingservice",
        "emailservice",
        "adservice",
        "redis-cart",
        "loadgenerator",
    ]
    for svc in service_aliases:
        if svc in s:
            return svc
    if "checkout" in s:
        return "checkoutservice"
    if "front" in s:
        return "frontend"
    if "cart" in s or "redis" in s:
        return "cartservice"
    if "product" in s:
        return "productcatalogservice"
    return "unknown"


def infer_fault_type(row: Dict[str, str], evidence_text: str) -> str:
    blob = " ".join(str(v) for v in row.values()) + " " + evidence_text
    blob = blob.lower()

    if any(k in blob for k in ["cpu", "cpu_pressure", "cpu-stress", "stress", "z_extreme", "surge"]):
        return "cpu_pressure"
    if any(k in blob for k in ["network", "delay", "latency", "timeout", "loss", "network_loss"]):
        return "network_delay"
    if any(k in blob for k in ["pod_kill", "pod-kill", "kill", "restart", "crash", "unavailable"]):
        return "pod_kill"
    if any(k in blob for k in ["error", "5xx", "exception", "failed"]):
        return "service_error"
    return "unknown_anomaly"


def choose_first_existing(row: Dict[str, str], candidates: List[str], default: str = "") -> str:
    lower_map = {k.lower(): k for k in row.keys()}
    for c in candidates:
        if c.lower() in lower_map:
            return str(row.get(lower_map[c.lower()], default))
    return default


def parse_float_maybe(x: str) -> Optional[float]:
    try:
        if x is None or str(x).strip() == "":
            return None
        return float(x)
    except Exception:
        return None


def is_anomaly_row(row: Dict[str, str]) -> bool:
    for col in ["prediction", "pred", "pred_label", "label", "is_anomaly", "anomaly", "alert", "status"]:
        v = choose_first_existing(row, [col], "")
        if str(v).strip().lower() in ANOMALY_TRUE_VALUES:
            return True

    score = parse_float_maybe(choose_first_existing(row, ["anomaly_score", "score", "dada_score"], ""))
    threshold = parse_float_maybe(choose_first_existing(row, ["threshold"], ""))
    if score is not None and threshold is not None and score >= threshold:
        return True

    return False


def load_events_from_csv(csv_path: Path) -> List[AlertEvent]:
    events: List[AlertEvent] = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header")

        for row in reader:
            if not is_anomaly_row(row):
                continue

            timestamp = choose_first_existing(
                row,
                ["timestamp", "time", "Time", "datetime", "date"],
                datetime.now().isoformat(timespec="seconds"),
            )
            score = parse_float_maybe(choose_first_existing(row, ["anomaly_score", "score", "dada_score"], ""))
            threshold = parse_float_maybe(choose_first_existing(row, ["threshold"], ""))

            evidence = choose_first_existing(
                row,
                ["evidence", "top_features", "top_feature", "contribution", "contrib", "reason", "message", "text"],
                "",
            )

            service = choose_first_existing(row, ["target_service", "service", "pod", "metric", "top_service"], "")
            if not service:
                service = normalize_service_name(" ".join(str(v) for v in row.values()))

            fault_type = choose_first_existing(row, ["fault_type", "type", "root_cause"], "")
            if not fault_type:
                fault_type = infer_fault_type(row, evidence)

            events.append(
                AlertEvent(
                    timestamp=timestamp,
                    source=f"member_e_csv:{csv_path.name}",
                    severity="warning",
                    anomaly_score=score,
                    threshold=threshold,
                    target_service=normalize_service_name(service) if service else "unknown",
                    fault_type=fault_type,
                    evidence=evidence or str(row),
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
        fault_type = infer_fault_type({**labels, **annotations}, evidence)

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

    if fault == "cpu_pressure":
        return base + [
            f"kubectl top pod -n {namespace} | grep {svc}",
            f"kubectl rollout restart deployment/{svc} -n {namespace}",
        ]

    if fault == "network_delay":
        return base + [
            f"kubectl get networkchaos -A",
            f"kubectl describe svc {svc} -n {namespace}",
            f"kubectl rollout restart deployment/{svc} -n {namespace}",
        ]

    if fault == "pod_kill":
        return base + [
            f"kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -30",
            f"kubectl delete pod -n {namespace} -l app={svc}",
        ]

    if fault == "service_error":
        return base + [
            f"kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -30",
            f"kubectl rollout restart deployment/{svc} -n {namespace}",
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
            f"成员 E 的异常检测结果触发告警，主要异常服务为 {svc}。"
            f"证据中出现 CPU、surge、z_extreme 或 checkoutservice 等高贡献特征，"
            f"说明该服务可能处于 CPU 过载或计算瓶颈状态。"
        )
        steps = [
            "先查看 pod CPU 使用率和最近事件，确认是否存在 CPU 尖峰。",
            "如果服务持续无响应，可以重启对应 deployment。",
            "后续优化建议：提高 CPU limit/request，或减少压测并发。",
        ]
    elif fault == "network_delay":
        root = f"{svc} network delay / unstable network"
        explanation = (
            f"异常结果与 {svc} 相关，故障类型被判断为网络延迟。"
            f"这通常对应 ChaosMesh NetworkChaos、请求超时、响应时间升高或前端访问变慢。"
        )
        steps = [
            "检查是否仍存在 NetworkChaos 规则。",
            "检查 service endpoint 和 pod 网络状态。",
            "如服务恢复后仍异常，可重启相关 deployment。",
        ]
    elif fault == "pod_kill":
        root = f"{svc} pod kill / pod restart"
        explanation = (
            f"异常结果与 {svc} 相关，故障类型被判断为 Pod Kill 或实例重启。"
            f"这通常会导致瞬时不可用、请求失败和 Kubernetes 事件中出现 Killing/Restart。"
        )
        steps = [
            "查看 Kubernetes events 确认 pod 是否被删除或重启。",
            "查看 deployment 副本是否恢复到期望状态。",
            "必要时删除异常 pod 让 deployment 自动拉起新实例。",
        ]
    else:
        root = f"{svc} unknown anomaly"
        explanation = "检测到异常点，但故障类型不明确。建议结合指标贡献、服务日志和 Kubernetes events 进一步定位。"
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
        confidence="medium" if svc != "unknown" else "low",
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
要求：不要执行命令，只输出建议。尽量简洁，适合放到课程大作业展示中。

事件：
{json.dumps(asdict(event), ensure_ascii=False, indent=2)}

初步规则诊断：
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
    parser = argparse.ArgumentParser(description="A lightweight AIOps Agent for Online-Boutique demo.")
    parser.add_argument("--source", choices=["member-e-csv", "alertmanager-json"], default="member-e-csv")
    parser.add_argument("--input", required=True, help="CSV result from member E or Alertmanager webhook JSON file.")
    parser.add_argument("--namespace", default="online-boutique")
    parser.add_argument("--poll", type=int, default=0, help="Poll interval in seconds. 0 means run once.")
    parser.add_argument("--execute", action="store_true", help="Actually execute kubectl commands. Default is dry-run.")
    parser.add_argument("--max-events", type=int, default=3)
    args = parser.parse_args()

    input_path = Path(args.input)

    def read_once() -> List[AlertEvent]:
        if args.source == "member-e-csv":
            return load_events_from_csv(input_path)
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
