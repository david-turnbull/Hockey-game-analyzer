# Stage 2 Qualification Report: Performance & Equivalence

> **Generated:** `2026-09-20T21:40:01.030666+00:00`  
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
| **Single-Player Stats** | `< 50 ms` | `48710.00 ms` (`48.71 s`) | `25460.79 ms` | **`20.83 ms`** | `7` | `0.12 MB` | `PASSED` |
| **Full-Season Summary** | `< 200 ms` | `45590.00 ms` (`45.59 s`) | `25460.79 ms` | **`90.13 ms`** | `8` | `3.92 MB` | `PASSED` |
| **Top-50 Leaderboard** | `< 50 ms` | `47210.00 ms` (`47.21 s`) | `25460.79 ms` | **`33.64 ms`** | `8` | `0.24 MB` | `PASSED` |

* **Full Summary Speedup vs Stage 0 Frozen Baseline:** **`505.8x Faster`**
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
* **Equivalence Determination:** `100% PERFECT EQUIVALENCE CONFIRMED`
