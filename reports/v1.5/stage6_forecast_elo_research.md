# Stage 6 — Forecast Intelligence & Elo Research Report

**Evaluated At:** `2026-09-22T01:13:17.810999+00:00`  
**Research Execution Git SHA:** `b08a0168237ea4a26f93ae9de30626901a937e60`  
**Production Artifact Invariance:** Verified (SHA-256 match)

---

## 1. Executive Summary & Dynamic Research Conclusions

This research study evaluates whether Elo-derived team strength signals improve PuckLens game forecasting. All evaluations were conducted using a strict, leakage-safe chronological protocol across 4 NHL regular seasons:

* **2021–22:** Development & Elo state initialization
* **2022–23:** Parameter selection & blend weight optimization
* **2023–24:** Frozen research validation
* **2024–25:** Untouched final holdout

### Key Empirical Findings:

1. On the untouched 2024-25 holdout split, the observed lowest Log Loss model was Selected Research Elo (Log Loss: 0.6722).
2. Selected Research Elo produced lower Log Loss (0.6722) than the production model (0.6843) on the 2024-25 holdout, but the paired bootstrap 95% CI [-0.0269, +0.0021] includes zero, indicating statistical uncertainty.
3. Elo-as-feature augmentation improved Log Loss on the frozen 2023-24 research-validation season (Validation Delta: +0.0079, Baseline Log Loss: 0.6768 -> Elo-Augmented: 0.6689). On the untouched 2024-25 holdout, the delta was +0.0048 (Baseline: 0.6751 -> Elo-Augmented: 0.6703).
4. All production models and artifacts remain strictly frozen (v1.4.0). Research Elo and Forecast Intelligence outputs remain in the research layer only.

---

## 2. Model Performance Summary Across Evaluation Windows

### Frozen 2023–24 Research Validation Window (1312 Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE |
| :--- | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | 0.6681 | 0.2368 | 58.69% | 0.0149 |
| **Probability Blend (w=0.95)** | 0.6658 | 0.2363 | 59.45% | 0.0225 |
| **Selected Research Elo** | 0.6658 | 0.2367 | 59.53% | 0.0140 |
| **Reference Elo Baseline** | 0.6688 | 0.2380 | 59.22% | 0.0353 |

### Untouched 2024–25 Final Holdout Window (1312 Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE | Extreme Probs (<0.20 or >0.80) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | 0.6843 | 0.2429 | 57.70% | 0.0277 | 0.69% (9) |
| **Probability Blend (w=0.95)** | 0.6807 | 0.2423 | 58.61% | 0.0327 | 0.84% (11) |
| **Selected Research Elo** | 0.6722 | 0.2398 | 58.00% | 0.0412 | 0.38% (5) |
| **Reference Elo Baseline** | 0.6735 | 0.2402 | 58.16% | 0.0410 | 1.75% (23) |

---

## 3. Elo Parameter Optimization Protocol & Results

Parameters were selected strictly on **2022–23 Log Loss** using state initialized from **2021–22**.

* **Reference Configuration:** `initial_elo=1500`, `k_factor=20`, `home_advantage=35`, `season_regression=0.25`, `use_mov=True`
* **Selected Candidate Configuration:** `initial_elo=1500.0`, `k_factor=15.0`, `home_advantage=20.0`, `season_regression=0.4`, `use_mov=True`
* **Config Hash:** `de04e2d87f496a99...`
* **Selection Metric (2022–23 Log Loss):** `0.6674`

---

## 4. Elo-as-Feature Research (Point-in-Time Provenance)

Controlled experiment using Stage 5 `PointInTimeAdapter` with Logistic Regression:

* **Point-in-Time Provenance:** `PointInTimeAdapter.extract_game_features_with_cutoff` (zero synthetic timestamps).
* **Baseline Candidate (11 Production Features):**
  * 2023–24 Validation Log Loss: `0.6768`
  * 2024–25 Holdout Log Loss: `0.6751`
* **Elo-Augmented Candidate (11 Features + 4 Pregame Elo Features):**
  * 2023–24 Validation Log Loss: `0.6689`
  * 2024–25 Holdout Log Loss: `0.6703`
* **Validation Delta (Validation Log Loss Improvement):** `+0.0079`
* **Holdout Delta (Holdout Log Loss Improvement):** `+0.0048`

---

## 5. Forecast Intelligence Signals & Agreement Analysis

Game-level agreement analysis on 2024–25 holdout (1312 games):

* **Win Outcome Pick Agreement:** 74.85% (982/1312 games)
* **High Agreement (|diff| < 0.05):** 34.68% (455 games)
* **Moderate Disagreement (0.05 <= |diff| < 0.15):** 48.78% (640 games)
* **Large Disagreement (|diff| >= 0.15):** 16.54% (217 games)

---

## 6. Paired Bootstrap Statistical Evidence (1,000 Resamples on 2024–25 Holdout)

> **Sign Semantics Note:** Difference = `comparator - base`. A negative difference indicates that the comparator model achieved a lower (better) score than the base production model.

| Comparison | Metric | Observed Difference (Comp - Base) | 95% Confidence Interval | Std Error |
| :--- | :--- | :---: | :---: | :---: |
| **Production vs. Reference Elo** | Log Loss | `-0.0108` | `[-0.0262, +0.0045]` | `0.0079` |
| | Brier Score | `-0.0027` | `[-0.0083, +0.0032]` | `0.0031` |
| **Production vs. Selected Elo** | Log Loss | `-0.0120` | `[-0.0269, +0.0021]` | `0.0076` |
| | Brier Score | `-0.0032` | `[-0.0086, +0.0024]` | `0.0028` |
| **Production vs. Blend (w=0.95)** | Log Loss | `-0.0036` | `[-0.0067, -0.0013]` | `0.0014` |
| | Brier Score | `-0.0007` | `[-0.0010, -0.0004]` | `0.0001` |

---

## 7. Conclusions & Production Invariance Statement

1. **Frozen Production Model Preserved:** `pucklens-win-v1.4.0` remains 100% unchanged as the active production model.
2. **Elo Research Qualification:** Elo research parameters, probability blending, and Elo-as-feature experiments were executed cleanly under point-in-time provenance.
3. **Forecast Intelligence Availability:** `ForecastIntelligenceService` provides transparent research-layer comparison descriptors when invoked.
