# PuckLens - Version 1.2.1 Release Notes

**Release Date:** September 2026  
**Theme:** Predictive Analytics Hardening, Mathematical Rigor, and Test Isolation Pass

PuckLens version 1.2.1 is a focused release-hardening and mathematical integrity update following the v1.2.0 predictive analytics milestone. This pass eliminates coordinate-frame discrepancies, establishes an inviolable domain boundary for blocked shot attempts, resolves training/serving missingness skew, seals held-out test set evaluation, enriches runtime provenance, and removes live network dependencies from the automated test suite.

---

## 1. Priority 0: Blocked Shots Invariant Enforcement

### Domain Rule: `Blocked → xG = NULL`
- **Fenwick Population Isolation:** Blocked shot attempts (`outcome == 'Blocked'`) are strictly ineligible for Expected Goals (`Shot.xg = None`, `Shot.model_name = None`, `Shot.model_version = None`, `Shot.prediction_method = None`).
- **Metric Boundaries:**
  - **Corsi ($CF$, $CA$, $CF\%$):** Retains all shot attempts including blocked shots.
  - **Fenwick ($FF$, $FA$, $FF\%$) and Expected Goals ($xGF$, $xGA$, $xG\%$):** Blocked shots are completely barred from receiving or contributing to xG or Fenwick/unblocked-attempt-derived metrics across all ingestion paths, backfill utilities, database migrations, services, and API endpoints.
- **Components Hardened:**
  - `data_pipeline/transform/normalizer.py`: Normalizer only evaluates and assigns xG for unblocked attempts (`Goal`, `Saved`, `Missed`).
  - `scripts/backfill_xg.py`: Exclusively calculates xG for unblocked attempts and explicitly purges any stale xG and provenance values from historical blocked rows.
  - `app/utils/db_migrator.py`: Runs automated migration SQL cleanup clearing xG for blocked attempts on legacy databases.
  - `app/services/game_service.py`: All team and 5v5 game xG totals, period breakdowns, and cumulative xG timeline series strictly filter for unblocked outcomes.
  - `app/services/skater_stats_service.py`: Individual skater xG totals enforce unblocked outcome filtering.
  - `app/services/unit_service.py`: Fixed xG accumulation to occur within the Fenwick/unblocked attempt branch rather than the Corsi branch.
  - `app/routes/api.py`: Serializes `"xg": null` and `"model_version": null` for blocked shots.
  - `scripts/database_diagnostics.py`: Added an automated integrity check detecting any blocked attempts with non-null xG.

---

## 2. Priority 1: Coordinate-Frame Consistency & Neutral Imputation

### Sequential Event Geometry
- **Raw Physical Distance:** `distance_from_prev_event` ($\Delta d$) strictly calculates raw Euclidean distance between consecutive rink events:
  $$\Delta d = \sqrt{(x_{curr} - x_{prev})^2 + (y_{curr} - y_{prev})^2}$$
- **Unified Attacking Transform:** `get_attacking_coordinate_transform` inspects attacking direction once per shot attempt. The identical transform is applied to both current and previous coordinates when deriving relative net-angle changes (`angle_change`), guaranteeing complete symmetry regardless of rink orientation.

### Elimination of Training/Serving Missing-Data Skew
- **Authoritative Standardization:** `ShotFeatureExtractor` serves as the authoritative feature extraction and imputation layer across all offline training and online inference paths.
- **Explicit Unknown Categories:** Unmapped shot types and strength states standardize to explicit `'UNKNOWN'` categories rather than forcing arbitrary defaults like `'wrist'` or `'EV'`.
- **Controlled Neutral Imputation:** Missing coordinates are cleanly imputed to neutral values ($45.0$ ft distance, $0.0^\circ$ angle, `coordinates_missing = 1`).
- **No Bypassing Defaults:** Removed hardcoded defaults (`30.0`, `'wrist'`, `'EV'`) from `XGService.predict_shot_xg`, allowing raw arguments to delegate cleanly to `ShotFeatureExtractor`.

---

## 3. Priority 1: Deterministic Offline Testing

### Player Metadata Ingestion Precedence
- **Network Isolation:** Eliminated live HTTP calls to `api-web.nhle.com` in `tests/test_metadata.py`, resolving 403 Forbidden failures in fresh CI environments lacking disk cache.
- **Roster Precedence Verification:** Implemented frozen fixtures proving canonical season roster metadata (`"L"`) takes precedence over play-by-play position defects (`"C"`) for Jonathan Huberdeau and defenseman position (`"D"`) for MacKenzie Weegar.
- **PBP Fallback Integrity:** Added a dedicated test confirming that when a player is absent from the season roster or the roster feed is empty, the pipeline gracefully falls back to play-by-play metadata.

---

## 4. Priority 2: Held-Out Test Set Isolation & Runtime Provenance

### Sealed Test Evaluation & Option B Retraining
- **Zero Leakage Pipeline:** `app/analytics/train_xg.py` does not inspect, evaluate, or log test set goal rates prior to candidate selection.
- **Option B Refit:** The selected Logistic Regression candidate architecture was refitted on the combined training and validation set (12,036 shots across 137 games) before a single, final evaluation on the untouched held-out test set (2,226 shots across 25 games).
- **Final Test Metrics:**
  - **Log Loss:** 0.2127
  - **Brier Score:** 0.0562
  - **ROC AUC:** 0.7494
  - **Expected Goals:** 150.27 xG vs 147.0 actual goals (6.75% vs 6.60%).

### Runtime Provenance & Pre-Deserialization Validation
- **Rich Metadata Persistence:** `models/xg/metadata.json` now records `joblib_version`, `python_version`, `platform`, and `git_commit` alongside algorithm parameters and data split metrics.
- **Pre-Deserialization Inspection:** `ModelRegistry.load_model()` parses `metadata.json` before unpickling artifacts with `joblib.load()`, verifying scikit-learn major version compatibility and providing diagnostic error logs if deserialization fails.

---

## 5. Verification & Test Suite Status

- **Automated Tests:** 88 passed, 0 failures across the complete test suite.
- **Execution Speed:** Full test suite runs offline in under 20 seconds.
- **Database Status:** Production database rescored (557 unblocked shots populated, 194 blocked shots cleared).
