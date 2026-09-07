# PuckLens - Version 1.1.0 Release Notes

PuckLens version 1.1.0 marks the transition of the NHL Hockey Analytics Platform from a single-game data prototype into a fully interactive game-exploration and lineup-analytics application. 

This release focuses on data accuracy, code modularity, spatial analytics exploration, and robust regression testing.

---

## 1. Key New Features

### Clickable Shared 5v5 Line & Defense Pair Detail Views
* Observed forward combinations (trios) and defensive pairings (duos) on the lineups page are now interactive links.
* Clicking any combination opens a dedicated unit detail page displaying:
  * Individual player cards mapping names, numbers, shooting handedness, and NHL headshots.
  * Shared on-ice statistics: Goals (GF/GA), Shots on Goal (SF/SA), Corsi (CF/CA/CF%), and Fenwick (FF/FA/FF%).
  * Chronological list of shared shift intervals showing start time, end time, and duration in the period.
  * On-ice events timeline showing all play-by-play events that occurred while the unit was active.
  * Interactive Plotly rink shot map plotting all attempts taken and faced by the unit.

### Side-by-Side Player Comparison Dashboard
* Compare any two skaters or goalies from the same game side-by-side using dropdown selectors.
* Compares Time on Ice (TOI), shifts, individual counting stats (Goals, Assists, Points, SOG, Hits, PIM, Faceoff Win %), on-ice metrics (Corsi, Fenwick rates), and expected goals (xG).
* Supports interactive situation filters (All Situations, 5v5, PP, PK) and dual Plotly shot attempt maps.

### Unified Strength-State Filters & Advanced Metric Tooltips
* Skater and goalie pages now support situation filters for shot mapping.
* Standardized advanced metric hover tooltips explaining analytical terms (Corsi, Fenwick, Expected Goals xG) are integrated across player profile tables, stats cards, and the comparison dashboard.

---

## 2. Bug Fixes & Refactoring

### Authoritative Roster Metadata & Historical Attribution
* Fixed an issue where historical players (e.g., Jonathan Huberdeau and Blake Coleman) were incorrectly assigned as centers. Positions and shooting/catching handedness are now loaded dynamically from the NHL API roster endpoints for the specific game's season, keyed on canonical player IDs.
* Excluded shootout (SO) goals and shots from goalie counting stats.
* Terminology update: Renamed display labels from "PP Shots Faced" to "Shots Faced Shorthanded" to reflect the goalie's defensive shorthanded perspective.

### Multi-Period On-Ice Lookup Bug
* Fixed the Period 2/3 on-ice player lookup bug. Replaced the simplistic query comparison with a centralized conversion method `OnIceService.period_time_to_game_elapsed(period, time_str)`. The `/api/game/<game_id>/on-ice` route now correctly retrieves overlapping shifts in periods 2, 3, and overtime.

### Refactored Player Game Service
* Decoupled the massive coordinator method `PlayerGameService.get_player_game_stats` into five specialized services for improved testability and maintainability:
  * `PlayerProfileService`: Biographical metadata and team resolution.
  * `PlayerTimelineService`: Chronological play-by-play events parser.
  * `GoalieStatsService`: Goalie statistics, save percentages, and splits.
  * `SkaterStatsService`: Skater performance counting stats, Corsi/Fenwick metrics, and xG.
  * `PlayerGameService`: Coordinates and delegates to the sub-services.

---

## 3. Testing & CI Updates

* **Strict Regression Tests**: Replaced conditional checks with explicit existence assertions in play-by-play tests (e.g., `assert blocked_event is not None`, `assert faceoff_event is not None`) to fail immediately if ingestion parsing breaks.
* **New Analytics Coverage**: Added `tests/test_v11_analytics.py` verifying line details, shared shifts, and player comparison stats calculations.
* **CI Configured**: Added `v1.1` release branch triggers to the GitHub Actions test workflow.
