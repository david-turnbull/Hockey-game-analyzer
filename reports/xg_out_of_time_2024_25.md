# Out-of-Time xG Validation Report (2024-2025 Partial Sample)

> **Important Dataset Scope Disclosure**: This out-of-time evaluation is conducted on an available sample of **25 evaluated games** (out of ~1,312 full NHL regular season games, representing **1.91% coverage**). Performance results reflect the available sample only; no full-season health or calibration conclusions are inferred.

## Dataset & Model Provenance

- **Target Season**: `20242025`
- **Games Evaluated**: `25` (Coverage: `1.91%` of 1,312 regular season games)
- **Evaluation Date Range**: `2024-10-09` to `2024-11-30`
- **Dataset Source**: `NHL Official Play-by-Play API (2024-25 Season Partial Sample)`
- **Total Shots Evaluated**: `2,190`
- **Total Goals**: `136`
- **Unknown Team Attribution**: `0` (0.00%)
- **Model Name & Version**: `pucklens-xg-logistic` (1.0.0)
- **Model Invariance SHA-256**: `c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635` (Verified Unchanged)
- **Evaluated At**: `2026-09-07T20:03:13.146838+00:00`

## 1. Executive Summary & Model Decision

> **Decision Verdict**: **`HEALTHY_ON_AVAILABLE_SAMPLE`**  
> **Sample Scope**: `available_sample_only` (Full-season inference: `disallowed`)  
> **Rationale**: On the available sample of 25 games (2,190 shots, 1.91% season coverage), the model maintains strong discriminative ability (ROC AUC = 0.7603) and well-calibrated probabilities (Log Loss = 0.2057, Brier = 0.0544). Expected goal rate (6.66%) closely matches observed goal rate (6.21%). This verdict applies strictly to the evaluated sample; no full-season health conclusion is inferred.

## 2. Core Probabilistic Evaluation Metrics

| Metric | Available Sample Value | Invariance / Health Criteria |
| :--- | :--- | :--- |
| **Shot Count** | 2,190 | 25 evaluated games (1.91% of season) |
| **Actual Goals** | 136 | Observed out-of-time goals |
| **Predicted xG** | 145.86 | Full 21-feature inference |
| **Actual Goal Rate** | 6.21% | Observed conversion rate |
| **Expected Goal Rate** | 6.66% | Predicted conversion rate |
| **Log Loss** | `0.2057` | Baseline target <= 0.25 (Test baseline ~0.21-0.23) |
| **Brier Score** | `0.0544` | Lower is better |
| **ROC AUC** | `0.7603` | Baseline target >= 0.72 (Test baseline ~0.74-0.75) |
| **Model Artifact SHA-256** | `c7f4f55bb0136f5d...` | Bitwise identical before & after validation |

## 3. Calibration Breakdown

| Prediction Band | Shot Count | Mean Predicted Prob | Observed Goal Rate |
| :--- | :--- | :--- | :--- |
| [0.00, 0.05] | 1,154 | 0.0235 | 0.0182 |
| [0.05, 0.10] | 571 | 0.0714 | 0.0806 |
| [0.10, 0.15] | 268 | 0.1211 | 0.0970 |
| [0.15, 0.20] | 110 | 0.1680 | 0.1636 |
| [0.20, 0.30] | 68 | 0.2435 | 0.2353 |
| [0.30, 0.50] | 8 | 0.3482 | 0.3750 |
| [0.50, 1.00] | 11 | 0.6958 | 0.5455 |

## 4. Segment Evaluations

### Distance Brackets

| Distance | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |
| :--- | :--- | :--- | :--- | :--- | :--- |
| <15 ft | 439 | 47 | 56.51 | 10.71% | 12.87% |
| 15-30 ft | 509 | 44 | 44.15 | 8.64% | 8.67% |
| 30-45 ft | 566 | 26 | 28.87 | 4.59% | 5.10% |
| 45+ ft | 676 | 19 | 16.33 | 2.81% | 2.42% |

### Strength State

| Strength | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |
| :--- | :--- | :--- | :--- | :--- | :--- |
| EV | 1,770 | 80 | 101.52 | 4.52% | 5.74% |
| PP | 356 | 42 | 30.19 | 11.80% | 8.48% |
| SH | 64 | 14 | 14.15 | 21.88% | 22.11% |

### Shot Types

| Shot Type | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |
| :--- | :--- | :--- | :--- | :--- | :--- |
| wrist | 1,187 | 69 | 69.33 | 5.81% | 5.84% |
| snap | 303 | 26 | 24.13 | 8.58% | 7.96% |
| tip-in | 234 | 14 | 18.41 | 5.98% | 7.87% |
| slap | 275 | 15 | 16.60 | 5.45% | 6.04% |
| backhand | 158 | 11 | 12.81 | 6.96% | 8.11% |
| wrap-around | 11 | 1 | 1.07 | 9.09% | 9.71% |
| other | 22 | 0 | 3.51 | 0.00% | 15.97% |

### Home / Away Split

| Location | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Home | 1,116 | 80 | 74.09 | 7.17% | 6.64% |
| Away | 1,074 | 56 | 71.77 | 5.21% | 6.68% |

### Team Segmentation (>= 10 Shots)

| Team | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |
| :--- | :--- | :--- | :--- | :--- | :--- |
| BOS | 48 | 4 | 3.73 | 8.33% | 7.77% |
| BUF | 35 | 2 | 2.22 | 5.71% | 6.34% |
| CAR | 59 | 4 | 4.22 | 6.78% | 7.15% |
| CBJ | 43 | 5 | 3.48 | 11.63% | 8.10% |
| CGY | 1,098 | 63 | 72.56 | 5.74% | 6.61% |
| CHI | 42 | 1 | 2.67 | 2.38% | 6.36% |
| DET | 41 | 2 | 2.24 | 4.88% | 5.46% |
| EDM | 79 | 5 | 4.60 | 6.33% | 5.82% |
| LAK | 43 | 1 | 2.46 | 2.33% | 5.72% |
| MIN | 44 | 3 | 2.87 | 6.82% | 6.52% |
| MTL | 47 | 2 | 3.77 | 4.26% | 8.02% |
| NJD | 29 | 0 | 2.32 | 0.00% | 8.00% |
| NSH | 46 | 0 | 3.43 | 0.00% | 7.45% |
| NYI | 39 | 1 | 2.52 | 2.56% | 6.46% |
| NYR | 37 | 2 | 2.16 | 5.41% | 5.85% |
| OTT | 39 | 4 | 2.86 | 10.26% | 7.33% |
| PHI | 56 | 3 | 3.45 | 5.36% | 6.16% |
| PIT | 112 | 9 | 6.94 | 8.04% | 6.20% |
| SEA | 39 | 2 | 2.24 | 5.13% | 5.74% |
| UTA | 45 | 5 | 3.15 | 11.11% | 7.01% |
| VAN | 80 | 8 | 5.54 | 10.00% | 6.92% |
| VGK | 44 | 5 | 2.77 | 11.36% | 6.31% |
| WPG | 45 | 5 | 3.66 | 11.11% | 8.14% |

## 5. Model Invariance & Security Attestation

- **Production Model Path**: `models/xg/xg_v1.pkl`
- **Expected SHA-256**: `c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635`
- **Pre-Validation SHA-256**: `c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635`
- **Post-Validation SHA-256**: `c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635`
- **Invariance Status**: **PASS** (Bitwise identical artifact confirmed; model was not retrained, fine-tuned, or modified).
