# PuckLens v1.4 Product-Readiness Audit & Baseline Report

**Audit Date:** September 2026  
**Repository Branch:** `v1.4`  
**Target Milestone:** v1.4 Product-Grade Forecasting, Validation & Prediction Integrity

---

## 1. Executive Summary

PuckLens is transitioning from a demonstration application into a production-grade hockey analytics product. This Phase 0 audit evaluates the current forecasting subsystem against commercial product readiness standards: correctness, reproducibility, data/model integrity, auditability, explicit failure handling, and strict separation of dev/test from production behavior.

---

## 2. Subsystem Audit Findings

### A. Data & Provenance Status
- **Target Seasons:** 2021-22, 2022-23, 2023-24, 2024-25.
- **Provenance Column:** `Game.data_source` exists (`nhl_api` vs `synthetic_test`).
- **Ingestion Resilience:** Retries (exponential backoff) and JSON disk cache validation exist in `NHLApiClient`.
- **Completeness & Audit Gate:** `scripts/audit_seasons.py` tracks feature-level completeness across regular season games and enforces the production training gate ($\ge 3$ complete real seasons with 0 synthetic games).

### B. Forecasting Architecture
- **Features (11):** `rest_differential`, `home_is_b2b`, `away_is_b2b`, `l10_xgf_pct_diff`, `l10_cf_pct_diff`, `l10_goal_diff_per_game`, `l20_xgf_pct_diff`, `home_venue_l10_win_pct`, `away_venue_l10_win_pct`, `h2h_home_win_pct`, `h2h_home_gd_avg`.
- **Temporal Cutoff:** Enforced in `PregameFeatureService` (`source_game.start_time_utc < target_game.start_time_utc`).
- **Model Protocol:** Train (2021-22), Selection (2022-23 by Log Loss), Combined Refit (2021-22 + 2022-23), Calibration (2023-24 Isotonic Regression), Holdout Test (2024-25).
- **Candidate Classifiers:** `LogisticRegression` and `HistGradientBoostingClassifier`.
- **Score Model:** Independent Poisson score distribution projection (`PoissonScoreModel`).

### C. Prediction Persistence & Lifecycle
- **Database Model (`GamePrediction`):** Stores `prediction_id`, `game_id`, `created_at`, `home_win_probability`, `away_win_probability`, `expected_home_goals`, `expected_away_goals`, `score_matrix_json`, `feature_importance_json`, `model_version`, `is_official`.
- **Outcome Resolution:** Dynamic property via `Game` relationship (`is_outcome_resolved`, `actual_winner`).

---

## 3. Product Risks & Identified Defects

| Defect ID | Component | Current Unacceptable Behavior | Required Product Behavior |
|---|---|---|---|
| **PR-01** | `ForecastService.get_trained_win_model` | Silently auto-trains model at runtime during web request if `.pkl` file is missing. | **Fail Closed**: Throw explicit `MODEL_UNAVAILABLE` error; never auto-train on HTTP request. |
| **PR-02** | `WinProbabilityModel.predict_game_probability` | Initializes a 10-dummy-sample `LogisticRegression` if `self.model is None`. | **Fail Closed**: Throw exception when unfitted model attempts prediction. |
| **PR-03** | `ForecastService.get_or_create_prediction` | Generates retrospective official predictions for completed past games if unpredicted. | **Strict Cutoff**: Official pregame predictions may ONLY be created when `now_utc < start_time_utc`. |
| **PR-04** | `ForecastService.get_upcoming_forecasts` | Orders games by `start_time_utc desc` without filtering `start_time_utc > now_utc`, returning past games. | **Upcoming Filter**: Filter `start_time_utc > now_utc` ordered ascending by start time. |
| **PR-05** | `GamePrediction` Schema | Missing SHA-256 artifact hash, feature snapshot JSON, and input cutoff timestamp. | **Provenance Tracking**: Persist SHA-256 artifact hash, complete feature payload JSON, and input cutoff timestamp. |
| **PR-06** | `GamePrediction` Constraints | No database unique constraint on `(game_id, model_version, is_official)`. | **Race Protection**: Unique DB constraint preventing duplicate predictions. |
| **PR-07** | Model Registry | No explicit JSON model manifest metadata (`models/forecasting/pucklens-win-v1.4.0.json`). | **Artifact Registry**: Publish explicit model metadata manifest with SHA-256 verification. |
| **PR-08** | API Error Handling | Generic 404/500 responses on missing model/features. | **Structured API Errors**: Return explicit status codes (`MODEL_UNAVAILABLE`, `GAME_ALREADY_STARTED`, etc.). |

---

## 4. Phase 1 Implementation Plan & Target Files

Phase 1 focuses on **Establishing the Official Historical Backtest** on real NHL data, validating temporal integrity, and producing authoritative reports.

### Target Files to Modify in Phase 1:
1. `app/analytics/forecasting/backtest_engine.py`
2. `app/analytics/forecasting/win_probability.py`
3. `scripts/run_backtest.py`
4. `reports/backtest_results_v1.4.0.json`
5. `reports/backtest_results_v1.4.0.md`
6. `tests/test_out_of_time_validation.py`

### Proposed Phase 1 Tests:
- `test_test_season_never_used_in_fitting`: Proves 2024-25 holdout is untouched during candidate training and selection.
- `test_calibration_season_isolated_from_selection`: Proves 2023-24 calibration data is not used during candidate selection.
- `test_source_games_precede_target_games`: Validates temporal cutoff invariant (`source.start_time_utc < target.start_time_utc`).
- `test_synthetic_games_blocked_from_production_training`: Verifies synthetic data gate blocks model training.
- `test_holdout_predictions_use_frozen_model`: Verifies holdout evaluation uses frozen refitted model.
