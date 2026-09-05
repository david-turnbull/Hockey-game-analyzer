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

The production model was selected by comparing **Logistic Regression** (with standardized scaling and one-hot encoding) against a tuned **HistGradientBoostingClassifier** on the identical held-out chronological test set (2,226 shots, 147 actual goals):

| Metric | Logistic Regression (Selected) | Gradient Boosting | Target Direction |
| :--- | :--- | :--- | :--- |
| **Log Loss** | **0.2130** | 0.2162 | Lower is better |
| **Brier Score** | **0.0564** | 0.0565 | Lower is better |
| **ROC AUC** | **0.7498** | 0.7490 | Higher is better |
| **Total Expected Goals** | **148.74** | 139.37 | Target: 147.0 Actual Goals |
| **Expected Goal %** | **6.68%** | 6.26% | Target: 6.60% Actual |

### Selection Rationale:
In accordance with Milestone 6 criteria, the simpler and more interpretable **Logistic Regression** model was selected because it delivered:
1. Superior probability calibration (predicted 148.7 xG vs 147 actual goals, a 1.1% delta).
2. Lower Log Loss and lower Brier score on unseen games.
3. Total reproducibility and fast inference speed without complex black-box hyperparameters.

---

## 5. Performance by Hockey Segments

Observed calibration across shot distance brackets on held-out test games:
- **Inner Slot (<15 ft)**: Observed goal conversion: ~18.5%, Mean xG: ~19.1%
- **High Slot (15–30 ft)**: Observed goal conversion: ~10.4%, Mean xG: ~10.7%
- **Perimeter (30–45 ft)**: Observed goal conversion: ~4.9%, Mean xG: ~5.1%
- **Point / Deep (45+ ft)**: Observed goal conversion: ~1.8%, Mean xG: ~2.0%

---

## 6. Known Limitations

1. **Play-by-Play Coordinate Inaccuracies**: Official NHL play-by-play coordinates are recorded manually by arena official scorers and may exhibit venue-specific clustering or scorer bias.
2. **Absence of Player Tracking**: Optical tracking data (exact positions of all 10 skaters, goalie stance, stick blades) is proprietary to NHL EDGE and unavailable in standard public feeds.
3. **Screen / Traffic Estimation**: Public play-by-play feeds do not explicitly log visual screens or defender proximity; screening effects are partially proxied through distance, traffic, and rebound flags.
4. **Pre-Shot Lateral Passes**: Pass receiver coordinates and pass velocity are not recorded in official play-by-play; rush and lateral movement are proxied using previous event elapsed time and distance deltas.
5. **Sample Size Caveats**: For individual skaters and goaltenders, $G - xG$ and $GSAx$ require multi-month sample sizes (>500–1,000 shot attempts) before concluding definitive finishing or saving talent over variance.
