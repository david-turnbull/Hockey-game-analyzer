# Stage 4: 2025-26 External Season Validation Report

**Evaluated At:** `2026-09-17T02:56:10.735694+00:00`  
**Run UUID:** `fc0cb4d0-30df-43cd-be75-2a7af2b704ad`  
**Model Version:** `v1.4.0`  
**Model Training Git SHA:** `f38f7f90cec9774c05452bd53347bf8a06c05dc2`  
**Evaluation Git SHA:** `d07a5d9c2e7eb5e46e46b591ab18b60dac513864`  
**Artifact SHA-256:** `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`  
**Feature Schema Version:** `v1`  
**Data Audit Snapshot Hash:** `a4aafb4d0dbfebf25d54cbe799678e529272be1111060975dbc373c35b648f09`  

## Provenance & Protocol Summary

- **Candidate Training:** `20212022` fit candidate architectures
- **Model Selection:** `20222023` select via Log Loss
- **Combined Production Refit:** `20212022 + 20222023`
- **Isotonic Calibration:** `20232024`
- **Frozen Holdout Baseline:** `20242025`
- **External Untouched Season:** `20252026` (`2025-26`)

> [!NOTE]
> Evaluation loaded the frozen production model artifact using `ForecastModelRegistry.load_active_model()`. Zero fitting, refitting, calibrating, or hyperparameter tuning was executed.

## Out-of-Time Performance Comparison

| Dataset / Model | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **2024-25 Frozen Holdout (Model)** | **0.6848** | **0.2431** | **57.55%** | **0.0315** |
| **2025-26 External Season (Model)** | **0.6957** | **0.2493** | **53.41%** | **0.0415** |
| 2025-26 Continuous Elo Baseline | 0.6955 | 0.2508 | 53.09% | 0.0616 |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Generalization Delta Analysis (2025-26 vs 2024-25 Holdout)

- **Δ Log Loss:** `+0.0109`
- **Δ Brier Score:** `+0.0062`
- **Δ Expected Calibration Error (ECE):** `+0.0100`

## 10 Probability Calibration Bins (2025-26)

| Bin Range | Sample Count | Avg Pred Prob | Actual Win Rate | Abs Calib Error | Bin Brier Score |
|---|---|---|---|---|---|
| `[0.0, 0.1)` | 1 | 0.0100 | 0.0000 | 0.0100 | 0.0001 |
| `[0.1, 0.2)` | 0 | 0.1500 | 0.0000 | 0.0000 | 0.0000 |
| `[0.2, 0.3)` | 42 | 0.2371 | 0.4524 | 0.2152 | 0.2913 |
| `[0.3, 0.4)` | 3 | 0.3694 | 0.0000 | 0.3694 | 0.1372 |
| `[0.4, 0.5)` | 270 | 0.4599 | 0.4889 | 0.0290 | 0.2506 |
| `[0.5, 0.6)` | 703 | 0.5471 | 0.5092 | 0.0379 | 0.2516 |
| `[0.6, 0.7)` | 150 | 0.6203 | 0.6133 | 0.0070 | 0.2387 |
| `[0.7, 0.8)` | 46 | 0.7432 | 0.6739 | 0.0693 | 0.2204 |
| `[0.8, 0.9)` | 11 | 0.8000 | 0.8182 | 0.0182 | 0.1491 |
| `[0.9, 1.0]` | 4 | 0.9900 | 0.5000 | 0.4900 | 0.4901 |

## Timeline Season Splits (2025-26)

| Season Segment | Games | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|---|
| **Early Season** | 410 | 0.7117 | 0.2559 | 50.24% | 0.0823 |
| **Mid Season** | 410 | 0.6908 | 0.2488 | 53.41% | 0.0391 |
| **Late Season** | 410 | 0.6847 | 0.2433 | 56.59% | 0.0233 |

## Bootstrap 95% Confidence Intervals (Model vs Elo Difference on 2025-26)

- **Log Loss Difference (Model - Elo):** `+0.0002` (95% CI: `[-0.0129, +0.0157]`, SE: `0.0072`)
- **Brier Score Difference (Model - Elo):** `-0.0015` (95% CI: `[-0.0067, +0.0041]`, SE: `0.0028`)


## Score Projection Evaluation (2025-26)

- **Expected Total Goals MAE:** 2.06 goals
- **Home Goals MAE:** 1.58 goals
- **Away Goals MAE:** 1.47 goals
- **Top 1 Exact Scoreline Coverage:** 3.82%
- **Top 5 Exact Scoreline Coverage:** 17.07%
