# PuckLens - Version 1.2.0 Release Notes

**Release Date:** September 2026  
**Theme:** Predictive Analytics Upgrade & Machine Learning Expected Goals Pipeline

PuckLens version 1.2.0 marks a milestone transition from descriptive boxscore analysis into an advanced predictive NHL hockey analytics platform. This release introduces a fully trained, calibrated, and reproducible statistical Expected Goals (xG) engine, versioned model registry, database schema persistence, goaltender evaluation metrics, forward trio / defensive pairing shot quality share, cumulative game timelines, and probability-scaled interactive shot maps.

---

## 1. Machine Learning Expected Goals (xG) Engine

### Statistical Model & Calibration
- Replaced the initial heuristic prototype with an independently trained statistical **Logistic Regression model** (`pucklens-xg-v1` / `pucklens-xg-logistic`, version `1.0.0`) with one-hot categorical encoding and standardized numerical scaling.
- Trained on **14,262 unblocked regular-season NHL shot attempts** across 162 cached game feeds from the 2023–2024 season.
- Structured with strict **chronological game-level splitting** (70% train / 15% validation / 15% test) to prevent temporal data leakage.
- Validated on a 2,226-shot held-out test set:
  - **Log Loss:** 0.2130
  - **Brier Score:** 0.0564
  - **ROC AUC:** 0.7498
  - **Calibration:** 148.74 expected goals predicted vs 147.0 actual goals (+1.1% delta).
- Documented with a transparent, production-grade **Model Card** at `docs/models/xg_v1.md`.

### Feature Engineering & Sequence Dynamics
- **Coordinate Symmetry:** Rink $(x, y)$ coordinates are symmetrically mapped to the attacking net at $(89, 0)$ so geometry is invariant to attack direction and period.
- **Euclidean Geometry:** Shot distance in feet and absolute angle in degrees.
- **Sequential Play Dynamics:** Extracted temporal and spatial deltas relative to preceding play-by-play events:
  - Rebound attempts ($\le 3.0$ seconds following save, block, or miss).
  - Transition rushes ($\Delta d \ge 40$ ft in $\Delta t \le 4.0$ seconds).
  - Turnovers ($\le 4.0$ seconds following takeaway or giveaway).
  - Post-faceoff shots ($\le 4.0$ seconds following faceoffs).
  - Lateral pre-shot angle changes ($\ge 25^\circ$ within $\le 3.0$ seconds).
- **Game State & Manpower:** Even strength, power play, shorthanded differentials, score deficit/lead, period timing, and empty-net indicators.

### Model Registry & Database Schema Persistence
- Implemented `app/analytics/model_registry.py` for model artifact serialization, version tracking, and graceful fallback handling.
- Extended the relational schema with `Shot.model_version` and updated `app/utils/db_migrator.py` for automated schema migration.
- Provided CLI tools `scripts/train_xg.py` for model retraining/evaluation and `scripts/backfill_xg.py` for database-wide shot rescoring.

---

## 2. Advanced Player, Goalie, and Unit Analytics

### Goaltender Analytics (xGA & GSAx)
- Integrated **Expected Goals Against ($xGA$)**, **Goals Saved Above Expected ($GSAx = xGA - GA$)**, and rate metrics (**$GSAx/60$**).
- **Empty-Net Safety Rule:** Empty-net attempts (`empty_net == True`) and shootout attempts are strictly excluded from goalie $xGA$ to prevent penalizing goaltenders for goals conceded after being pulled.

### Skater Finishing Analytics
- Integrated individual **Goals Above Expected ($G - xG$)**, **Expected Goals per 60 ($xG/60$)**, and **Expected Shooting Percentage ($xSh\% = xG / Shots \times 100$)** on skater game pages.

### 5v5 Forward Combinations & Defensive Pairings
- Added on-ice Expected Goals For ($xGF$), Expected Goals Against ($xGA$), Expected Goal Share ($xG\%$), and rate metrics ($xGF/60$, $xGA/60$) to observed forward trios and defensive pairings.

---

## 3. Interactive Visualizations & Dashboards

### Cumulative Game xG Timeline
- Interactive Plotly step-function chart plotting home and away cumulative expected goals progression over 60+ game minutes.
- Supports interactive situation filtering (`All`, `5v5`, `Power Play`) with period boundary markers and score annotations.

### Probability-Scaled Interactive Shot Maps
- Shot attempt markers on rink visualizations dynamically scale in radius and color intensity based on expected goal probability (ice blue for perimeter attempts up to deep crimson for high-danger rebounds).
- Enhanced hover tooltips displaying model version, xG probability, shot distance, and sequence flags (rebound, rush, turnover).

---

## 4. Diagnostics & Data Quality

### Shot Model Data Quality Checks
- Added `shot_model_data_quality` integrity audits to `app/services/data_integrity_service.py`, `scripts/database_diagnostics.py`, and the `/diagnostics` dashboard.
- Monitors out-of-bounds spatial coordinates, missing shooter/goalie attribution, normalization integrity, and sample distribution statistics.

---

## 5. Testing & Verification

- Added comprehensive test suites:
  - `tests/test_predictive_analytics.py`: Tests spatial normalization, Euclidean geometry, rebound/rush sequence detection, division-by-zero resilience, goalie empty-net exclusions, and diagnostic data quality.
  - `tests/test_xg_model.py`: Tests model registry fallback, serialization, and deterministic probability prediction.
- All **76 automated tests pass** with zero warnings on Python 3.12.
