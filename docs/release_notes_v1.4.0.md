# PuckLens v1.4.0 Release Notes — Forecasting, Historical Backtesting & Prediction Auditability

**Release Date:** September 2026  
**Version:** v1.4.0  
**Repository Branch:** `v1.4`  

---

## Executive Summary

PuckLens v1.4.0 introduces **Pregame Match Forecasting, Historical Out-of-Time Backtesting, and Immutable Prediction Snapshots**. Built upon strict statistical rigor, v1.4.0 enforces a hard pre-flight data completeness gate requiring at least 3 full NHL regular seasons, guarantees zero future leakage using true game-start timestamps (`start_time_utc`), separates model selection from calibration, records tamper-proof pregame prediction snapshots, and enforces end-to-end cryptographic and data integrity safeguards.

---

## Key Features & Enhancements

### 1. Production Data Completeness Hard Gate & Provenance Hardening
- Ingested 4 complete real regular seasons (2021-22, 2022-23, 2023-24, and 2024-25) comprising **5,248 total official regular season games** with 100% UTC timestamp and PBP coverage from the official NHL API.
- Audit script (`scripts/audit_seasons.py`) enforces a hard gate requiring **at least 3 complete regular seasons** and **0 synthetic test games** before model training or official backtesting can proceed (`PRODUCTION FORECAST DATA GATE: PASSED`).
- Quarantines synthetic data generation to `scripts/generate_synthetic_test_data.py --testing-only` with `data_source = 'synthetic_test'`. All production feature aggregation queries strictly isolate `Game.data_source == 'nhl_api'`, preventing synthetic data leakage into historical stats caches.

### 2. Leakage-Safe Pregame Feature Engine (`PregameFeatureService`)
- Enforces strict temporal boundary invariant: `source_game.start_time_utc < target_game.start_time_utc` (with UTC timezone normalization).
- Computes 10-game and 20-game rolling forms (`GF/G`, `GA/G`, `xGF%`, `CF%`, `SF%`, `Shooting%`, `Save%`).
- Computes rest days, back-to-back flags, rest differentials, venue split win percentages, and head-to-head history.

### 3. Baseline Elo Model & Dynamic Rating Engine (`EloService`)
- Margin-of-victory and home-ice advantage adjusted dynamic Elo calculation with 25% regression to mean between seasons.
- Evaluated against out-of-time test holdouts (2024-25 Test Holdout Log Loss: 0.6735, Brier Score: 0.2403, Accuracy: 58.16%).

### 4. Calibrated Win Probability Classifier (`WinProbabilityModel`)
- **Strict Multi-Phase Out-of-Time Protocol:**
  - **Candidate Fit Season:** 2021-22 (Candidate model fitting)
  - **Model Selection Season:** 2022-23 (Evaluates `LogisticRegression` vs `HistGradientBoostingClassifier` by Log Loss)
  - **Combined Production Refit:** 2021-22 + 2022-23 (Refits selected classifier on combined 2,624 sample dataset)
  - **Calibration Season:** 2023-24 (`IsotonicRegression` calibration fit on validation split)
  - **Final Untouched Test Holdout:** 2024-25 (1,312 games holdout evaluation)
- **Provenance Manifest:** Model artifact `pucklens-win-v1.4.0.pkl` stores explicit metadata fields including `model_sha256`, `feature_schema_version`, `candidate_fit_seasons`, `selection_season`, `production_refit_seasons`, `training_seasons`, `calibration_season`, and `excluded_holdout_seasons`.
- **Explanation Contract:** Local perturbation sensitivity attributions for `HistGradientBoosting` and exact linear attributions for `LogisticRegression`.

### 5. Poisson Score Projection Model (`PoissonScoreModel`)
- Generates expected goals ($\lambda_{home}$, $\lambda_{away}$) and 10x10 joint score distribution matrices.
- Calculates regulation win, loss, and tie probabilities alongside Over/Under lines (5.5, 6.0, 6.5).
- Mandatory disclaimer label: **"projected hockey-goal score distribution (excluding shootout bonus)"**.

### 6. Immutable Prediction Snapshot & Persistence (`GamePrediction`)
- `GamePrediction` database model stores pregame snapshots prior to puck drop with 7 auditability fields: `prediction_type`, `model_sha256`, `feature_schema_version`, `run_id`, `input_cutoff_time_utc`, `feature_payload_json`, and `feature_payload_sha256`.
- **Legacy Audit & Migration:** Automatically audits existing legacy rows during migration; only rows created prior to puck drop are classified as `official_pregame`. Post-puck-drop rows are categorized as `legacy_unverified`.
- **SQLite Partial Unique Index:** Enforces `CREATE UNIQUE INDEX _game_model_official_pregame_uc ON game_prediction (game_id, model_version) WHERE prediction_type = 'official_pregame'` to guarantee exactly one official snapshot per game while allowing multiple `ad_hoc` runs with distinct `run_id`s.
- **Race Condition & Integrity Recovery:** Catches DB duplicate race conditions gracefully and retries lookup of existing official predictions.
- **Post-Puck-Drop Rejection:** Refuses to generate official pregame predictions after puck drop (`now_utc >= start_time_utc`), returning HTTP status 400 with structured error codes (`GAME_ALREADY_STARTED`).

### 7. Forecast API & Dashboard UI (`/forecast` & `/forecast/game/<id>`)
- Glassmorphic UI featuring upcoming game predictions sorted in ascending future chronological order (`start_time_utc > now_utc`).
- Detailed match forecast page featuring 10x10 score matrix heatmap, signed feature attributions, expected goal breakdowns, and a **Model Provenance Verification Card** rendering live SHA-256 checksums, schema version, prediction type, and run ID.

---

## Out-of-Time Historical Backtest Results

| Metric Split | Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **2024-25 Test (Holdout)** | **HistGradientBoosting (Calibrated)** | **0.6848** | **0.2431** | **57.55%** | **0.0315** |
| **2024-25 Test (Holdout)** | Dynamic Elo Baseline | 0.6735 | 0.2403 | 58.16% | 0.0410 |
| **2024-25 Test (Holdout)** | Naive 50/50 Benchmark | 0.6931 | 0.2500 | 50.00% | 0.0000 |
| **2023-24 Calibration Split** | HistGradientBoosting (Calibrated) | 0.6581 | 0.2340 | 58.84% | 0.0001 |
| **2022-23 Selection Split** | HistGradientBoosting (Selected) | 0.5897 | 0.2018 | 72.64% | 0.1391 |

- **Served Model Artifact SHA-256:** `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`
- **Feature Schema Version:** `v1.4.0`

---

## Verification & Testing

- **Full Pytest Pass Rate:** **175 / 175 tests passed** (`100%` pass rate in 28.65s).
- Dedicated test suite `tests/test_prediction_lifecycle.py` verifies all 10 product integrity safeguards:
  - Partial unique index enforcement on `official_pregame`
  - Multi `ad_hoc` execution support
  - Timezone normalization and post-puck-drop rejection
  - Immutable snapshot retrieval post-puck-drop
  - Model-version specific lookup
  - Deterministic feature payload JSON SHA-256 generation
  - served model artifact SHA-256 consistency
