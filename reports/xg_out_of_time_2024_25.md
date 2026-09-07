# Out-of-Time xG Validation Report (2024-2025)

**Model Name**: `pucklens-xg-logistic`  
**Model Version**: `1.0.0`  
**Evaluated At**: `2026-09-07T15:13:45.030939+00:00`  
**Target Season**: `20242025`  

## 1. Executive Summary & Model Decision

> **Decision Verdict**: **`HEALTHY`**  
> **Rationale**: Model maintains strong discriminative ability (ROC AUC = 0.7603) and well-calibrated probabilities (Log Loss = 0.2057, Brier = 0.0544). Expected goal rate (6.66%) closely matches observed goal rate (6.21%).

## 2. Core Probabilistic Evaluation Metrics

| Metric | Out-of-Time Value |
| :--- | :--- |
| **Shot Count** | 2,190 |
| **Actual Goals** | 136 |
| **Predicted xG** | 145.86 |
| **Actual Goal Rate** | 6.21% |
| **Expected Goal Rate** | 6.66% |
| **Log Loss** | `0.2057` |
| **Brier Score** | `0.0544` |
| **ROC AUC** | `0.7603` |

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
