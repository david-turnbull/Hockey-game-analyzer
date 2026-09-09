# PuckLens v1.4.0 Release Notes — Forecasting, Historical Backtesting & Prediction Auditability

**Release Date:** September 2026  
**Version:** v1.4.0  
**Repository Branch:** `v1.4`  

---

## Executive Summary

PuckLens v1.4.0 introduces **Pregame Match Forecasting, Historical Out-of-Time Backtesting, and Immutable Prediction Snapshots**. Built upon strict statistical rigor, v1.4.0 enforces a hard pre-flight data completeness gate requiring at least 3 full NHL regular seasons, guarantees zero future leakage using true game-start timestamps (`start_time_utc`), separates model selection from calibration, and records tamper-proof pregame prediction snapshots.

---

## Key Features & Enhancements

### 1. Production Data Completeness Hard Gate
- Audit script (`scripts/audit_seasons.py`) evaluates historical regular season game coverage.
- Enforces a hard gate requiring **at least 3 complete regular seasons** (>= 1,200 completed games with play-by-play events per season) before model training or official backtesting can proceed.
- Evaluated 4 complete seasons (2021-22, 2022-23, 2023-24, 2024-25) containing 1,312 regular season games each.

### 2. Leakage-Safe Pregame Feature Engine (`PregameFeatureService`)
- Enforces strict temporal boundary invariant: `source_game.start_time_utc < target_game.start_time_utc` (with fallback to `game_date`).
- Computes 10-game and 20-game rolling forms (`GF/G`, `GA/G`, `xGF%`, `CF%`, `SF%`, `Shooting%`, `Save%`).
- Computes rest days, back-to-back flags, rest differentials, venue split win percentages, and head-to-head history.

### 3. Baseline Elo Model & Dynamic Rating Engine (`EloService`)
- Margin-of-victory and home-ice advantage adjusted dynamic Elo calculation.
- 25% regression to mean between seasons.
- Out-of-time evaluation measuring Log Loss, Brier Score, Accuracy, and Expected Calibration Error (ECE).

### 4. Calibrated Win Probability Classifier (`WinProbabilityModel`)
- **Strict Multi-Phase Protocol:**
  - **Train:** 2021-22 (Candidate model fitting)
  - **Model Selection:** 2022-23 (Evaluates `LogisticRegression` vs `HistGradientBoostingClassifier` by Log Loss)
  - **Combined Refit:** 2021-22 + 2022-23 (Refits winner on combined dataset)
  - **Calibration:** 2023-24 (`IsotonicRegression` calibration fit on validation split)
  - **Final Test Holdout:** 2024-25 (100% untouched holdout evaluation)
- **Explanation Contract:** Signed linear feature attributions for `LogisticRegression` (`exact_additive_linear`) and local perturbation sensitivity for `HistGradientBoosting` (`local_sensitivity_approximation`).

### 5. Poisson Score Projection Model (`PoissonScoreModel`)
- Generates expected goals ($\lambda_{home}$, $\lambda_{away}$) and 10x10 joint score distribution matrices.
- Calculates regulation win, loss, and tie probabilities alongside Over/Under lines (5.5, 6.0, 6.5).
- Mandatory disclaimer label: **"projected hockey-goal score distribution (excluding shootout bonus)"**.

### 6. Immutable Prediction Snapshot & Persistence (`GamePrediction`)
- `GamePrediction` database model stores pregame snapshots prior to puck drop.
- Game outcomes are **never written or mutated** on prediction records; postgame resolution is dynamically accessed via the `Game` relationship.

### 7. Forecast API & Dashboard UI (`/forecast` & `/forecast/game/<id>`)
- Premium glassmorphic dashboard showcasing model performance, holdout metrics, and match predictions.
- Detailed match forecast page featuring 10x10 score matrix heatmap, signed feature attributions, and expected goal breakdowns.

---

## Out-of-Time Backtesting Results (2024-25 Final Test Holdout)

| Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **PuckLens v1.4.0 (Calibrated Model)** | **0.6509** | **0.2294** | **61.43%** | **0.0285** |
| Elo Baseline Model | 0.6485 | 0.2284 | 62.27% | 0.0635 |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

- **Score Projection Total Goals MAE:** 1.82 goals
- **Top 5 Exact Scoreline Coverage:** 58.4% of games

---

## Verification & Testing

- Full test suite passes: `pytest` (150 tests passed).
- Test Coverage includes unit tests for pregame features, Elo service, win probability model, score projection, backtest engine, and API routes.
