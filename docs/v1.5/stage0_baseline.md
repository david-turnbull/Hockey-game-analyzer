# Stage 0 — Baseline, Measurement & Analytical Contracts

## Executive Summary
This document establishes the empirical baseline measurement, dataset scale diagnostics, query-plan audit, bottleneck diagnosis, and frozen numerical reference test contracts for **PuckLens v1.5** prior to introducing performance optimizations.

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
Queries ALL Games in Season (1,312 games for 20212022)
  ↓
Queries ALL GamePlayer rows in Season (10,839 rows)
  ↓
Queries ALL Goals, Assists, Shots, and Shifts for ALL players in the NHL (210,379 shifts, 148,574 events)
  ↓
Computes 5v5 shift boundary intervals in Python memory across all 1,312 games
  ↓
Searches returned list of 782 skaters to extract the 1 requested player
```

---

## 2. Empirical Performance & Dataset Scale (Season 20212022 Data)

Benchmarked on local production-sized SQLite database (`hockey.db`, ~1.47 GB).

### Dataset Scale Diagnostics (Season 20212022)
* **Games:** 1,312
* **GamePlayer rows:** 10,839
* **Shifts (total):** 210,379
* **Shifts (valid, >0s):** 208,724
* **Events (total):** 148,574
* **Events (5v5):** 132,239
* **Shots:** 96,015

### Execution Benchmarks

| Operation | Wall-Clock Time | SQL Query Count | Peak Memory | Output Info |
| :--- | :--- | :--- | :--- | :--- |
| **1. Single Player Season Stats** (`get_skater_season_stats`) | **48.71 s** | 12 | **464.09 MB** | 1 player found |
| **2. Full Season Skaters Summary** (`include_on_ice_5v5=True`) | **45.59 s** | 12 | **463.54 MB** | 782 skaters |
| **3. Full Season Skaters Summary** (`include_on_ice_5v5=False`) | **16.74 s** | 8 | **7.98 MB** | 782 skaters |
| **4. Team Season Stats** (`get_team_season_stats`) | **0.09 s** (91.93 ms) | 6 | **0.53 MB** | 1 team found |
| **5. Skater Leaderboards** (`get_skater_leaderboards limit=50`) | **47.21 s** | 12 | **463.77 MB** | 50 skaters |

### Reproducible Benchmark Utility Usage
Run the CLI benchmark script against any season with optional JSON export:
```bash
python scripts/stage0_benchmark.py --season 20212022 --output reports/v1.5/stage0_benchmark.json
```

---

## 3. SQL Query-Plan Audit (`EXPLAIN QUERY PLAN`)

Analysis of representative SQL queries against `hockey.db` for season `20212022`:

### A. Game Season Query
```sql
EXPLAIN QUERY PLAN 
SELECT game_id, game_date FROM game 
WHERE season = '20212022' 
ORDER BY game_date ASC, game_id ASC;
```
* **Query Plan:**
  - `SEARCH game USING INDEX idx_game_season_type (season=?)`
  - `USE TEMP B-TREE FOR ORDER BY`

### B. GamePlayer Season Join
```sql
EXPLAIN QUERY PLAN 
SELECT gp.player_id, gp.game_id, gp.team_id 
FROM game_player gp 
JOIN player p ON gp.player_id = p.player_id 
JOIN team t ON gp.team_id = t.team_id 
JOIN game g ON gp.game_id = g.game_id 
WHERE g.season = '20212022' AND p.position != 'G';
```
* **Query Plan:**
  - `SEARCH g USING COVERING INDEX idx_game_season_type (season=?)`
  - `SEARCH gp USING INDEX sqlite_autoindex_game_player_1 (game_id=?)`
  - `SEARCH p USING INTEGER PRIMARY KEY (rowid=?)`
  - `SEARCH t USING INTEGER PRIMARY KEY (rowid=?)`

### C. Shifts Bulk Query
```sql
EXPLAIN QUERY PLAN 
SELECT player_id, duration FROM shift 
WHERE game_id IN (SELECT game_id FROM game WHERE season = '20212022') 
  AND is_anomaly = 0 AND duration > 0;
