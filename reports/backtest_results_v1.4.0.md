# PuckLens v1.4.0 Authoritative Artifact-Bound Holdout Report (2024-25)

- **Evaluation Timestamp:** `2026-09-17T01:50:24.084619+00:00`
- **Run UUID:** `5025cbe0-ab93-4225-abf1-0a3a5e1d8d7f`
- **Git Commit SHA:** `f38f7f90cec9774c05452bd53347bf8a06c05dc2`
- **Model Version:** `v1.4.0`
- **Model Artifact SHA-256:** `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`
- **Feature Schema Version:** `v1`

## Protocol & Provenance Metadata

- **Candidate Training Split (2021-22):** Model candidate parameter fitting
- **Selection Split (2022-23):** Model selection criterion via Log Loss
- **Production Refit (2021-22 + 2022-23):** Selected model refitted on combined historical dataset
- **Calibration Split (2023-24):** Isotonic Regression calibrator fit on validation predictions
- **Authoritative Untouched Holdout (2024-25):** 100% untouched test evaluation using `ForecastModelRegistry.load_active_model()`

## Out-of-Time Performance Comparison (2024-25 Test Holdout)

| Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **PuckLens v1.4.0 (Production Artifact)** | **0.6848** | **0.2431** | **57.55%** | **0.0315** |
| Elo Baseline Model | 0.6735 | 0.2403 | 58.16% | 0.0410 |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Score Projection Model Evaluation (2024-25)

- **Expected Total Goals MAE:** 2.06 goals
- **Home Goals MAE:** 1.56 goals
- **Away Goals MAE:** 1.48 goals
- **Exact (Top 1) Scoreline Coverage:** 3.89% of games
- **Top 5 Exact Scoreline Coverage:** 18.9% of games

> [!IMPORTANT]
> This evaluation strictly loads the active frozen production model artifact using `ForecastModelRegistry.load_active_model()`. Zero fitting, refitting, calibrating, or hyperparameter tuning was executed during this evaluation.
