# Out-of-Time xG Predictive Validation (2024-25 Season)

## Executive Summary
In PuckLens v1.3, the frozen `v1.2.1` Expected Goals model (`models/xg/xg_v1.pkl`) was evaluated against an out-of-time sample of regular season games from the 2024-25 NHL season. The model was evaluated without any retraining, weight adjustments, or recalibration.

> **Dataset Scope Disclosure**: This evaluation is conducted on an available sample of **25 evaluated regular season games** (out of 1,312 full NHL regular season games, representing **1.91% coverage**, spanning October 9, 2024 through November 30, 2024). Performance results reflect the available sample only; no full-season health or zero concept drift across the full season is inferred.

## Invariant Evaluation Rules
1. **Model Freeze & SHA-256 Invariance:** Absolute freeze on model parameters, pipeline weights, and categorical encoders. Both pre-validation and post-validation SHA-256 hashes must strictly match `c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635`.
2. **Blocked Shot Invariant:** Blocked attempts (`Shot.outcome == 'Blocked'`) are strictly excluded from validation evaluation ($xG = \text{NULL}$).
3. **Shootout Exclusion:** Shootout attempts are excluded.
4. **Data Isolation:** Only 2024-25 regular season games were evaluated.
5. **Authentic Provenance:** Game ID and date provenance must be authentically derived from source data without synthetic fallbacks.

## Dataset Profile
- **Total Games Ingested:** 25 (~1.91% of full season)
- **Date Range:** 2024-10-09 to 2024-11-30
- **Total Play-by-Play Events:** 8,790
- **Total Shot Attempts (Corsi):** 3,182
- **Unblocked Shot Attempts (Fenwick / xG Population):** 2,190
- **Actual Goals Scored:** 136

## Predictive Performance & Metrics

| Metric | Target / Benchmark | 2024-25 Out-of-Time Result | Status |
| :--- | :--- | :--- | :--- |
| **Actual Goal Rate** | Empirical | 6.21% | - |
| **Predicted Expected Goal Rate** | Empirical | 6.66% | - |
| **Total Expected Goals** | Sum($xG$) | 145.86 | - |
| **Calibration Ratio** ($\sum Goals / \sum xG$) | 0.85 - 1.15 | 0.9324 | **PASS** |
| **Log Loss** | < 0.220 | 0.2057 | **PASS** |
| **Brier Score** | < 0.060 | 0.0544 | **PASS** |
| **ROC AUC** | > 0.700 | 0.7603 | **PASS** |
| **Model Invariance SHA-256** | `c7f4f55bb013...` | Identical pre- and post-validation | **PASS** |

## Calibration Deciles

| Decile | Shots | Predicted Prob Range | Expected Goals | Actual Goals | Actual Rate |
| :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | 219 | 0.015 - 0.025 | 4.48 | 3 | 1.37% |
| 2 | 219 | 0.025 - 0.030 | 6.07 | 4 | 1.83% |
| 3 | 219 | 0.030 - 0.035 | 7.15 | 6 | 2.74% |
| 4 | 219 | 0.035 - 0.042 | 8.37 | 7 | 3.20% |
| 5 | 219 | 0.042 - 0.050 | 9.98 | 8 | 3.65% |
| 6 | 219 | 0.050 - 0.061 | 12.10 | 12 | 5.48% |
| 7 | 219 | 0.061 - 0.077 | 14.94 | 15 | 6.85% |
| 8 | 219 | 0.077 - 0.103 | 19.45 | 18 | 8.22% |
| 9 | 219 | 0.103 - 0.155 | 27.28 | 25 | 11.42% |
| 10 | 219 | 0.155 - 0.449 | 36.03 | 38 | 17.35% |

## Diagnostic Verdict
**Verdict: `HEALTHY_ON_AVAILABLE_SAMPLE`**  
The model demonstrates strong calibration (0.9324) and discriminative separation (0.7603 ROC-AUC) on the available out-of-time 2024-25 data sample (25 games, 1.91% coverage). This verdict applies strictly to the evaluated sample; no full-season health or zero concept drift across the entire season is inferred.
