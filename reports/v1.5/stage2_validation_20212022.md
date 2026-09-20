# Stage 2 Validation Report: Season 20212022

> **Generated:** `2026-09-20T20:43:54.301617+00:00`  
> **Status:** `FAILED`

## 1. Audit & Backfill Completeness
* **Total Season Games:** `1312`
* **Complete Games:** `271`
* **Incomplete Games:** `0`
* **Missing Games:** `1041`
* **Audit Result:** `INCOMPLETE`

## 2. Performance Benchmark
| Engine | Execution Time | Skaters Loaded | Speedup |
| :--- | :--- | :--- | :--- |
| **Legacy `_get_season_skaters_summary_legacy`** | `26.787 s` | `782` | Baseline (1.0x) |
| **Derived `_get_season_skaters_summary_derived`** | `0.1059 s` | `782` | **253.0x Faster** |

## 3. Player Equivalence Summary
* **Total Players Evaluated:** `782`
* **Mismatches Found:** `3`
* **Equivalence Result:** `MISMATCHES DETECTED`

### Verified Metrics
- Games Played (`gp`), Goals (`goals`), Assists (`assists`), Points (`points`)
- Shots on Goal (`shots`), Unblocked Attempts (`unblocked_attempts`)
- Individual Expected Goals (`xg`)
- Total Time on Ice (`toi_seconds`), 5v5 Time on Ice (`toi_5v5_seconds`)
- 5v5 Corsi For / Against (`cf`, `ca`), 5v5 Fenwick For / Against (`ff`, `fa`)
- 5v5 Expected Goals For / Against (`on_ice_xgf`, `on_ice_xga`)
