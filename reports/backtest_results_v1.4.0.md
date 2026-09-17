# PuckLens v1.4.0 Historical Out-of-Time Backtest Report

**Run Timestamp:** 2026-09-17T01:33:37.760696+00:00  
**Selected Model Architecture:** `HistGradientBoosting`

## Protocol & Temporal Splits

- **Train Split (2021-22):** Model candidate parameter fitting
- **Model Selection Split (2022-23):** Candidate selection via Log Loss (`LogisticRegression` vs `HistGradientBoosting`)
- **Combined Refit (2021-22 + 2022-23):** Winner refitted on combined historical data
- **Calibration Split (2023-24):** Isotonic Regression calibrator fit on 2023-24 validation predictions
- **Final Out-of-Time Test (2024-25):** 100% untouched holdout evaluation

## Out-of-Time Performance Comparison (2024-25 Test Holdout)

| Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **PuckLens v1.4.0 (Calibrated Model)** | **0.6848** | **0.2431** | **57.55%** | **0.0315** |
| Elo Baseline Model | 0.6735 | 0.2403 | 58.16% | 0.0410 |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Score Projection Model Evaluation (2024-25)

- **Expected Total Goals MAE:** 2.06 goals
- **Home Goals MAE:** 1.56 goals
- **Away Goals MAE:** 1.48 goals
- **Exact (Top 1) Scoreline Coverage:** 3.89% of games
- **Top 5 Exact Scoreline Coverage:** 18.9% of games

> [!NOTE]
> All pregame features enforce the strict temporal invariant (`start_time_utc < target_game.start_time_utc`), guaranteeing zero future leakage.
