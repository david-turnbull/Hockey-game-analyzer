# Rolling Trends & Form Analysis

## Overview
Single-game analytical samples exhibit significant noise in professional ice hockey. In PuckLens v1.3, `RollingService` computes rolling windows of underlying performance metrics to evaluate process quality and momentum over time.

## Mathematical Invariant: Zero Future Leakage
All rolling trends are strictly chronological:
- Games are sorted by `(game_date ASC, game_id ASC)`.
- At game index $i$, the rolling window incorporates only games in the interval $[ \max(0, i - W + 1), i ]$.
- Under no circumstances does a rolling metric access, aggregate, or peek at games occurring after game $i$.

## Multi-Windowing
The platform provides three canonical team rolling windows:
1. **5-Game Window:** Short-term tactical form, line chemistry shifts, and immediate hot/cold streaks.
2. **10-Game Window:** Intermediate process evaluation, dampening single-game outlier effects.
3. **20-Game Window:** Long-term process stabilization, revealing sustained team true-talent level.

## Tracked Metrics
- **Team Trends:**
  - $xGF\%$ (Rolling Expected Goal Share)
  - $CF\%$ (Rolling Corsi Share)
  - $FF\%$ (Rolling Fenwick Share)
  - $xGF/60$ and $xGA/60$
  - $xG\ \text{Differential}$ ($xGF - xGA$)
  - Finishing Variance ($GF - xGF$) and Goaltending Variance ($xGA - GA$)
- **Player Trends:**
  - Rolling $xG$ (Cumulative expected goal generation)
  - Rolling $G - xG$ (Finishing variance)
  - Rolling $xG/60$ (Rate production)
  - Rolling Shot Volume (Unblocked attempt rate)
- **Goalie Trends:**
  - Rolling $GSAx$ (Goals Saved Above Expected)
  - Rolling $GSAx/\text{game}$
  - Rolling Actual Save % vs Expected Save %
