# NHL Hockey Analytics Platform v1.0 Release Checklist

This checklist documents the release criteria that must be verified before tagging the repository as `v1.0`.

- [x] **Environment and Setup**
  - [x] A fresh python virtual environment can successfully install all dependencies from `requirements.txt`.
  - [x] The local SQLite database can be initialized from scratch using `python scripts/initialise_database.py`.
  - [x] At least one complete game's API data can be ingested and loaded cleanly (`python scripts/ingest_game.py 2023020007`).

- [x] **Database Integrity Diagnostics**
  - [x] Running the integrity checker results in a `PASS` or `PASS WITH WARNINGS` with zero fatal integrity issues (verified by `tests/test_diagnostics.py`):
    ```bash
    python scripts/database_diagnostics.py
    ```
  - [x] Mismatches between shift teams and historical roster teams are zero.
  - [x] Orphan game roster (`GamePlayer`) rows are zero.
  - [x] Missing GamePlayer relationships (players in shifts/events without a GamePlayer row) are checked and zero.

- [x] **Functional & Analytical Correctness**
  - [x] **Historical Roster Attribution is Authoritative:** Querying historical games resolves a player's team accurately relative to that game date, independent of subsequent trades (verified by `tests/test_historical_attribution.py`).
  - [x] **No Silent Historical Fallback to `current_team_id`:** Safe fallback hierarchy (shifts, events, unresolved) is used to determine player team in case GamePlayer is missing. No silent current team fallback is used (verified by `tests/test_historical_fallback.py`).
  - [x] **True 5v5 Possession:** CF, CA, FF, FA metrics in `"5v5"` mode contain only true 5v5 events (excluding 4v4, 3v3, power play, penalty kill, empty-net, shootouts) (verified by `tests/test_possession_strengths.py`).
  - [x] **Half-Open Shift Semantics are Consistent:** Shift change boundary detection uses half-open interval semantics `[start, end)` (verified by `tests/test_shift_boundaries.py`).
  - [x] **Authoritative On-Ice Service:** All calculations (possession, line combinations, etc.) delegate shift matching to the centralized `OnIceService` rules (verified by `tests/test_line_service_on_ice.py`).
  - [x] **LineService Delegates On-Ice Logic Appropriately:** `LineService` uses `OnIceService.build_active_players_timeline` to fetch timelines (verified by `tests/test_line_service_on_ice.py`).
  - [x] **Player TOI/Average-Shift Calculations Use Valid Shifts:** Average shift duration divides valid TOI by the count of *valid* shifts, excluding anomalies (verified by `tests/test_avg_shift_calculation.py`).

- [x] **User Interface Verification**
  - [x] Game selector on index page loads available seasons and teams successfully.
  - [x] Detailed game dashboard (/game/<game_id>) displays team boxscore comparison, chronological goals/penalties timeline, interactive shot map, and line combinations.
  - [x] Player individual game dashboard (/game/<game_id>/player/<player_id>) displays player statistics, shift chart, and prototype xG values.
  - [x] **Undefined Possession Percentages Display as N/A:** When `CF + CA = 0` or `FF + FA = 0`, percentages are rendered cleanly as `N/A` on the dashboards, and actual `0%` remains `0%` (verified by `tests/test_empty_possession.py`).

- [x] **CI & Test Suite**
  - [x] The automated test suite runs successfully with zero failures (all 33 tests pass):
    ```bash
    pytest
    ```
  - [x] **GitHub Actions Runs on the Release Candidate:** CI workflow in `.github/workflows/tests.yml` triggers on pushes to the `v1.0` branch and pull requests.

- [x] **Documentation & Repository Presentation**
  - [x] The `README.md` file is complete, professional, and includes:
    - [x] Project title, summary, and capabilities description.
    - [x] Mermaids architecture diagram rendering correctly.
    - [x] Definitions of analytical terms (Corsi, Fenwick, 5v5, TOI, xG).
    - [x] Documentation of the prototype xG formulas and hand-selected coefficients.
    - [x] List of known limitations.
    - [x] Project development roadmap.
    - [x] CI/test documentation and build status badge.
  - [x] **Screenshots Status:** Screenshot folder `docs/screenshots/` exists, and required screenshots (Game selector, Game overview, Shot map, Player Game Page, Lines / possession analysis) are listed in the README as pending.
