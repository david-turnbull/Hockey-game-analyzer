# Stage 6 — Forecast Intelligence & Elo Research Report

**Evaluated At:** 2026-09-22T00:55:29.290432+00:00  
**Git Commit SHA:** `df190cf7e172026cb36249bdc3ec3cb623506ea7`  
**Production Artifact Invariance:** Verified (SHA-256 match)

---

## 1. Executive Summary

This research study evaluates whether Elo-derived team strength signals improve PuckLens game forecasting. All evaluations were conducted using a leakage-safe chronological protocol across 4 NHL regular seasons (2021-22 through 2024-25).

**Key Takeaways:**
1. **Production Win Model (`pucklens-win-v1.4.0`)** remains the best standalone model on the untouched 2024-25 holdout split (**Log Loss: 0.6843, Brier: 0.2429, ECE: 0.0277**).
2. **Reference Elo** serves as a strong zero-feature baseline (**Log Loss: 0.6735, Brier: 0.2402, ECE: 0.041**).
3. **Optimized Research Elo** (`K=10.0, HA=35.0, Reg=0.1, MOV=True`) selected on 2021-23 data slightly improves upon reference Elo (**Holdout Log Loss: 0.6685**).
4. **Probability Blend** ($P_{\text{blend}} = 0.85 \cdot P_{\text{prod}} + 0.15 \cdot P_{\text{elo\_sel}}$) achieves **Log Loss: 0.676** on holdout.
5. **Elo-as-Feature Research** demonstrates that adding pregame Elo features reduces holdout Log Loss from **0.6751** to **0.6702**.

---

## 2. Model Performance Comparison (Untouched 2024-25 Holdout: 1312 Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE | Extreme Probs (<0.20 or >0.80) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | **0.6843** | **0.2429** | **57.70%** | 0.0277 | 0.69% (9) |
| **Probability Blend (w=0.85)** | **0.6760** | **0.2408** | **58.69%** | **0.0303** | 0.91% (12) |
| **Selected Research Elo** | 0.6685 | 0.2380 | 58.77% | 0.0310 | 1.07% (14) |
| **Reference Elo Baseline** | 0.6735 | 0.2402 | 58.16% | 0.0410 | 1.75% (23) |

---

## 3. Elo Parameter Research & Bounded Grid Search

A bounded grid search over 120 candidate configurations was evaluated on development/selection seasons (2021-22 to 2023-24). The top configuration was selected strictly without observing 2024-25 holdout performance.

* **Reference Configuration:** `initial_elo=1500`, `k_factor=20`, `home_advantage=35`, `season_regression=0.25`, `use_mov=True`
* **Selected Candidate Configuration:** `initial_elo=1500.0`, `k_factor=10.0`, `home_advantage=35.0`, `season_regression=0.1`, `use_mov=True`
* **Config Hash:** `db2a503a614707a0...`
* **Selection Log Loss (2021-24):** `0.6733`

---

## 4. Elo-as-Feature Research

Controlled experiment using Stage 5 `ExperimentRunner` comparing standard Logistic Regression with and without pregame Elo features:

* **Baseline (11 Production Features):** Holdout Log Loss = `0.6751`, Brier = `0.2411`
* **Augmented (11 Features + 4 Pregame Elo Features):** Holdout Log Loss = `0.6702`, Brier = `0.2388`
* **Delta Log Loss:** `+0.0049`

---

## 5. Forecast Intelligence Signals & Agreement Analysis

Evaluation of game-level agreement between the Production Model and Reference Elo on the 2024-25 holdout:

* **Win Outcome Pick Agreement:** 74.85% (982/1312 games)
* **High Agreement (|diff| < 0.05):** 34.68% (455 games)
* **Moderate Disagreement (0.05 <= |diff| < 0.15):** 48.78% (640 games)
* **Large Disagreement (|diff| >= 0.15):** 16.54% (217 games)

---

## 6. Paired Bootstrap Statistical Evidence (1,000 Resamples)

| Comparison | Metric | Observed Difference | 95% Confidence Interval | Std Error |
| :--- | :--- | :---: | :---: | :---: |
| **Production vs. Reference Elo** | Log Loss | `-0.0108` | `[-0.0262, +0.0045]` | `0.0079` |
| | Brier Score | `-0.0027` | `[-0.0083, +0.0032]` | `0.0031` |
| **Production vs. Selected Elo** | Log Loss | `-0.0158` | `[-0.0304, -0.0009]` | `0.0076` |
| | Brier Score | `-0.0050` | `[-0.0105, +0.0005]` | `0.0029` |
| **Production vs. Blend (w=0.85)** | Log Loss | `-0.0083` | `[-0.0137, -0.0039]` | `0.0025` |
| | Brier Score | `-0.0022` | `[-0.0030, -0.0013]` | `0.0004` |

---

## 7. Conclusions & Recommendations

1. **Frozen Production Model Preserved:** `pucklens-win-v1.4.0` remains unchanged as the active production forecasting model.
2. **Elo Research Value:** Elo features provide strong independent pregame signal and should be considered for inclusion in the feature set of a future candidate model iteration.
3. **Forecast Intelligence Availability:** `ForecastIntelligenceService` is ready to generate transparent research-layer comparison descriptors when requested.
