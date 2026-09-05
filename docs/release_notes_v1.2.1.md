# PuckLens - Version 1.2.1 Release Notes

**Release Date:** September 2026  
**Theme:** Predictive Analytics Hardening, Provenance Tracking, and Methodological Rigor

PuckLens version 1.2.1 is a targeted engineering and statistical hardening release for the predictive analytics engine. It solidifies model validation methodology, isolates held-out test data, establishes granular prediction provenance, clarifies shooting population denominators, refines spatial and sequential feature extraction, strengthens dependency boundaries, and expands auditability across the platform.

---

## 1. Methodological Rigor & Data Leakage Prevention

### Validation Log Loss Model Selection
- Candidate model comparison and configuration selection are now evaluated **strictly on the chronological validation set** (2,176 shots across 24 games).
- Primary decision metric is **Validation Log Loss** (Logistic Regression candidate: 0.2325 vs Gradient Boosting candidate: 0.2328).
- The held-out test set is kept completely isolated and is **never accessed** during candidate pruning or hyperparameter selection.

### Production Retraining (Option B)
- Following frozen configuration selection, the winning Logistic Regression pipeline is refitted on the combined training and validation set (12,036 unblocked shot attempts across 137 games).
- The refitted production model is evaluated **exactly once** on the untouched chronological test set (2,226 shots across 25 games):
  - **Test Log Loss:** 0.2127
  - **Test Brier Score:** 0.0563
  - **Test ROC AUC:** 0.7493
  - **Expected Goals:** 150.44 vs 147.0 Actual Goals (+2.3% delta)
- The serialized model artifact (`models/xg/xg_v1.pkl`) is preserved unchanged after this final evaluation.

---

## 2. Granular Prediction Provenance

### Independent Provenance Tracking
- Added independent storage of prediction provenance attributes to the `Shot` entity:
  - `model_name`: Model identifier (e.g., `pucklens-xg-logistic`, `pucklens-xg-heuristic`)
  - `model_version`: Semantic version string (e.g., `1.0.0`)
  - `prediction_method`: Generation category (`ml` or `heuristic`)
- Implemented `XGPrediction` immutable value object returned by `ModelRegistry` and `XGService`.
- Automated database migration via `app/utils/db_migrator.py` ensuring backward and forward schema compatibility.
- Database backfill utility (`scripts/backfill_xg.py`) populates full provenance without guessing historical rows where it cannot be reliably established.

---

## 3. Statistical Population Clarity

### Explicit Denominator Semantics
- Clarified the distinction between actual shooting percentage and expected conversion rate in `app/services/skater_stats_service.py`:
  - `shots_on_goal`: Count of goals and saves (NHL standard denominator for actual shooting percentage).
  - `unblocked_attempts`: Count of goals, saves, and missed shots (Fenwick population and denominator for expected conversion).
  - `actual_shooting_pct`: Calculated as `goals / shots_on_goal * 100`.
  - `expected_goal_rate_per_unblocked_attempt`: Calculated as `player_xg / unblocked_attempts * 100`.
- Provided backward-compatible aliases (`shooting_pct` and `expected_shooting_pct`) to maintain seamless operation across existing templates and consumers.

---

## 4. Feature Engineering & Spatial Geometry Hardening

### Raw Physical Distance Across Possession Changes
- Refactored `distance_from_prev_event` to use raw rink Euclidean coordinates ($\sqrt{\Delta x^2 + \Delta y^2}$), ensuring physical travel distance is correctly calculated even when preceding events belong to the opposing team.
- Angle changes (`angle_change`) are normalized from the perspective of the current shooting team's attacking net.

### Controlled Neutral Imputation & Missingness Flags
- Introduced `coordinates_missing` binary indicator feature.
- Explicitly standardized missing values (`standardize_shot_type` and `standardize_strength_state` map `None` or empty inputs to `'UNKNOWN'`).
- Missing coordinates use controlled neutral imputation (`distance = 45.0`, `angle = 0.0`, `coordinates_missing = 1`) rather than arbitrary zeros.

---

## 5. Dependency & Pipeline Robustness

### Dependency Version Pinning & Runtime Verification
- Pinned bounded version ranges in `requirements.txt`:
  - `scikit-learn>=1.4.0,<2.0.0`
  - `numpy>=1.26.0,<3.0.0`
  - `pandas>=2.1.0,<4.0.0`
  - `joblib>=1.3.0,<2.0.0`
- Added runtime scikit-learn major version check on model artifact deserialization in `ModelRegistry`.
- Generalized CI workflow triggers in `.github/workflows/tests.yml` to test on `[ main, master, 'v*' ]`.

### Rich Serialization Metadata
- Extended `models/xg/metadata.json` with comprehensive audit trail:
  - Game counts, shot counts, and goal rates across train, validation, and test partitions.
  - Candidate validation comparison metrics.
  - Retraining strategy specification (`option_b_train_plus_validation_refit`).
  - Feature lists and orderings.
  - Environment package versions (`scikit-learn`, `numpy`, `pandas`).
  - Test set data leakage audit stamp.

---

## 6. Documentation & Verification

- Updated `docs/models/xg_v1.md` model card with the validated test set metrics, validation selection rationale, and Option B refit documentation.
- Cleaned up terminology in `README.md` (fixing `git checkout v1.1` to `v1.2` and removing lingering prototype references).
- Expanded regression and predictive unit test suite with 100% pass rate.
