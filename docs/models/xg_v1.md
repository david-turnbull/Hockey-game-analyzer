# PuckLens Expected Goals (xG) — Model Card

**Model Version:** `pucklens-xg-v1` (Model Identifier: `pucklens-xg-logistic`)  
**Release Date:** September 2026  
**License / Platform:** PuckLens Independent Hockey Analytics Platform  

---

## 1. Model Overview & Purpose

The **PuckLens Expected Goals (xG) Model v1** is an independently trained statistical model designed to estimate the probability that an unblocked shot attempt (goal, save, or miss) results in a goal. The model produces a continuous probability:

$$0.0 \le xG \le 1.0$$

The primary purpose is to assess underlying shot quality, team offensive/defensive generation ($xGF$, $xGA$, $xG\%$), goaltender performance ($GSAx = xGA - GA$), and lineup deployment independent of shooting percentage variance and small-sample puck luck.

> **Attribution Notice**: This is an independently developed statistical model engineered for PuckLens. It does not represent proprietary NHL, Sportlogiq, or third-party proprietary metrics.

---

## 2. Training Data & Methodology

- **Population**: 14,262 unblocked regular-season NHL shot attempts extracted from 162 regular season games (2023–2024 season). Shootout attempts are excluded.
- **Split Strategy**: Strictly **chronological train/validation/test split** by game date and ID to eliminate temporal data leakage:
  - **Training Set**: 113 games (9,860 shot attempts; 690 goals; 7.00% goal rate)
  - **Validation Set**: 24 games (2,176 shot attempts; 157 goals; 7.22% goal rate)
  - **Held-Out Test Set**: 25 games (2,226 shot attempts; 147 goals; 6.60% goal rate)

---

## 3. Features & Inputs

All features are normalized relative to the attacking net located at $(x = 89, y = 0)$ and are strictly restricted to information available prior to or at the instant of shot release (zero look-ahead bias).

### Core Geometric & Game Context Features:
| Feature | Type | Description |
| :--- | :--- | :--- |
| `distance` | Numeric | Euclidean distance (in feet) from normalized shot coordinates to net center $(89, 0)$. |
| `angle` | Numeric | Absolute angle (in degrees) from center-line to net center. Centered shots = $0^\circ$, goal-line shots = $90^\circ$. |
| `shot_type` | Categorical | Shot release type (`wrist`, `slap`, `snap`, `backhand`, `tip-in`, `deflected`, `wrap-around`, `other`). |
| `strength_state` | Categorical | Manpower state (`EV`, `PP`, `SH`). |
| `score_differential` | Numeric | Shooter's team score minus defending team score at time of shot attempt. |
| `period` | Numeric | Regulation or overtime period number (1, 2, 3, 4). |
| `period_seconds` | Numeric | Elapsed seconds within current period (0 to 1200). |
| `is_home` | Binary | 1 if shooting team is the home team, 0 if away. |
| `empty_net` | Binary | 1 if defending goaltender is pulled, 0 otherwise. |

### Sequential & Contextual Derived Features:
| Feature | Type | Description |
| :--- | :--- | :--- |
| `prev_event_type` | Categorical | Type of play-by-play event immediately preceding the shot attempt. |
| `time_since_prev_event` | Numeric | Elapsed seconds ($\Delta t$) between preceding event and current shot attempt. |
| `distance_from_prev_event` | Numeric | Distance in feet ($\Delta d$) traveled from the location of the previous event. |
| `angle_change` | Numeric | Change in angle relative to the net between preceding event and shot attempt. |
| `is_rebound` | Binary | 1 if shot occurred within $\le 3.0$ seconds of a previous save, block, or miss. |
| `is_rush` | Binary | 1 if shot was preceded by rapid transition ($\Delta d \ge 40$ ft within $\Delta t \le 4$ s). |
| `is_turnover` | Binary | 1 if shot followed a takeaway or giveaway within $\le 4.0$ seconds. |
| `is_after_faceoff` | Binary | 1 if shot occurred within $\le 4.0$ seconds of a faceoff event. |
| `is_lateral_movement` | Binary | 1 if rapid lateral angle change ($\ge 25^\circ$) occurred within $\le 3.0$ seconds. |

---

## 4. Evaluation Results & Model Selection

### Validation-Based Candidate Selection (Zero Test Leakage)
In accordance with PuckLens predictive analytics hardening standards, candidate models were evaluated and compared **strictly on the chronological validation set** (2,176 shot attempts across 24 games; 157 actual goals). **The held-out test set remained completely isolated and untouched during candidate selection.**

