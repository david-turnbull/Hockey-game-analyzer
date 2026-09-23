# PuckLens v1.5.0 Release Notes

**Release Version:** `v1.5.0`  
**Release Date:** September 2026  
**Target Branch:** `v1.5`  
**Qualification Status:** RELEASE QUALIFIED (All 11 Release Gates Passed)

---

## Executive Summary

PuckLens v1.5.0 introduces major architectural enhancements to data processing, analytical query performance, UI presentation flexibility, experiment auditing, and out-of-time forecast intelligence research while preserving 100% frozen backward compatibility with all v1.4 production forecasting models and artifacts.

---

## Key Features & Highlights

### 1. Stage 1–2: SQL Derived Player-Game Analytics Data Layer
* **Derived Analytical Tables:** Built the `player_game_analytics` table providing pre-aggregated 5v5 and all-situation skater metrics.
* **Massive Performance Speedup:** Reduced full-season skater summary query latency from **45.59 seconds (baseline)** to **83.36 ms** (a **546.9x speedup**), comfortably exceeding the 200 ms SLA threshold.
* **Single-Player Query Efficiency:** Direct single-player season queries execute in **21.79 ms** (SLA < 50 ms) without triggering full-season aggregations.
* **Top-50 Leaderboard Performance:** Bounded leaderboard queries execute in **37.81 ms** (SLA < 50 ms).
* **Memory Optimization:** Peak memory allocation during analytical queries dropped from ~464 MB to **4.00 MB** (SLA < 15 MB).
* **Analytical Equivalence:** Verified 100% exact numerical match across all counting statistics (GP, G, A, P, SOG, TOI, 5v5 TOI, CF, CA, FF, FA) and adherence to documented tolerances for individual xG and 5v5 percentage metrics across 782 evaluated skaters in the 2021–22 season dataset.

### 2. Stage 3: Methodology Registry & Model Cards
* **Centralized Registry:** Introduced `MethodologyRegistry` providing structured, testable metadata definitions (`MetricDefinition` and `ModelCard`) for all PuckLens metrics and production models.
* **Provenance Tracking:** Captures formula, strength context, version, caveats, and mathematical origin for metrics, alongside scikit-learn version, training approach, and git commit SHA for models.
* **Fallback Hardening:** Displays `Unavailable` when registry keys or model metadata are absent rather than hardcoding static fallback names.

### 3. Stage 4: Multi-Tier Presentation Modes
* **Presentation Modes:** Supports **Beginner**, **Intermediate**, and **Professional** UI presentation modes.
* **Analytical Invariance:** Guarantees that raw underlying statistical values remain 100% identical across all three presentation modes.
* **Progressive Disclosure:** Beginner mode hides dense 5v5 raw tables while providing friendly explanatory labels ("defeated", "leads", "is tied"). Intermediate retains contextual guidance. Professional provides dense analytical depth and full provenance.
* **URL & Parameter Preservation:** The `build_mode_url()` template helper retains active filters, season context, and team parameters when switching presentation modes.

### 4. Stage 5: Point-in-Time Experiment Framework
* **Leakage-Safe Framework:** Created `PointInTimeAdapter` and `PointInTimeCutoff` ensuring feature extraction for game `T` strictly uses information available prior to `T`.
* **Explicit Timestamp Provenance:** Enforces `latest_source_game_start_time` tracking to prevent future data leakage.
* **Fail-Closed Auditing:** Raises `TemporalLeakageError` when temporal provenance cannot be established.

### 5. Stage 6: Out-of-Time Forecast Intelligence & Elo Research
* **Leakage-Safe Research Pipeline:** Executed comprehensive out-of-time Elo research across regular season datasets without modifying frozen v1.4 production models.
* **Clean Provenance:** Retains `research_execution_git_sha` (`b08a0168237ea4a26f93ae9de30626901a937e60`) while removing misleading parent-commit SHA metadata.
* **Production Isolation:** Confirmed that dynamic Elo features remain research-only unless explicitly promoted in a future release.

### 6. Stage 7: Release Qualification & Operational Hardening
* **Complete Database Isolation:** Executed data rebuilds and performance benchmarks against an isolated SQLite backup (`hockey_stage7_temp.db`).
* **Frozen Model SHA-256 Contracts:** Verified exact matches for `pucklens-win-v1.4.0.pkl` (`63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9`) and `score_candidate_params_v1.4.0.json` (`a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701`).
* **Security Hardening:** Enforced `ProductionConfig` fail-closed defaults (`ALLOW_PUBLIC_INGESTION=False`, `ALLOW_PREDICTION_GENERATION=False`, mandatory `SECRET_KEY`).
* **Resumable Orchestrator:** Implemented `scripts/run_stage7_release_qualification.py` supporting `--gate`, `--from-gate`, `--resume`, and `--output-dir`.

---

## Automated Test & CI Verification

* **Local Pytest Suite:** **265 PASSED, 0 FAILED, 24 WARNINGS**
* **GitHub Actions CI:** Green pass on exact candidate SHA (`b7c38cac8424bd311c0070bdfad67d64015cf96f`).

---

## Release Verification Checklist

- [x] All 7 implementation stages completed and audited.
- [x] Database isolation verified with atomic SQLite backup API.
- [x] Analytical data layer rebuilt and verified 100% equivalent to legacy baseline.
- [x] All performance SLAs passed (<50ms single-player, <200ms summary, <50ms top-50, <15MB memory).
- [x] Multi-tier presentation modes verified with value invariance.
- [x] Frozen model artifact hashes verified via SHA-256 contracts.
- [x] Operational security fail-closed defaults enforced.
- [x] Full pytest suite (265 tests) passing cleanly.

**PuckLens v1.5.0 is certified RELEASE QUALIFIED and ready for production deployment.**
