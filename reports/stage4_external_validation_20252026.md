# Stage 4: 2025-26 External Season Validation Report

**Evaluated At:** `2026-09-18T00:32:56.352687+00:00`  
**Run UUID:** `8721f963-0789-4dbc-b0f2-9e9043fe1597`  
**Model Version:** `v1.4.0`  
**Model Training Git SHA:** `f38f7f90cec9774c05452bd53347bf8a06c05dc2`  
**Evaluation Git SHA:** `9e23d640a26c172fe14dde8804cd69a1eea3470d`  
**Artifact SHA-256:** `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`  
**Feature Schema Version:** `v1`  
**Data Audit Snapshot Hash:** `7e1e00ef63d03e613097833e3c73d21b36e951aebc49fd6a4dfcc9bead7a4608`  

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
| **2025-26 External Season (Model)** | **0.6910** | **0.2479** | **54.19%** | **0.0332** |
| 2025-26 Continuous Elo Baseline | 0.6959 | 0.2510 | 53.20% | 0.0600 |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Generalization Delta Analysis (2025-26 vs 2024-25 Holdout)

- **Δ Log Loss:** `+0.0062`
- **Δ Brier Score:** `+0.0048`
- **Δ Expected Calibration Error (ECE):** `+0.0017`

## 10 Probability Calibration Bins (2025-26)

| Bin Range | Sample Count | Avg Pred Prob | Actual Win Rate | Abs Calib Error | Bin Brier Score |
|---|---|---|---|---|---|
| `[0.0, 0.1)` | 1 | 0.0100 | 0.0000 | 0.0100 | 0.0001 |
| `[0.1, 0.2)` | 0 | 0.1500 | 0.0000 | 0.0000 | 0.0000 |
| `[0.2, 0.3)` | 46 | 0.2389 | 0.4783 | 0.2394 | 0.3093 |
| `[0.3, 0.4)` | 4 | 0.3464 | 0.7500 | 0.4036 | 0.3695 |
| `[0.4, 0.5)` | 285 | 0.4602 | 0.4561 | 0.0041 | 0.2483 |
| `[0.5, 0.6)` | 752 | 0.5460 | 0.5133 | 0.0327 | 0.2499 |
| `[0.6, 0.7)` | 160 | 0.6222 | 0.6062 | 0.0160 | 0.2396 |
| `[0.7, 0.8)` | 56 | 0.7521 | 0.7321 | 0.0200 | 0.1895 |
| `[0.8, 0.9)` | 7 | 0.8000 | 0.8571 | 0.0571 | 0.1257 |
| `[0.9, 1.0]` | 1 | 0.9900 | 0.0000 | 0.9900 | 0.9801 |

## Timeline Season Splits (2025-26)

| Season Segment | Games | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|---|
| **Early Season** | 437 | 0.7024 | 0.2542 | 50.80% | 0.0653 |
| **Mid Season** | 437 | 0.6835 | 0.2452 | 55.38% | 0.0362 |
| **Late Season** | 438 | 0.6869 | 0.2442 | 56.39% | 0.0355 |

## Bootstrap 95% Confidence Intervals (Model vs Elo Difference on 2025-26)

- **Log Loss Difference (Model - Elo):** `-0.0049` (95% CI: `[-0.0173, +0.0079]`, SE: `0.0064`)
- **Brier Score Difference (Model - Elo):** `-0.0031` (95% CI: `[-0.0085, +0.0023]`, SE: `0.0027`)


## Score Projection Evaluation (2025-26)

- **Expected Total Goals MAE:** 2.05 goals
- **Home Goals MAE:** 1.57 goals
- **Away Goals MAE:** 1.48 goals
- **Top 1 Exact Scoreline Coverage:** 3.35%
- **Top 5 Exact Scoreline Coverage:** 17.38%