| Metric | Logistic Regression (Candidate) | Gradient Boosting (Candidate) | Target Direction |
| :--- | :--- | :--- | :--- |
| **Validation Log Loss** | **0.2325** | 0.2328 | Lower is better (Primary Selection Metric) |
| **Validation Brier Score** | 0.0635 | **0.0625** | Lower is better |
| **Validation ROC AUC** | 0.7486 | **0.7528** | Higher is better |
| **Validation Expected Goals** | 151.66 | 137.30 | Target: 157.0 Actual Goals |
| **Validation Exp Goal %** | 6.97% | 6.31% | Target: 7.22% Actual |

### Selection Rationale:
The **Logistic Regression** configuration was selected as the winning architecture because:
1. It achieved the lowest **Validation Log Loss** (0.2325 vs 0.2328).
2. It exhibited superior calibration on unseen validation games (predicting 151.66 xG vs 157 actual goals, a 3.4% delta, compared to 137.30 xG for gradient boosting).
3. It provides high interpretability, strict mathematical guarantees, and fast inference without black-box hyperparameter fragility.

---

## 5. Production Retraining (Option B) & Final Benchmark

### Retraining Protocol
Once candidate architecture selection was frozen, the selected Logistic Regression configuration was **refitted on the combined training and validation dataset** (Option B):
- **Refit Dataset**: 137 games (113 train + 24 validation games)
- **Refit Sample Size**: 12,036 total unblocked shot attempts (847 goals; 7.04% baseline goal rate)

### Final Single Evaluation on Untouched Held-Out Test Set
The finalized refit model was evaluated **once** on the untouched chronological test set (25 games; 2,226 shot attempts; 147 actual goals).

> **Methodological Disclaimer**: The held-out test set was never accessed, evaluated, or peeked at during candidate selection, hyperparameter choices, or feature engineering iterations.

| Final Test Metric | Production Model (`pucklens-xg-logistic` v1.0.0) | Target / Reference |
| :--- | :--- | :--- |
| **Test Log Loss** | **0.2127** | Lower is better |
| **Test Brier Score** | **0.0563** | Lower is better |
| **Test ROC AUC** | **0.7493** | Higher is better |
| **Actual Goals** | 147 | — |
| **Total Expected Goals** | **150.44** | Target: 147.0 Actual Goals (+2.3% delta) |
| **Actual Goal Rate** | 6.60% | — |
| **Expected Goal Rate** | **6.76%** | Well-calibrated baseline |

---

## 6. Performance by Hockey Segments (Held-Out Test Games)

Calibration across shot distance brackets and game situations on the untouched test set:
- **Inner Slot (<15 ft)**: 487 shots | 50 actual goals (10.27%) | 64.11 xG (13.16%)
- **High Slot (15–30 ft)**: 488 shots | 45 actual goals (9.22%) | 40.35 xG (8.27%)
- **Perimeter (30–45 ft)**: 574 shots | 39 actual goals (6.79%) | 30.74 xG (5.35%)
- **Point / Deep (45+ ft)**: 677 shots | 13 actual goals (1.92%) | 15.25 xG (2.25%)
- **Even Strength (EV)**: 1,824 shots | 90 actual goals (4.93%) | 105.46 xG (5.78%)
- **Power Play (PP)**: 335 shots | 38 actual goals (11.34%) | 29.75 xG (8.88%)
- **Shorthanded (SH)**: 67 shots | 19 actual goals (28.36%) | 15.24 xG (22.74%)

---

## 7. Known Limitations

1. **Play-by-Play Coordinate Inaccuracies**: Official NHL play-by-play coordinates are recorded manually by arena official scorers and may exhibit venue-specific clustering or scorer bias.
2. **Absence of Player Tracking**: Optical tracking data (exact positions of all 10 skaters, goalie stance, stick blades) is proprietary to NHL EDGE and unavailable in standard public feeds.
3. **Screen / Traffic Estimation**: Public play-by-play feeds do not explicitly log visual screens or defender proximity; screening effects are partially proxied through distance, traffic, and rebound flags.
4. **Pre-Shot Lateral Passes**: Pass receiver coordinates and pass velocity are not recorded in official play-by-play; rush and lateral movement are proxied using previous event elapsed time and distance deltas.
5. **Sample Size Caveats**: For individual skaters and goaltenders, $G - xG$ and $GSAx$ require multi-month sample sizes (>500–1,000 shot attempts) before concluding definitive finishing or saving talent over variance.

