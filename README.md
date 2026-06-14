# 🚀 微服务系统部署、自动化测试与智能运维全生命周期实践

**课程名称**：软件测试与维护 (2026春)  
**实验底座**：基于 Google Online-Boutique 的 11 维微服务架构  
**核心目标**：实现“架构集成 -> 自动化测试 -> 混沌故障注入 -> 异常检测 -> 智能体修复”的完整闭环。

---

## 🌟 项目亮点
1. **架构升级（第二档）**：舍弃基础 SockShop，部署复杂度更高的 **Google Online-Boutique**，含 11 个跨语言服务，攻克了国内网络环境下 `gcr.io` 镜像注入与 K8s 版本匹配难题。
2. **自主开发（第三档）**：由成员 B 自研 **Points Service（积分服务）**，采用 Go 语言 + gRPC 协议 + SQLite 存储，成功集成至现有系统，实现微服务二次开发。
3. **多模态检测（加分项一）**：同时复现了 **DADA-Lite (KPI指标)** 与 **PreLog (日志文本)** 两篇前沿 AI 论文算法，对系统故障进行多维度交叉验证。
4. **智能运维（加分项二）**：封装 **AIOps Agent**。监听到算法异常后，自动调用大模型解析根因并生成 `kubectl` 修复指令。

---

## 👥 团队分工与贡献
| 成员 | 职责定位 | 核心产出 |
| :--- | :--- | :--- |
| **成员 A (你)** | **首席架构师/集成负责人** | K8s 环境搭建、系统集成、**全量实验运行（压测/注入/采数）**、GitHub 维护与报告统筹。 |
| **成员 B** | **微服务开发工程师** | 自研 Points Service (Go)，编写 Dockerfile 及 K8s 部署 YAML。 |
| **成员 C** | **混沌工程设计师** | 设计三类生产级故障（网络/CPU/Pod），提供 ChaosMesh 实验方案。 |
| **成员 D** | **全链路测试设计师** | 设计 Selenium 自动化下单流程与 JMeter 并发压测模型。 |
| **成员 E** | **AI 算法研究员 (KPI)** | 复现 DADA 论文算法，针对时序指标进行异常检测与区间预测。 |
| **成员 F** | **AI 算法研究员 (Log/Agent)** | 复现 PreLog 论文，构造 Metric-Event 实验，研发 AIOps Agent 智能体。 |

---

## 📂 仓库目录说明
*   `infrastructure/`: 系统底座部署文件（Online-Boutique & 监控系统）。
*   `new-service/`: 成员 B 自研的积分微服务源码及集成配置文件。
*   `testing/`: 成员 D 设计的自动化测试脚本（Selenium/JMeter）。
*   `chaos-experiments/`: 成员 C 设计的故障注入 YAML 脚本及重跑产生的 `_logs.txt`。
*   `dataset/`: **核心数据集**。包含 14:00-15:00 实验周期的指标 CSV 与带时间戳的原始日志。
*   `analysis/`: 成员 E/F 的论文复现代码、AIOps Agent 源码及分析报告。
*   `image/`: 实验过程关键截图（含全绿 Pod 列表、监控尖峰图、Agent 诊断输出）。

---

## 🛠️ 快速开始
### 1. 环境唤醒
```bash
minikube start --cpus=4 --memory=8192 --kubernetes-version=v1.28.3 --image-mirror-country=cn
```
### 2. 系统部署
```bash
kubectl apply -f infrastructure/kubernetes-manifests.yaml -n online-boutique
kubectl apply -f new-service/points-service/kubernetes/points-service.yaml -n online-boutique
```
### 3. 数据采集实验
1. 启动 `testing/` 下的 JMeter 脚本产生背景流量。
2. 依次 `kubectl apply -f` 位于 `chaos-experiments/` 的故障 YAML。
3. 访问 Grafana 看板观察实时异常波形。

---

## 📊 实验数据 Ground Truth (14:00-15:00)
为方便算法验证，实验过程中人为制造了三个故障区间：
1. **14:10 - 14:25**：`checkoutservice` CPU 过载（计算瓶颈）。
2. **14:30 - 14:40**：`frontend` 网络延迟（通信异常）。
3. **14:50 - 15:00**：`cartservice` Pod 频繁销毁（实例崩溃）。

---

## 🤖 加分项演示：AIOps Agent
当成员 E 的算法检测到 `checkoutservice` CPU 飙升至 **0.1875** 阈值以上时，Agent 自动输出如下报告：
> **[Diagnosis]**: Root cause found in checkoutservice.
> **[Reason]**: Resource saturation detected via metrics correlation.
> **[Action]**: `kubectl rollout restart deployment/checkoutservice -n online-boutique`
