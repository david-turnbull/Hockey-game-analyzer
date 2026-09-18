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


---

## 5. Phase 2 Roadmap — Forecast Quality Investigation & Persistent Team Strength

Phase 2 focuses on explaining the observed gap between the production forecasting model and the Elo baseline, then improving the feature system without weakening temporal integrity or overfitting to a previously observed benchmark season.

### Guiding Rule: Diagnostic-First, Leakage-Safe Iteration
- The existing 2024-25 evaluation remains a frozen reference benchmark and must not be repeatedly optimized against while still being described as an untouched holdout.
- Feature and architecture decisions should be developed using leakage-safe historical / walk-forward experiments on earlier seasons.
- A new external validation season should be used for final confirmation when a complete production-quality season is available (prefer 2025-26 once the data-completeness gate passes).
- Every season-to-date statistic must use only games with `source_game.start_time_utc < target_game.start_time_utc`; no historical forecast may use end-of-season totals that were not known at the target game's puck drop.

### Phase 2A — Probe Why Elo Outperforms the Current HGB Forecast

Current 2024-25 reference metrics show the Dynamic Elo baseline outperforming the calibrated HistGradientBoosting model on Log Loss, Brier Score, and Accuracy. Before changing production behavior, add a repeatable diagnostic harness that compares:

1. Naive 50/50 benchmark.
2. Dynamic Elo baseline.
3. Logistic Regression using the current feature set.
4. Raw HistGradientBoosting probabilities.
5. Isotonic-calibrated HistGradientBoosting probabilities.
6. Elo + Logistic Regression.
7. Elo + HistGradientBoosting.

Required diagnostics:
- Paired per-game Log Loss and Brier deltas between candidate models.
- Bootstrap confidence intervals for paired metric differences.
- ROC-AUC / discrimination metrics in addition to Log Loss, Brier, Accuracy, and ECE.
- Calibration curves for raw and calibrated probabilities.
- Performance splits by early/mid/late season, home/away, back-to-back status, Elo mismatch size, and disagreement between Elo and xG-based form.
- Inspection of the largest per-game wins/losses versus Elo to identify failure modes.
- Explicit review of the unusually large drop from the 2022-23 selection result to the 2024-25 reference result.

### Phase 2B — Add Elo as a First-Class Pregame Feature

Treat Elo as a persistent team-strength prior rather than only a benchmark.

Candidate leakage-safe features:
- `home_elo_pregame`
- `away_elo_pregame`
- `elo_diff`
- optionally `elo_home_adv_adjusted_diff`

Requirements:
- Elo for a target game must be computed strictly from games completed before that game's start time.
- Postgame Elo updates occur only after the prediction for that game has been recorded.
- Between-season regression-to-mean remains explicit and versioned.
- Elo feature generation must be reproducible during training, backtesting, and live prediction.
- The pure Elo model remains available as a benchmark even if Elo is incorporated into the production feature vector.

Primary hypothesis:
> Persistent team strength from Elo may complement short-term hockey signals such as xGF%, Corsi, goal differential, rest, and schedule context better than either approach performs alone.

### Phase 2C — Improve Full-Season / Season-to-Date Team Strength Features

The current forecasting feature set relies heavily on L10/L20 windows. Add longer-horizon, leakage-safe season-to-date context so the model can distinguish persistent team quality from short-term form.

Candidate season-to-date features:
- GF/G and GA/G.
- Goal differential per game.
- xGF% and xGA / xGF rates.
- CF% and FF% where available.
- SF%.
- Shooting percentage and save percentage.
- Record / points percentage.
- Home and away season-to-date splits where sample size is adequate.
- Season-to-date special-teams metrics if later supported by the underlying data model.

For each team-strength statistic, evaluate multiple memory formulations rather than assuming one window:
- L5.
- L10.
- L20.
- L40.
- Season-to-date.
- Exponentially weighted history.
- Prior-season carryover regressed toward league average for early-season stabilization.

Early-season safeguards:
- Include sample-count / games-played context where useful.
- Shrink unstable percentages toward league average when the season sample is small.
- Avoid treating 3-5 early-season games as equally reliable to 50+ games.
- Do not use final full-season statistics when recreating historical forecasts.

### Phase 2D — Feature Ablation & Simplification

Run controlled ablation experiments to determine which features improve out-of-time generalization and which add noise.

Minimum experiment set:
- Elo only.
- Existing hockey features only.
- Elo + existing hockey features.
- Elo + xGF form + rest / B2B.
- Full hybrid model minus H2H.
- Full hybrid model minus venue splits.
- Full hybrid model minus Corsi.
- Full hybrid model minus goal differential.
- Full hybrid model minus short-term xGF.
- Full hybrid model minus season-to-date features.

Prefer the simplest model that produces a reproducible out-of-time improvement. A larger feature set should not be retained merely because it improves in-sample fit.

### Phase 2E — Candidate Promotion Criteria

A revised v1.4 forecasting candidate should only replace the current production artifact if it:
- Improves out-of-time Log Loss and/or Brier Score against both the current production model and Elo benchmark on a genuinely external validation period.
- Does not materially degrade calibration.
- Preserves the strict temporal cutoff invariant.
- Has reproducible feature generation and artifact provenance.
- Includes an updated feature schema version and model manifest.
- Passes regression, leakage, snapshot-integrity, and prediction-lifecycle tests.

### Proposed Phase 2 Target Files
1. `app/services/elo_service.py`
2. `app/services/pregame_feature_service.py`
3. `app/analytics/forecasting/win_probability.py`
4. `app/analytics/forecasting/backtest_engine.py`
5. `scripts/run_backtest.py`
6. New diagnostic / ablation script under `scripts/`
7. `tests/test_elo_service.py`
8. `tests/test_pregame_feature_service.py`
9. `tests/test_stage4_validation.py`
10. New tests covering season-to-date features, Elo feature chronology, ablation reproducibility, and early-season shrinkage.

### Proposed Phase 2 Tests
- `test_elo_feature_uses_only_prior_games`
- `test_elo_updates_after_prediction_not_before`
- `test_season_to_date_features_use_only_prior_games`
- `test_historical_features_never_use_final_season_totals`
- `test_early_season_shrinkage_is_deterministic`
- `test_exponential_weighting_has_no_future_leakage`
- `test_raw_and_calibrated_probabilities_are_reported_separately`
- `test_ablation_runs_are_reproducible`
- `test_external_validation_season_is_excluded_from_fitting_and_selection`
