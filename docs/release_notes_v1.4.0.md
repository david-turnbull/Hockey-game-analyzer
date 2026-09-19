# PuckLens v1.4.0 Release Notes

**Release Version:** `v1.4.0`  
**Release Date:** September 2026  
**Status:** Production Release Qualified  
**Authoritative Runtime Environment:** Python 3.12.10 | scikit-learn 1.9.0 | numpy 2.5.2  

---

## Executive Overview

PuckLens v1.4.0 marks the transition of PuckLens into an end-to-end, production-grade NHL game forecasting, expected goals (xG), and operational analytics platform. Built around a strictly calibrated, out-of-time evaluated HistGradientBoosting win probability classifier and an Independent Poisson score projection engine, v1.4.0 establishes complete prediction provenance, automated pregame prediction lifecycle enforcement, fail-closed operational safeguards, and real-time calibration monitoring.

---

## Stage-by-Stage Implementation & Architectural Highlights

### Stage 1 — Official Historical Backtest
* Built on 5 complete NHL regular seasons (2021–22 through 2025–26), comprising 6,560 regular-season games (exactly 1,312 games per season across 32 teams).
* Training dataset spans 2021–22 and 2022–23 (2,624 games). Isotonic calibration trained on 2023–24 (1,312 games).
* Strict zero synthetic contamination invariant enforced across all training and evaluation datasets.

### Stage 2 — Production Model Artifact & Registry
* Production win probability model frozen in `models/forecasting/pucklens-win-v1.4.0.pkl` with manifest `models/forecasting/pucklens-win-v1.4.0.json`.
* Score parameter candidate frozen in `models/forecasting/score_candidate_params_v1.4.0.json`.
* Model registry provides strict runtime validation, artifact SHA-256 verification, and fail-closed error handling.

### Stage 3 — Official Prediction Lifecycle
* Implemented immutable `GamePrediction` provenance capturing `input_cutoff_time_utc`, `scheduled_start_time_utc`, `feature_payload_json`, and `feature_payload_sha256`.
* Enforced database-level unique constraint `_game_official_pregame_uc` on `(game_id)` for `prediction_type = 'official_pregame'`.
* Retrospective official pregame predictions strictly prohibited; all official predictions must be generated prior to puck drop.

### Stage 4 — External Temporal Validation & Schedule Repair
* Conducted out-of-sample holdout validation on 2024–25 and out-of-time external temporal validation on 2025–26.
* Executed schedule repair resolving initial API missing game gaps, achieving 100% schedule parity (1,312/1,312 games) for all 5 seasons.

### Stage 5 — Score Projection Validation
* Evaluated four candidate score distribution frameworks: Independent Poisson, Negative Binomial, Bivariate Poisson, and Dixon-Coles.
* Confirmed Negative Binomial collapses to Poisson (`alpha = 0.0`) and Bivariate Poisson collapses to Poisson (`lambda3 = 0.0`).
* Dixon-Coles tie adjustment (`gamma = 0.0543`) produced statistically detectable but extremely small pre-shootout 3-class Brier improvements versus Independent Poisson: mean difference `-0.00074` in 2024–25 (95% CI `[-0.00085, -0.00061]`) and `-0.00027` in 2025–26 (95% CI `[-0.00039, -0.00015]`). The gains were too small and not broad enough across the wider distributional metrics to justify replacing the simpler Independent Poisson baseline.

### Stage 6 — Production Automation, Monitoring & Operational Reliability
* Built race-safe, idempotent CLI pregame prediction generator (`scripts/generate_official_predictions.py`).
* Implemented unified **48-Hour Forecast Horizon** across API (`/api/v1/forecast/upcoming`), UI (`/forecast`), CLI generator, and operational monitoring.
* Made all GET forecast routes strictly read-only with zero hidden prediction generation side-effects.
* Added health (`/api/v1/health`) and readiness (`/api/v1/ready`) probes validating DB, foreign keys, indexes, model loading, artifact SHA, and production secrets.
* Created sample-aware operational calibration monitoring (`/api/v1/monitoring/calibration`) grouped by model version and SHA.

### Stage 7 — Release Qualification
* Formally locked release environment dependencies in `requirements-release.txt` and `constraints.txt`.
* Verified complete test suite passing (199 passed, 0 failures; 3 warnings on local qualification run, 24 warnings on GitHub CI qualification run).
* Hardened production configuration with fail-closed checks for missing `SECRET_KEY`, public ingestion defaults (`ALLOW_PUBLIC_INGESTION=False`), and generation defaults (`ALLOW_PREDICTION_GENERATION=False`).

---

## Authoritative Model Performance Metrics

| Evaluation Dataset | Log Loss | Brier Score | Accuracy | ECE | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Original 2024–25 Frozen Holdout** | `0.6848` | `0.2431` | `57.55%` | `0.0315` | Pre-repair schedule audit |
| **Stage 4 Repaired 2024–25 Re-evaluation** | `0.6843` | `0.2429` | `57.70%` | `0.0277` | Model artifact unchanged; input repair shift |
| **2025–26 External Temporal Validation** | `0.6910` | `0.2479` | `54.19%` | `0.0332` | Out-of-time future season evaluation |

> [!NOTE]
> The win probability model artifact remained identical (`63cf3cec...`) across evaluations. The slight metric difference between the original and repaired 2024–25 holdouts is entirely attributable to historical input data repair.

---

## Authoritative Artifact Hashes

* **Win Probability Model Artifact (`models/forecasting/pucklens-win-v1.4.0.pkl`):**  
  `63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`
* **Score Parameter Candidate Artifact (`models/forecasting/score_candidate_params_v1.4.0.json`):**  
  `a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701`

---

## API & CLI Endpoint Reference

* `GET /api/v1/health` — Liveness probe (HTTP 200)
* `GET /api/v1/ready` — Operational readiness probe (HTTP 200 / 503)
* `GET /api/v1/forecast/upcoming` — Upcoming 48-hour game forecasts with availability metadata
* `GET /api/v1/monitoring/summary` — Pregame prediction coverage & unresolved game counts
* `GET /api/v1/monitoring/calibration` — Sample-aware calibration metrics grouped by model version
* `POST /api/v1/forecast/game/<game_id>/generate` — Admin pregame prediction generation endpoint (requires token + config flag)
* `python scripts/generate_official_predictions.py --lookahead-hours 48` — Primary scheduled pregame prediction automation CLI

---

## Known Limitations

1. **In-Season Roster / Injury Dynamics:** Pregame features are calculated strictly from past game statistics and rest schedules; player trade/injury updates on game day are not currently modeled in the pregame feature payload.
2. **OT/Shootout Dynamics:** Game win probabilities reflect overall regulation plus extra-time victory probability; specific shootout skill matrices are not modeled separately.
