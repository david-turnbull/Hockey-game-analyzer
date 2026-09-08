# Team Season Analytics Architecture & Methodology

## Overview
The PuckLens Team Season Analytics engine aggregates full regular-season schedules into actionable possession, expected goal, and finishing variance metrics. 

To achieve optimal performance and scalability across multi-season datasets, PuckLens implements a **hybrid architecture**:
1. **Bulk Grouped SQL Aggregations:** Used for high-volume counting, shot metrics, and event aggregations, eliminating N+1 database round-trips.
2. **Bounded In-Memory Temporal Processing (`OnIceService`):** Used for micro-level second-by-second shift timeline reconstructions to compute precise manpower situations and individual skater 5v5 on-ice time on ice.

## Situational Filtering & Manpower Rules
Hockey operates in distinct game states that dramatically affect shot rates and expected quality. PuckLens supports four canonical situation filters:
- **`all` (All Situations):** Encompasses even-strength, power play, shorthanded, empty net, and 3v3 overtime play.
- **`5v5` (Even Strength):** Restricted strictly to true 5-on-5 play, requiring exactly 5 skaters and 1 goalie on the ice for both teams.
- **`pp` (Power Play):** Offensive man-advantage strength states (e.g. 5v4, 5v3, 4v3). **Rule:** Requires both goalies on the ice (`h_g >= 1 and a_g >= 1`) with skater numerical advantage. Goalie-pull / extra-attacker situations (e.g. 6v5, 5v6) are strictly excluded.
- **`sh` (Shorthanded / PK):** Defensive penalty-killing strength states (e.g. 4v5, 3v5, 3v4). **Rule:** Requires both goalies on the ice (`h_g >= 1 and a_g >= 1`) with skater numerical disadvantage. Goalie-pull / empty net situations are strictly excluded.

> **Missing Shift Data Invariant:** If a game lacks shift records, situation-specific denominators cannot be determined with statistical confidence; `toi_seconds` defaults to `None` for affected filters.

## Traded Player Representation
PuckLens implements a unified stint-based representation for players active on multiple teams during a season:
- **League-Wide Scope (`team_id=None`):** Statistics and TOI are aggregated across all stints, with chronological team abbreviations (e.g. `CGY/VAN/CGY`).
- **Team-Filtered Scope (`team_id=<team>`):** Only production, shots, TOI, and 5v5 on-ice possession metrics recorded while actively representing that team are returned.

## Core Metric Definitions & Formulas

### 1. Shot Attempt Shares (Corsi & Fenwick)
- **Corsi ($CF$, $CA$, $CF\%$):**
  Includes all shot attempts (Goals, Saved Shots, Missed Shots, Blocked Shots).
  $$CF\% = \frac{CF}{CF + CA} \times 100$$
- **Fenwick ($FF$, $FA$, $FF\%$):**
  Includes only unblocked shot attempts (Goals, Saved Shots, Missed Shots). Blocked shots are excluded.
  $$FF\% = \frac{FF}{FF + FA} \times 100$$

### 2. Expected Goals Shares & Rates
- **Expected Goals For ($xGF$) & Against ($xGA$):**
  Sum of model predicted $xG$ for all unblocked attempts taken ($xGF$) and allowed ($xGA$).
- **Expected Goal Share ($xG\%$):**
  $$xG\% = \frac{xGF}{xGF + xGA} \times 100$$
- **Per-60 Standardized Rates:**
  $$xGF/60 = \frac{xGF}{\text{TOI hours}}, \quad xGA/60 = \frac{xGA}{\text{TOI hours}}$$
  $$xG\ \text{Differential} = xGF - xGA$$

### 3. Variance & Regression Indicators
- **Finishing Variance ($GF - xGF$):**
  Measures whether a team is out-scoring or under-scoring its underlying shot quality creation. High positive values indicate either elite finishing talent or regression-susceptible shooting luck.
- **Goaltending Variance ($xGA - GA$):**
  Measures goaltender performance relative to expected danger. Positive values indicate goaltenders saving more goals than expected based on shot quality faced.
