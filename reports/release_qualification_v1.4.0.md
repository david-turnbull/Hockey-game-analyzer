# PuckLens v1.4.0 Release Qualification Report

**Report Status:** FINAL RELEASE QUALIFIED  
**Target Release:** `v1.4.0`  
**Qualification Date:** September 2026  
**Audited Target Branch:** `v1.4`  

---

## 1. System & Environment Runtime Verification

* **Final Pre-Merge Release Candidate SHA:** `141a8c33863988911268e49c5c28f890231f7b92` *(The final immutable release Git SHA will be the merged commit tagged `v1.4.0`.)*
* **Authoritative Model-Training Runtime:** `Python 3.12.10` | `scikit-learn 1.9.0` | `numpy 2.5.2`
* **CI Qualification Runtime:** `Python 3.12.10` (Pinned in `.github/workflows/tests.yml`)
* **Flask Version:** `3.1.2`
* **SQLAlchemy Version:** `2.0.38`
* **Dependency Lock Files:** [`constraints.txt`](../constraints.txt), [`requirements-release.txt`](../requirements-release.txt)
* **InconsistentVersionWarning Status:** VERIFIED ZERO (All model artifacts load under authoritative runtime without version mismatch warnings)

---

## 2. Frozen Model Artifact & Registry Hashes

| Artifact Description | File Path | Expected SHA-256 | Verified Status |
| :--- | :--- | :--- | :---: |
| **Win Probability Classifier** | [`models/forecasting/pucklens-win-v1.4.0.pkl`](../models/forecasting/pucklens-win-v1.4.0.pkl) | `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9` | **MATCH** |
| **Win Probability Manifest** | [`models/forecasting/pucklens-win-v1.4.0.json`](../models/forecasting/pucklens-win-v1.4.0.json) | Manifest metadata & schema version `v1` | **MATCH** |
| **Score Candidate Parameters** | [`models/forecasting/score_candidate_params_v1.4.0.json`](../models/forecasting/score_candidate_params_v1.4.0.json) | `a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701` | **MATCH** |

---

## 3. Database Schema & Index Verification

Migration script [`app/utils/db_migrator.py`](../app/utils/db_migrator.py) executes automatically on startup. Schema and index integrity verified:

- [x] Table `game_prediction` contains required columns: `prediction_type`, `model_sha256`, `feature_schema_version`, `run_id`, `input_cutoff_time_utc`, `scheduled_start_time_utc`, `feature_payload_json`, `feature_payload_sha256`.
- [x] Partial unique index `_game_official_pregame_uc` verified on `game_prediction (game_id) WHERE prediction_type = 'official_pregame'`.
- [x] Performance indexes verified: `idx_game_season_type`, `idx_game_home_start`, `idx_game_away_start`, `idx_game_start_utc`, `idx_game_date`, `idx_game_prediction_game_official`.
- [x] Migration execution fails closed on error (exception re-raised).

---

## 4. Stage 1–6 Invariant Checklist

