# PuckLens - Version 1.3.0 Release Notes

**Release Date:** September 2026  
**Theme:** Season Analytics, Out-of-Time Predictive Validation, Rolling Trends, and Model Explainability

PuckLens version 1.3.0 expands the platform from single-game diagnostics to complete multi-season analytics, rigorous out-of-time model validation on the 2024-25 NHL season, chronological rolling performance trends, mathematical expected goal (xG) explainability, RESTful season APIs, and responsive team, player, and goalie dashboards.

---

## 1. Multi-Season Data Pipeline Foundation (2024-25 Data)
- **Multi-Season Isolation:** Ingestion pipelines and storage cleanly support multiple distinct seasons (e.g., `20232024`, `20242025`) without cross-contamination.
- **Orchestrator Ingestion Metrics:** Added `ingest_game` and `ingest_season` telemetry reporting total events, shots, shifts, players, cached vs live downloads, and runtime.
- **Selective Team / Schedule Ingestion:** `scripts/ingest_season.py` supports targeted ingestion via `--season <season> --team <team_abbr>` (e.g. `--season 20242025 --team CGY`) and league-wide `--all` execution.
- **Cache & Idempotency Safeguards:** Skips already ingested final games when re-run, eliminating redundant external network traffic.

---

## 2. Out-of-Time xG Validation (Frozen Model Invariant)
- **Strict Invariance:** Evaluated the released `v1.2.1` logistic regression model (`models/xg/xg_v1.pkl`) on freshly ingested 2024-25 regular season games without retraining, parameter tuning, or calibration shifts.
- **Validation Dataset:** 25 regular season games from 2024-25 (8,790 events, 3,182 shot attempts, 2,190 unblocked attempts, 136 actual goals).
- **Predictive Results:**
  - **Actual Goal Rate:** 6.21%
  - **Predicted Expected Goal Rate:** 6.66% (Total xG: 145.86 vs 136 actual goals)
  - **Calibration Ratio:** 0.9324
  - **Log Loss:** 0.2057 (beats baseline test set 0.2127)
  - **Brier Score:** 0.0544 (beats baseline test set 0.0562)
  - **ROC AUC:** 0.7603 (healthy discriminative ranking)
- **Stability Verdict:** **HEALTHY** — Model demonstrates excellent generalization to out-of-time 2024-25 NHL data with no indication of concept drift or calibration collapse.

---

## 3. Team Season Analytics
- **Grouped SQL Aggregation:** Aggregates team standings and canonical analytics in grouped SQL queries with zero N+1 overhead.
- **Situational Filters:** Fully supports `all`, `5v5`, `pp`, and `sh` game states.
- **Key Metrics:**
  - Traditional: GP, W, L, OTL, PTS, GF, GA, Goal Differential
  - Shot Attempt Shares: Corsi For ($CF$), Corsi Against ($CA$), Corsi Share ($CF\%$), Fenwick For ($FF$), Fenwick Against ($FA$), Fenwick Share ($FF\%$)
  - Quality Metrics: Expected Goals For ($xGF$), Expected Goals Against ($xGA$), Expected Goal Share ($xG\%$)
  - Per-60 Rates: $xGF/60$, $xGA/60$, and $xG$ Differential
  - Process Variances: Finishing Luck ($GF - xGF$) and Goaltending Variance ($xGA - GA$)
- **Season Rankings:** Automated analytical rankings across all teams.

---

## 4. Skater & Goalie Season Analytics
- **Skater Profiles & Leaderboards:**
  - Individual counting metrics: GP, G, A, PTS, SOG, Unblocked Attempts
  - Predictive metrics: $xG$, Goals Above Expected ($G - xG$), $xG/60$, $G/60$
  - Shooting efficiencies: Shooting Percentage ($Sh\%$) vs Expected Conversion ($xG / \text{Unblocked}$)
  - 5v5 On-Ice possession impact: $CF\%$, $FF\%$, and On-Ice $xG\%$
  - Configurable minimum thresholds: `min_gp`, `min_toi_seconds`, `min_unblocked_attempts`
