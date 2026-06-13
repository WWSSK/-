# Member E DADA-Lite Anomaly Detection Code

This directory contains the code used by member E for paper-based KPI anomaly detection.
Reports and presentation files are intentionally not included.

The implementation is a lightweight reproduction of the ICLR 2025 DADA idea for course-project use:

- complementary mask reconstruction;
- adaptive bottleneck pool;
- normal/anomaly dual reconstruction using injected anomaly windows;
- threshold calibration;
- point-level KPI anomaly predictions for TrainTicket monitoring CSV files.

## Directory

- `src/dada_lite/`: detector implementation and utilities.
- `scripts/`: data conversion, weak-label generation, detection runner, and result summarizer.
- `tests/`: local unit tests.
- `configs/`: sample Prometheus query config.

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Reproduce the Real Data Run

Run from this directory. The raw Grafana CSV is stored at repository root under `dataset/`.

```bash
mkdir -p data outputs/member_c_online_boutique_cpu_weak_label

python3 scripts/convert_grafana_pod_cpu.py \
  --input ../../dataset/Explore-data-as-seriestocolumns-2026-06-12\ 15_46_00.csv \
  --output data/member_c_online_boutique_cpu_clean.csv \
  --train-output data/member_c_online_boutique_cpu_train.csv \
  --train-fraction 0.45

python3 scripts/add_weak_labels.py \
  --input data/member_c_online_boutique_cpu_clean.csv \
  --output data/member_c_online_boutique_cpu_weak_labeled.csv \
  --anomaly-window "2026-06-12 15:28:00+08:00,2026-06-12 15:30:45+08:00,multi_pod_cpu_rise" \
  --anomaly-window "2026-06-12 15:31:45+08:00,2026-06-12 15:33:15+08:00,checkoutservice_cpu_spike" \
  --anomaly-window "2026-06-12 15:35:00+08:00,2026-06-12 15:36:45+08:00,second_multi_pod_cpu_rise"

python3 scripts/run_dada_lite.py \
  --train-csv data/member_c_online_boutique_cpu_train.csv \
  --test-csv data/member_c_online_boutique_cpu_weak_labeled.csv \
  --time-column timestamp \
  --label-column label \
  --out-dir outputs/member_c_online_boutique_cpu_weak_label \
  --window-size 40 \
  --step 5 \
  --threshold-quantile 0.98 \
  --injected-threshold-quantile 0.70 \
  --title "Member E DADA-Lite on C Real Pod CPU Data" \
  --primary-metric cpu_checkoutservice_5b59b6549c_tzm6v

python3 scripts/summarize_detection.py \
  --scores-csv outputs/member_c_online_boutique_cpu_weak_label/detection_scores.csv \
  --train-csv data/member_c_online_boutique_cpu_train.csv \
  --output-md outputs/member_c_online_boutique_cpu_weak_label/summary.md \
  --output-json outputs/member_c_online_boutique_cpu_weak_label/detection_intervals.json
```

Expected weak-label auxiliary metrics:

- Precision: `0.5098`
- Recall: `0.9630`
- F1: `0.6667`

The weak labels are based on visual inspection of the Grafana screenshot and are not strict ChaosMesh ground truth.

## Test

```bash
python3 -m unittest discover -s tests
```
