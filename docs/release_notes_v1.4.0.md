# PuckLens v1.4.0 Release Notes — Forecasting, Historical Backtesting & Prediction Auditability

**Release Date:** September 2026  
**Version:** v1.4.0  
**Repository Branch:** `v1.4`  

---

## Executive Summary

PuckLens v1.4.0 introduces **Pregame Match Forecasting, Historical Out-of-Time Backtesting, and Immutable Prediction Snapshots**. Built upon strict statistical rigor, v1.4.0 enforces a hard pre-flight data completeness gate requiring at least 3 full NHL regular seasons, guarantees zero future leakage using true game-start timestamps (`start_time_utc`), separates model selection from calibration, and records tamper-proof pregame prediction snapshots.

---

## Key Features & Enhancements

### 1. Production Data Completeness Hard Gate & Provenance Hardening
- Audit script (`scripts/audit_seasons.py`) evaluates historical regular season game coverage across 7 feature metrics.
- Enforces a hard gate requiring **at least 3 complete regular seasons** (1,312 completed games, $\ge 99\%$ PBP coverage, $\ge 99\%$ UTC timestamp coverage per season) and **0 synthetic test games** before model training or official backtesting can proceed.
- Quarantines synthetic data generation to `scripts/generate_synthetic_test_data.py --testing-only` with `data_source = 'synthetic_test'`. Any synthetic game present in the database automatically invalidates forecast training and official backtesting.
- Re-ingestion in `db_loader.py` updates `start_time_utc` and `data_source` on existing records.
- API client (`NHLApiClient`) features bounded exponential backoff retries and malformed JSON disk cache validation.
- Multi-season ingestion pipeline utility (`scripts/ingest_forecast_history.py`) and safety-gated database reset utility (`scripts/reset_historical_data.py --confirm`).

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

## Out-of-Time Backtesting Results

> [!WARNING]
> **Pending Historical Validation**: Derived performance metrics generated during early development using synthetic/partial fixtures have been invalidated. Official backtesting requires ingesting at least 3 complete real regular seasons from the NHL API (`python scripts/ingest_forecast_history.py`), followed by running `python scripts/run_backtest.py`.

---

## Verification & Testing

- Comprehensive unit test suite in `tests/test_provenance_hardening.py` covers synthetic data isolation, `start_time_utc` replacement, audit metric computation, production training gate enforcement, failure manifests, and malformed cache handling.
- Full test suite passes via `pytest`.
