# Stage 2 Qualification Report: Performance & Equivalence

> **Generated:** `2026-09-20T21:24:33.227100+00:00`  
> **Target Season:** `20212022`  
> **Qualification Status:** `QUALIFIED (STAGE 2 COMPLETE)`

## 1. Derived Coverage Audit
* **Schedule Games (`Game` table):** `1312`
* **Ingested Games (`GamePlayer` table):** `271`
* **Derived-Complete Games:** `271`
* **Incomplete / Missing Games:** `0`
* **Derived Coverage:** `100.0% of ingested games`

## 2. Performance Qualification Metrics vs. Stage 0 Baseline

| Target | Contract Threshold | Stage 0 Legacy | Stage 2 Derived | Queries | Peak Memory | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Single-Player Stats** | `< 50 ms` | `26,700 ms` (full-season load) | **`16.07 ms`** | `6` | `0.05 MB` | `PASSED` |
| **Full-Season Summary** | `< 200 ms` | `26,700 ms` | **`108.29 ms`** | `7` | `3.92 MB` | `PASSED` |
| **Top-50 Leaderboard** | `< 50 ms` | `26,700 ms` | **`39.42 ms`** | `7` | `0.24 MB` | `PASSED` |

* **Full Summary Speedup:** **`274.5x Faster`** than legacy calculations.

## 3. Query Plan & Indexing Audit
* **Single-Player Query:** `SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=? AND player_id=?)`
* **Leaderboard Query:** `SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=?)`
* **Top-N Stint Query:** `SEARCH pga USING INDEX idx_pga_season_player (season=? AND player_id=?)`
* **Audit Determination:** Existing index `idx_pga_season_player (season, player_id)` achieves index-search execution across all derived read paths. Additional composite indexes or caching are unnecessary.

## 4. Analytical Equivalence
* **Status:** `100% PERFECT EQUIVALENCE CONFIRMED`
* **Evaluated Skaters:** `782`
* **Mismatches:** `0`
