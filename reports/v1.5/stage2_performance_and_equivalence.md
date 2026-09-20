# Stage 2 Qualification Report: Performance & Equivalence

> **Generated:** `2026-09-20T21:50:26.765723+00:00`  
> **Target Season:** `20212022`  
> **Qualification Status:** `QUALIFIED (STAGE 2 COMPLETE)`

## 1. Derived Coverage Audit
* **Schedule Games (`Game` table):** `1312`
* **Ingested Games (`GamePlayer` table):** `271`
* **Derived-Complete Games:** `271`
* **Incomplete / Missing Games:** `0`
* **Derived Coverage:** `100.0% of ingested games`
* **Safety Audit Status:** `PASSED (Per-game row counts verified)`

## 2. Performance Qualification Metrics vs. Stage 0 Baseline

| Metric / Endpoint | Contract Threshold | Stage 0 Frozen Baseline | Current Legacy Re-run | Stage 2 Derived | Queries | Peak Memory | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Single-Player Stats** | `< 50 ms` | `48710.00 ms` (`48.71 s`) | `not re-run` | **`33.27 ms`** | `7` | `0.12 MB` | `PASSED` |
| **Full-Season Summary** | `< 200 ms` | `45590.00 ms` (`45.59 s`) | `25392.75 ms` | **`110.20 ms`** | `8` | `3.92 MB` | `PASSED` |
| **Top-50 Leaderboard** | `< 50 ms` | `47210.00 ms` (`47.21 s`) | `not re-run` | **`47.55 ms`** | `8` | `0.24 MB` | `PASSED` |

* **Full Summary Speedup vs Stage 0 Frozen Baseline:** **`413.7x Faster`**
* **Peak Memory Allocation:** **`3.92 MB`** (Threshold `< 15.0 MB`, Stage 0 Baseline `~464 MB`).

## 3. Query Plan & Indexing Audit (SQLite EXPLAIN QUERY PLAN)

### Single-Player Query Plan
```
[5, 0, 61, 'SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=? AND player_id=?)']
```
* **Execution Details:** `SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=? AND player_id=?)`

### Leaderboard Top-50 Aggregation Query Plan
```
[9, 0, 61, 'SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=?)']
[53, 0, 0, 'USE TEMP B-TREE FOR ORDER BY']
```
* **Execution Details:** `SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=?)`

### Top-N Stint Lookup Query Plan
```
[4, 0, 61, 'SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=? AND player_id=?)']
[35, 0, 0, 'USE TEMP B-TREE FOR ORDER BY']
```
* **Execution Details:** `SEARCH player_game_analytics USING INDEX idx_pga_season_player (season=? AND player_id=?)`

## 4. Production Analytical Equivalence Audit
* **Evaluated Skaters:** `782`
* **Mismatches Detected:** `0`
* **Equivalence Determination:** `EQUIVALENCE CONFIRMED WITHIN DOCUMENTED TOLERANCE`
* **Documented Tolerances:**
  * Counting Stats (GP, G, A, P, shots, unblocked attempts, TOI, CF, CA, FF, FA, 5v5 TOI): `0` (Exact match)
  * Individual xG & Rate Metrics (`xg`, `goals_above_expected`, `goals_per_60`, `xg_per_60`, `shooting_pct`, `expected_conversion_pct`, `shooting_vs_expected_diff`): `0.05`
  * 5v5 On-Ice xG Values (`on_ice_xgf`, `on_ice_xga`): `0.05`
  * 5v5 On-Ice Percentages (`cf_pct`, `ff_pct`, `on_ice_xg_pct`): `0.30%`
