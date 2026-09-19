# PuckLens v1.4 Forecasting Methodology & Temporal Boundary Integrity

## 1. Overview

PuckLens v1.4 provides pregame game outcome forecasts and expected score distributions for NHL regular season games. The forecasting engine is designed around three principles:
1. **Zero Future Information Leakage**: Strict temporal boundary enforcement prior to puck drop.
2. **Model Selection & Calibration Decoupling**: Candidate model selection on validation data separated from post-hoc probability calibration.
3. **Auditability & Provenance**: Immutable snapshot recording and provenance-gated training.

---

## 2. Temporal Boundary & Leakage-Safe Feature Engineering

### Temporal Invariant
For any target game $G_{target}$ scheduled at $T_{start} = \text{target\_game.start\_time\_utc}$, all historical rolling metrics (team form, expected goals, head-to-head records, venue splits) are calculated strictly using prior games $G_{source}$ satisfying:
$$G_{source}.\text{start\_time\_utc} < G_{target}.\text{start\_time\_utc}$$
*(with fallback to `game_date` for legacy records lacking UTC timestamps)*.

### Pregame Features (11 Feature Vectors)
- `rest_differential`: Home team rest days minus away team rest days.
- `home_is_b2b`: Indicator if home team is playing on back-to-back consecutive days.
- `away_is_b2b`: Indicator if away team is playing on back-to-back consecutive days.
- `l10_xgf_pct_diff`: Difference in last 10 games rolling expected goals percentage ($xGF\%_{home} - xGF\%_{away}$).
- `l10_cf_pct_diff`: Difference in last 10 games rolling Corsi percentage ($CF\%_{home} - CF\%_{away}$).
- `l10_goal_diff_per_game`: Difference in last 10 games average goal differential per game.
- `l20_xgf_pct_diff`: Difference in last 20 games rolling expected goals percentage.
- `home_venue_l10_win_pct`: Home team win percentage in last 10 home games.
- `away_venue_l10_win_pct`: Away team win percentage in last 10 away games.
- `h2h_home_win_pct`: Home team historical win percentage against away team.
- `h2h_home_gd_avg`: Home team historical average goal differential against away team.

---

## 3. Out-of-Time Model Protocol & Calibration

### Multi-Season Temporal Protocol
To evaluate model performance without future leakage, the 4-season protocol is structured as follows:

| Protocol Phase | Season | Purpose |
|---|---|---|
| **Train** | 2021-22 | Candidate model parameter fitting (`LogisticRegression`, `HistGradientBoosting`) |
| **Model Selection** | 2022-23 | Select best architecture using out-of-sample Log Loss on 2022-23 regular season |
| **Combined Refit** | 2021-22 + 2022-23 | Refit winning architecture on combined 2-season dataset |
| **Calibration** | 2023-24 | Fit `IsotonicRegression` probability calibrator on 2023-24 validation predictions |
| **Final Test Holdout** | 2024-25 | 100% untouched holdout evaluation for final metrics (Log Loss, Brier Score, Accuracy, ECE) |

### Probability Calibration
Raw model output probabilities $p_{raw}$ are transformed using Isotonic Regression:
$$p_{calibrated} = \text{Isotonic.transform}(p_{raw})$$
Calibrated probabilities are clamped to $[0.01, 0.99]$ to guarantee numerical stability.

---

## 4. Score Projection Model (`PoissonScoreModel`)

Expected team goals $\lambda_{home}$ and $\lambda_{away}$ are projected using team 10-game offensive and defensive rates.
Joint scoreline probabilities $P(\text{Home}=i, \text{Away}=j)$ are computed via independent Poisson distributions up to $10 \times 10$ goals:
$$P(\text{Home}=i, \text{Away}=j) = \frac{\lambda_{home}^i e^{-\lambda_{home}}}{i!} \times \frac{\lambda_{away}^j e^{-\lambda_{away}}}{j!}$$

### Disclaimer Label
All score projection views present the mandatory disclaimer label:
> **"projected hockey-goal score distribution (excluding shootout bonus)"**

---

## 5. Official Prediction Persistence (`GamePrediction`)

Before puck drop, official prediction snapshots are saved to the `GamePrediction` table with model version `v1.4.0`. Once persisted, prediction records are **immutable** and never overwritten postgame. Ground truth outcomes are retrieved dynamically via the `Game` relationship.
