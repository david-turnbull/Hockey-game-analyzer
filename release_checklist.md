# NHL Hockey Analytics Platform v1.0 Release Checklist

This checklist documents the release criteria that must be verified before tagging the repository as `v1.0`.

- [ ] **Environment and Setup**
  - [ ] A fresh python virtual environment can successfully install all dependencies from `requirements.txt`.
  - [ ] The local SQLite database can be initialized from scratch using `python scripts/initialise_database.py`.
  - [ ] At least one complete game's API data can be ingested and loaded cleanly (`python scripts/ingest_game.py 2023020007`).

- [ ] **Database Integrity Diagnostics**
  - [ ] Running the integrity checker results in a `PASS` or `PASS WITH WARNINGS` with zero fatal integrity issues:
    ```bash
    python scripts/database_diagnostics.py
    ```
  - [ ] Mismatches between shift teams and historical roster teams are zero.
  - [ ] Orphan game roster (`GamePlayer`) rows are zero.

- [ ] **Functional & Analytical Correctness**
  - [ ] **Historical Player-Team Attribution:** Querying historical games resolves a player's team accurately relative to that game date, independent of subsequent trades (verified by `tests/test_historical_attribution.py`).
  - [ ] **True 5v5 Possession:** CF, CA, FF, FA metrics in `"5v5"` mode contain only true 5v5 events (excluding 4v4, 3v3, power play, penalty kill, empty-net, shootouts) (verified by `tests/test_possession_strengths.py`).
  - [ ] **Shift Boundaries:** Shift change boundary detection uses half-open interval semantics `[start, end)` (verified by `tests/test_shift_boundaries.py`).
  - [ ] **Authoritative On-Ice Service:** All calculations (possession, line combinations, etc.) delegate shift matching to the centralized `OnIceService` rules.
  - [ ] **Line Combinations and Defensive Pairings:** Skaters are grouped correctly and on-ice statistics match expectations.

- [ ] **User Interface Verification**
  - [ ] Game selector on index page loads available seasons and teams successfully.
  - [ ] Detailed game dashboard (/game/<game_id>) displays team boxscore comparison, chronological goals/penalties timeline, interactive shot map, and line combinations.
  - [ ] Player individual game dashboard (/game/<game_id>/player/<player_id>) displays player statistics, shift chart, and prototype xG values.
  - [ ] All Expected Goals metrics are explicitly labeled as "Prototype Expected Goals (xG)" or "Prototype Expected Goal Estimate".

- [ ] **CI & Test Suite**
  - [ ] The automated test suite runs successfully with zero failures:
    ```bash
    pytest
    ```
  - [ ] Continuous Integration workflow in GitHub Actions passes.

- [ ] **Documentation**
  - [ ] The `README.md` file is complete, professional, and includes:
    - [ ] Project title, summary, and capabilities description.
    - [ ] Mermaids architecture diagram.
    - [ ] Definitions of analytical terms (Corsi, Fenwick, 5v5, TOI, xG).
    - [ ] Documentation of the prototype xG formulas and hand-selected coefficients.
    - [ ] List of known limitations.
    - [ ] Project development roadmap.
