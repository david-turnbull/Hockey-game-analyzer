# Stage 0 — Baseline, Measurement & Analytical Contracts

## Executive Summary
This document establishes the empirical baseline measurement, query-plan audit, bottleneck diagnosis, and analytical test contracts for **PuckLens v1.5** prior to introducing performance optimizations.

---

## 1. Current Architecture Audit

Season statistics in PuckLens v1.4 are generated on-the-fly via two primary services:
1. `PlayerSeasonService`: Aggregates skater counting statistics (GP, G, A, P, SOG, unblocked attempts, individual xG, TOI) and 5v5 on-ice metrics (CF, CA, CF%, FF, FA, FF%, on-ice xGF, on-ice xGA, on-ice xG%).
2. `TeamSeasonService`: Aggregates team-level records (W/L/OTL), goals for/against, Corsi, Fenwick, and expected goals across situations (`all`, `5v5`, `pp`, `sh`).

### Core Bottleneck Identified: Single-Player Pathology
`PlayerSeasonService.get_skater_season_stats(player_id, season)` executes the following workflow:
```
Request Single Player Season Stats
  ↓
Calls get_season_skaters_summary(season, include_on_ice_5v5=True)
  ↓
Queries ALL Games in Season (800+ games)
  ↓
Queries ALL GamePlayer rows in Season (~20,000+ rows)
  ↓
Queries ALL Goals, Assists, Shots, and Shifts for ALL players in the NHL
  ↓
Computes 5v5 shift boundary intervals in Python memory across all 800+ games (~200,000+ shifts)
  ↓
Searches returned list of 780+ skaters to extract the 1 requested player
```

---

## 2. Empirical Performance Benchmarks (Season 20212022 Data)

Benchmarked on local production-sized SQLite database (`hockey.db`, ~1.47 GB).

| Operation | Wall-Clock Time | SQL Query Count | Peak Memory | Output Info |
| :--- | :--- | :--- | :--- | :--- |
| **1. Single Player Season Stats** (`get_skater_season_stats`) | **53.89 s** | 12 | **464.09 MB** | 1 player found |
| **2. Full Season Skaters Summary** (`include_on_ice_5v5=True`) | **46.79 s** | 12 | **463.54 MB** | 782 skaters |
| **3. Full Season Skaters Summary** (`include_on_ice_5v5=False`) | **16.74 s** | 8 | **7.83 MB** | 782 skaters |
| **4. Team Season Stats** (`get_team_season_stats`) | **0.14 s** (139.95 ms) | 6 | **0.52 MB** | 1 team found |
| **5. Skater Leaderboards** (`get_skater_leaderboards limit=50`) | **47.10 s** | 12 | **463.72 MB** | 50 skaters |

### Key Bottleneck Findings:
- **Single-Player Latency:** Requesting stats for one player takes **53.89 seconds** and **464 MB of RAM**, identical to calculating the entire league's season stats.
- **On-Ice 5v5 Shift Interval Cost:** Computing on-ice 5v5 shift boundary intervals in Python adds **~30 seconds** of pure CPU/RAM overhead (46.79s vs 16.74s) and increases RAM usage from **7.83 MB to 463.54 MB**.
- **Leaderboard Unbounded Query:** `get_skater_leaderboards(limit=50)` computes full-season 5v5 stats for all 782 skaters in Python memory before slicing the top 50.

---

## 3. SQL Query-Plan Audit (`EXPLAIN QUERY PLAN`)

Analysis of representative SQL queries against `hockey.db`:

### A. Game Season Query
```sql
EXPLAIN QUERY PLAN 
SELECT game_id, game_date FROM game 
WHERE season = '20232024' 
ORDER BY game_date ASC, game_id ASC;
```
* **Query Plan:**
  - `SEARCH game USING INDEX idx_game_season_type (season=?)`
  - `USE TEMP B-TREE FOR ORDER BY`
* **Finding:** Uses index `idx_game_season_type`, but requires temp B-Tree sort for composite ordering (`game_date`, `game_id`).

### B. GamePlayer Season Join
```sql
EXPLAIN QUERY PLAN 
SELECT gp.player_id, gp.game_id, gp.team_id 
FROM game_player gp 
JOIN player p ON gp.player_id = p.player_id 
JOIN team t ON gp.team_id = t.team_id 
JOIN game g ON gp.game_id = g.game_id 
WHERE g.season = '20232024' AND p.position != 'G';
```
* **Query Plan:**
  - `SEARCH game USING COVERING INDEX idx_game_season_type (season=?)`
  - `SEARCH game_player USING INDEX sqlite_autoindex_game_player_1 (game_id=?)`
  - `SEARCH player USING INTEGER PRIMARY KEY (rowid=?)`
  - `SEARCH team USING INTEGER PRIMARY KEY (rowid=?)`
* **Finding:** Clean index coverage, but returns ~20,000+ rows into Python memory for full season.

### C. Shifts Bulk Query
```sql
EXPLAIN QUERY PLAN 
SELECT player_id, duration FROM shift 
WHERE game_id IN (SELECT game_id FROM game WHERE season = '20232024') 
  AND is_anomaly = 0 AND duration > 0;
```
* **Query Plan:**
  - `SEARCH shift USING INDEX ix_shift_game_id (game_id=?)`
  - `LIST SUBQUERY 1` $\rightarrow$ `SEARCH game USING COVERING INDEX idx_game_season_type (season=?)`
  - `CREATE BLOOM FILTER`
* **Finding:** Loads ~200,000+ raw shift rows into Python memory, causing the 464 MB peak memory allocation.

---

## 4. Analytical Contracts & Invariants

All future optimization stages (starting with Stage 1 `player_game_analytics`) must strictly preserve the following contracts verified in `tests/test_stage0_baseline.py`:

1. **Points Contract:** $\text{Points} = \text{Goals} + \text{Assists}$
2. **Shooting Percentage Contract:** $\text{Sh}\% = \text{round}\left(\frac{\text{Goals}}{\text{Shots}} \times 100, 2\right)$ when $\text{Shots} > 0$, else `0.0`.
3. **Goals Above Expected Contract:** $\text{GAE} = \text{round}(\text{Goals} - \text{xG}, 2)$.
4. **Additive Primitives Contract:** Persist additive components ($CF, CA, FF, FA, TOI, xGF, xGA$) per game.
5. **Ratio Aggregation Rule:** Season ratio statistics must be calculated post-aggregation:
   $$\text{CF}\% = \frac{\sum \text{CF}}{\sum \text{CF} + \sum \text{CA}} \times 100$$
   **NEVER** average individual game percentages.

---

## 5. Proposed Performance Targets for Stage 1 & Stage 2

| Operation | Stage 0 Baseline | Stage 2 Target | Target Improvement |
| :--- | :--- | :--- | :--- |
| **Single Player Season Stats** | 53.89 s | **< 50 ms** | **> 1,000x faster** |
| **Full Season Skaters Summary** | 46.79 s | **< 200 ms** | **> 200x faster** |
| **Skater Leaderboards (Top 50)** | 47.10 s | **< 50 ms** | **> 900x faster** |
| **Peak Memory Allocation** | 464 MB | **< 15 MB** | **> 95% reduction** |

---

## 6. Stage 0 Exit Criteria Verification

- [x] Baseline benchmarks exist (`scripts/stage0_benchmark.py` executed with empirical results recorded).
- [x] Analytical reference tests exist (`tests/test_stage0_baseline.py` created and passing).
- [x] Full test suite passes (202 test items passed cleanly).
- [x] Performance bottlenecks supported by empirical evidence (53.89s single-player latency & 464 MB memory documented).
