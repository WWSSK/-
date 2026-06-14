成员 F：论文复现与 Agent 封装交付说明

1. PreLog 论文复现
- 论文：SIGMOD 2024 PreLog
- 官方 BGL 数据集复现结果：faulty F1 = 0.935
- 说明：完成环境配置、模型运行和结果分析

2. Online-Boutique 迁移实验
- 数据：本组 Online-Boutique 日志与 Prometheus/Grafana CSV
- 结果：PreLog 在小规模组内数据上出现单类别退化
- 分析：故障主要体现在指标层，原始应用日志可分性较弱

3. Metric-Event Baseline
- 方法：将 Prometheus CSV 转化为指标事件日志
- 模型：TF-IDF + Logistic Regression
- 结果：accuracy=0.9985，macro F1=0.9985，faulty F1=0.9984
- 作用：验证组内指标事件数据具有明显异常信号

4. AIOps Agent
- 触发器：监听成员 E 的 detection_scores.csv
- 诊断逻辑：根据异常服务、故障类型和证据生成根因解释
- 动作：输出 kubectl 检查与修复指令
- 当前状态：已通过 mock 成员 E 结果完成端到端验证

