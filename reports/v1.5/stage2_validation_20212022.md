# Stage 2 Validation Report: Season 20212022

> **Generated:** `2026-09-20T20:45:53.817970+00:00`  
> **Status:** `PASSED`

## 1. Audit & Backfill Completeness
* **Total Season Games:** `271`
* **Complete Games:** `271`
* **Incomplete Games:** `0`
* **Missing Games:** `0`
* **Audit Result:** `100% COMPLETE`

## 2. Performance Benchmark
| Engine | Execution Time | Skaters Loaded | Speedup |
| :--- | :--- | :--- | :--- |
| **Legacy `_get_season_skaters_summary_legacy`** | `24.339 s` | `782` | Baseline (1.0x) |
| **Derived `_get_season_skaters_summary_derived`** | `0.0834 s` | `782` | **291.7x Faster** |

## 3. Player Equivalence Summary
* **Total Players Evaluated:** `782`
* **Mismatches Found:** `0`
* **Equivalence Result:** `PERFECT 100% MATCH`

### Verified Metrics
- Games Played (`gp`), Goals (`goals`), Assists (`assists`), Points (`points`)
- Shots on Goal (`shots`), Unblocked Attempts (`unblocked_attempts`)
- Individual Expected Goals (`xg`)
- Total Time on Ice (`toi_seconds`), 5v5 Time on Ice (`toi_5v5_seconds`)
- 5v5 Corsi For / Against (`cf`, `ca`), 5v5 Fenwick For / Against (`ff`, `fa`)
- 5v5 Expected Goals For / Against (`on_ice_xgf`, `on_ice_xga`)