- **Goaltender Performance & GSAx:**
  - Workload and counting stats: GP, TOI, Shots Faced, GA, Saves, $Sv\%$
  - Quality metrics: $xGA$, Goals Saved Above Expected ($GSAx$), $GSAx/60$, Expected Save % ($Exp\ Sv\%$), and Save % Differential ($Sv\%\ Diff$)
  - **Domain Rules Invariant:** Empty-net shots and shootouts are strictly barred from $xGA$ and $GSAx$ calculations.

---

## 5. Chronological Rolling Form & Trends
- **Zero Future Leakage:** Strictly orders games chronologically and computes rolling windows using past games only.
- **Multi-Window Team Form:** 5-game, 10-game, and 20-game rolling windows for $xGF\%$, $xG$ diff, $xGF/60$, $xGA/60$, $CF\%$, $FF\%$, and finishing luck.
- **Player & Goalie Rolling Form:** 5-game rolling windows for skater $xG$, $G - xG$, shot volume, and goalie $GSAx$ and $Sv\%$.

---

## 6. Expected Goals (xG) Explainability
- **Mathematical Logit Decomposition:** Deconstructs logistic regression predictions:
  $$\text{logit} = \beta_0 + \sum_{k=1}^{M} \beta_k \cdot x_k, \quad \text{xG} = \sigma(\text{logit})$$
- **Feature Contribution Factors:**
  - Danger-increasing factors ($\beta_k \cdot x_k > 0$) with positive logit impact.
  - Danger-reducing factors ($\beta_k \cdot x_k < 0$) with negative logit impact.
  - Baseline comparison: odds multiplier vs average unblocked attempt ($6.6\%$).
- **Blocked Attempt Protection:** Blocked attempts (`Shot.outcome == 'Blocked'`) are strictly rejected with HTTP 400.

---

## 7. Season RESTful API Endpoints
- `GET /api/seasons`: List all ingested seasons.
- `GET /api/seasons/<season>/teams`: Team analytical standings, rates, and rankings.
- `GET /api/teams/<team_id>/season/<season>`: Complete team season analytical profile.
- `GET /api/teams/<team_id>/season/<season>/trends`: Multi-window rolling trends.
- `GET /api/teams/<team_id>/season/<season>/players`: Skaters season summary for roster.
- `GET /api/teams/<team_id>/season/<season>/goalies`: Goalie season summary for roster.
- `GET /api/players/<player_id>/season/<season>`: Skater individual & on-ice metrics.
- `GET /api/goalies/<goalie_id>/season/<season>`: Goalie workload, $xGA$, and $GSAx$.
- `GET /api/seasons/<season>/leaders`: Analytical leaderboards with sample filtering.
- `GET /api/shots/<shot_id>/xg-explanation`: Feature contribution explanation.

---

## 8. Responsive Dashboards & UI Experience
- **League Overview Dashboard (`/season/<season>`):** Interactive team standings table sortable by any column with situation toggle (All vs 5v5) and leaders preview.
- **Team Season Dashboard (`/team/<team_id>/season/<season>`):** Analytical KPI cards, Plotly rolling form chart, skater table, goalie table, and recent games.
- **Skater Season Profile (`/player/<player_id>/season/<season>`):** Totals, 5v5 on-ice possession grid, and rolling form trend chart.
- **Goalie Season Profile (`/goalie/<goalie_id>/season/<season>`):** Workload, $GSAx$, $Exp\ Sv\%$, and rolling performance chart.
- **Interactive Shot Map Model Popover:** Click any shot attempt marker on the rink in `/game/<game_id>` to open an interactive breakdown of model contributions.

---

## 9. Test Suite & Verification
- **Automated Tests:** 129 passing unit, integration, and regression tests.
- **Backward Compatibility:** All existing v1.2.1 tests and features remain 100% intact.
