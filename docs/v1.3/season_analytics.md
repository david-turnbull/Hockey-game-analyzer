# Team Season Analytics Architecture & Methodology

## Overview
The PuckLens Team Season Analytics engine aggregates full regular-season schedules into actionable possession, expected goal, and finishing variance metrics. To handle large volumes of games and events efficiently, all calculations use grouped SQL aggregations, eliminating N+1 database queries.

## Situational Filtering
Hockey operates in distinct game states that dramatically affect shot rates and expected quality. PuckLens supports four canonical situation filters:
- **`all` (All Situations):** Encompasses even-strength, power play, short-handed, empty net, and 3v3 overtime play.
- **`5v5` (Even Strength):** Restricted strictly to 5v5 skater strength state, representing true baseline team quality.
- **`pp` (Power Play):** Offensive man-advantage strength states (5v4, 5v3, 4v3).
- **`sh` (Shorthanded):** Defensive penalty-killing strength states (4v5, 3v5, 3v4).

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