```
* **Query Plan:**
  - `SEARCH shift USING INDEX ix_shift_game_id (game_id=?)`
  - `LIST SUBQUERY 1` $\rightarrow$ `SEARCH game USING COVERING INDEX idx_game_season_type (season=?)`
  - `CREATE BLOOM FILTER`

### D. 5v5 Events & Shot Query
```sql
EXPLAIN QUERY PLAN 
SELECT e.game_id, e.event_type, sh.xg 
FROM event e 
JOIN game g ON e.game_id = g.game_id 
LEFT OUTER JOIN shot sh ON e.event_id = sh.shot_id 
WHERE g.season = '20212022' AND e.team_strength_state = '5v5';
```
* **Query Plan:**
  - `SEARCH g USING COVERING INDEX idx_game_season_type (season=?)`
  - `SEARCH e USING INDEX ix_event_game_id (game_id=?)`
  - `SEARCH sh USING INDEX sqlite_autoindex_shot_1 (shot_id=?) LEFT-JOIN`

---

## 4. Frozen Analytical Reference Outputs & Test Contracts

Stage 0 freezes the exact analytical truth in `tests/test_stage0_baseline.py` using hard numerical assertions across a deterministic 12-player true-5v5 lineup fixture (Calgary Flames vs Edmonton Oilers).

### Frozen Reference Values for Calgary Player 101 (Mikael Backlund)

#### Individual & Counting Statistics
- **GP:** `1`
- **Goals:** `1`
- **Assists:** `0`
- **Points:** `1`
- **Shots on Goal:** `1`
- **Unblocked Attempts:** `1`
- **Individual xG:** `0.35`
- **Goals Minus xG ($G - \text{xG}$):** `0.65`
- **Total TOI:** `600` seconds (`10:00`)
- **Shooting %:** `100.0%`
- **Expected Conversion %:** `35.0%`
- **Goals per 60:** `6.0`
- **xG per 60:** `2.1`

#### 5v5 On-Ice Statistics
- **Corsi For (CF):** `3` (Goal, Missed, Blocked)
- **Corsi Against (CA):** `2` (Saved, Missed)
- **Corsi For % (CF%):** `60.0%` ($\frac{3}{5} \times 100$)
- **Fenwick For (FF):** `2` (Goal, Missed)
- **Fenwick Against (FA):** `2` (Saved, Missed)
- **Fenwick For % (FF%):** `50.0%` ($\frac{2}{4} \times 100$)
- **On-Ice xGF:** `0.55` ($0.35 + 0.20$)
- **On-Ice xGA:** `0.30` ($0.21 + 0.09$)
- **On-Ice xG %:** `64.71%` ($\frac{0.55}{0.85} \times 100$)
- **5v5 TOI:** `600` seconds (`10:00`)

### Hard Ratio Aggregation Contract
Season percentage statistics MUST be calculated from summed additive primitives:
$$\text{CF}\% = \frac{\sum \text{CF}}{\sum \text{CF} + \sum \text{CA}} \times 100$$
Tested across asymmetric multi-game scenarios (Game 1: 90.0% CF, Game 2: 1.0% CF) to verify that season CF% yields **9.09%** (summed ratio) and **NEVER** 45.5% (average of game percentages).

---

## 5. Proposed Performance Targets for Stage 1 & Stage 2

| Operation | Stage 0 Baseline | Stage 2 Target | Target Improvement |
| :--- | :--- | :--- | :--- |
| **Single Player Season Stats** | 48.71 s | **< 50 ms** | **> 900x faster** |
| **Full Season Skaters Summary** | 45.59 s | **< 200 ms** | **> 200x faster** |
| **Skater Leaderboards (Top 50)** | 47.21 s | **< 50 ms** | **> 900x faster** |
| **Peak Memory Allocation** | 464 MB | **< 15 MB** | **> 95% reduction** |

---

## 6. Stage 0 Exit Criteria Verification

- [x] Deterministic true-5v5 fixture exists (`tests/test_stage0_baseline.py`).
- [x] Both teams contain full skater/goalie lineups (6 players per side, 12 total) for valid 5v5 reconstruction.
- [x] Hard numerical reference values tested (CF, CA, FF, FA, on-ice xGF, on-ice xGA, 5v5 TOI, counting stats, individual xG).
- [x] Single-player stats proven equivalent to full-season summary entry across all analytical fields.
- [x] Ratio-from-additive-primitives behavior explicitly tested (`test_stage0_ratio_aggregation_semantics`).
- [x] Benchmark CLI season selection implemented (`--season`).
- [x] `EXPLAIN QUERY PLAN` uses selected season dynamically.
- [x] Dataset row counts reported (208k shifts, 132k 5v5 events).
- [x] Machine-readable JSON output supported (`--output`).
- [x] Full test suite passes cleanly (**205 passed**).
- [x] Zero Stage 1 optimizations introduced.