| Invariant Requirement | Stage | Status | Verification Method |
| :--- | :---: | :---: | :--- |
| **Zero Synthetic Contamination** | Stage 1 | **PASSED** | Audited all training/evaluation data; 100% official NHL API data source. |
| **Frozen Model Integrity** | Stage 2 | **PASSED** | Model binary and score parameters untouched; exact SHA-256 match. |
| **Immutable Prediction Provenance** | Stage 3 | **PASSED** | Cutoff time, scheduled start, payload JSON, and SHA snapshot captured per prediction. |
| **No Retrospective Predictions** | Stage 3 | **PASSED** | Predictions created strictly prior to puck drop; duplicate pregame creation rejected by `_game_official_pregame_uc`. |
| **Complete Schedule Parity** | Stage 4 | **PASSED** | 5 seasons audited (2021-22 to 2025-26); exactly 1,312/1,312 games each; 32 teams x 82 games. |
| **Independent Poisson Retained** | Stage 5 | **PASSED** | Score model evaluation confirmed Poisson baseline retained; NegBinomial (`alpha=0.0`) and Bivariate (`lambda3=0.0`) collapse to Poisson. Dixon-Coles improvement negligible. |
| **Read-Only GET Routes** | Stage 6 | **PASSED** | `/forecast` and `/api/v1/forecast/upcoming` perform zero prediction side-effects. |
| **Prediction Automation Pathways** | Stage 6 | **PASSED** | CLI (`scripts/generate_official_predictions.py`) provides primary scheduled path; `POST /api/v1/forecast/game/<game_id>/generate` provides fail-closed administrative path. |
| **48-Hour Forecast Horizon** | Stage 6 | **PASSED** | Configured via `FORECAST_DEFAULT_LOOKAHEAD_HOURS=48` across API, UI, CLI generator, and monitoring. |
| **Operational Health & Readiness** | Stage 6 | **PASSED** | `/api/v1/health` and `/api/v1/ready` probes operational; fail-closed on DB, index, artifact, or secret key failure. |
| **Sample-Aware Monitoring** | Stage 6 | **PASSED** | Operational calibration groups metrics by model version and SHA; clips probabilities (`1e-15`); handles small samples. |

---

## 5. Authoritative Performance Metric Summary

| Stage / Evaluation Window | Log Loss | Brier Score | Accuracy | ECE | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Original 2024-25 Frozen Holdout** | `0.6848` | `0.2431` | `57.55%` | `0.0315` | Pre-repair schedule audit |
| **Stage 4 Repaired 2024-25 Re-evaluation** | `0.6843` | `0.2429` | `57.70%` | `0.0277` | Model artifact unchanged (`63cf3cec...`); input data repair shift |
| **2025-26 External Temporal Validation** | `0.6910` | `0.2479` | `54.19%` | `0.0332` | Out-of-time future season evaluation |

---

## 6. Production Security & Configuration Hardening

* **Public Ingestion Default:** `ALLOW_PUBLIC_INGESTION=False` in `ProductionConfig`.
* **Prediction Generation Default:** `ALLOW_PREDICTION_GENERATION=False` in `ProductionConfig`.
* **Prediction Generation API Route:** `POST /api/v1/forecast/game/<game_id>/generate` (Requires `ALLOW_PREDICTION_GENERATION=True` and `X-Generation-Token` / `Bearer` token).
* **Prediction Token:** `PREDICTION_GENERATION_TOKEN` driven exclusively by environment variable.
* **Production Secret Key:** `SECRET_KEY` is enforced at startup by `create_app`; a missing key causes an immediate fail-closed `ValueError`, so the production application does not start. When the application is running, `/api/v1/ready` also validates production-secret state as part of readiness.

---

## 7. Automated Test Suite Qualification Environments

* **Pinned Release Test Framework:** `pytest 8.3.4` (Lock file `requirements-release.txt`)
* **Final GitHub Actions CI Qualification Run (#111):**
  - **Runtime:** Python `3.12.10` | pytest `8.3.4`
  - **Result:** **202 PASSED, 0 FAILED, 24 WARNINGS** in `14.66s`
  - **Release Candidate SHA:** `141a8c33863988911268e49c5c28f890231f7b92`
  - **Non-Blocking Warnings:** Deprecation and feature warnings under CI test runner environment.

---

## 8. Release Qualification Certification

- [x] All 7 implementation stages completed and verified against roadmap requirements.
- [x] Frozen model artifacts verified with exact SHA-256 hashes.
- [x] Schedule parity verified across 5 seasons (6,560 total games).
- [x] Full test suite (202 tests) passing cleanly under Python 3.12.10.
- [x] Production fail-closed security safeguards active.
- [x] Documentation ([`README.md`](../README.md), [`docs/release_notes_v1.4.0.md`](../docs/release_notes_v1.4.0.md)) fully updated for `v1.4.0`.

**PuckLens v1.4.0 is certified RELEASE QUALIFIED and ready for production deployment.**
