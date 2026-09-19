# PuckLens v1.4 Historical Data Ingestion & Data Provenance Hardening

## 1. Overview & Data Provenance Rules

PuckLens v1.4 introduces strict data provenance tracking and quarantine rules to ensure that production forecast model training and historical backtesting are based **exclusively** on authentic NHL API data.

### Provenance Classification (`Game.data_source`)
All game records in the database feature a mandatory `data_source` string column with the following valid values:
- `nhl_api`: Verified real NHL game data fetched via official NHL APIs (`api-web.nhle.com` or `statsapi.web.nhl.com`).
- `synthetic_test`: Quarantined synthetic test data generated solely for testing pipeline infrastructure.

### Synthetic Data Quarantine Rules
1. Synthetic test data generation is strictly restricted to `scripts/generate_synthetic_test_data.py`.
2. The script requires the mandatory `--testing-only` CLI flag.
3. Every generated synthetic game record is explicitly tagged with `data_source = 'synthetic_test'`.
4. Legacy generation scripts (`scripts/backfill_seasons.py`) are deprecated and automatically redirect to `generate_synthetic_test_data.py --testing-only`.

---

## 2. Ingestion & Hardened Resilience

### Multi-Season Ingestion Wrapper (`scripts/ingest_forecast_history.py`)
Collects target regular seasons (e.g. 20212022, 20222023, 20232024, 20242025) sequentially from the NHL API. Upon completion, it automatically executes `scripts/audit_seasons.py` to evaluate completeness and gate criteria.

### API Client Resilience (`NHLApiClient`)
- **Bounded Exponential Backoff Retries:** Network requests (`_fetch_url`) retry up to 3 times with exponential backoff (`1.0s`, `2.0s`, `4.0s`) on HTTP errors or timeouts.
- **Cache Integrity Validation:** Disk-cached JSON files (`_validate_json_file`) are checked for malformed or truncated content before loading. Corrupted cache files are automatically purged and re-fetched from the API.

### Orchestrator Optimizations (`PipelineOrchestrator`)
- **In-Memory Roster Caching:** Avoids redundant `get_season_roster` calls during multi-game ingestion loops.

### Re-Ingestion Update Behavior (`db_loader.py`)
When updating existing game records during re-ingestion:
- `start_time_utc` is explicitly overwritten with fresh API values.
- `data_source` is set to the incoming loader `data_source` (default `'nhl_api'`), removing legacy synthetic tags if replacing a synthetic record with real data.

---

## 3. Season Completeness & Provenance Audit (`scripts/audit_seasons.py`)

The audit utility evaluates historical regular season game coverage on a per-season basis across 7 key feature metrics:
1. `actual_regular_season_games`: Total regular season games in database.
2. `completed_regular_season_games`: Games with state `OFF`, `FINAL`, or `OVER`.
3. `start_time_coverage_pct`: % of games with valid `start_time_utc` timestamps.
4. `pbp_coverage_pct`: % of games with play-by-play event data (`Event`).
5. `shot_coverage_pct`: % of games with shot attempts (`Shot`).
6. `xg_coverage_pct`: % of games with calculated expected goals (`Shot.xg`).
7. `shift_coverage_pct`: % of games with player shift data (`Shift`) — *Reported separately as optional data*.

### Season Status Criteria
- **`COMPLETE`**: Exactly 1,312 games, 100% completed, $\ge 99\%$ `start_time_utc` coverage, $\ge 99\%$ PBP event coverage, $0$ synthetic games.
- **`PARTIAL`**: Real games present but incomplete season coverage.
- **`INVALID`**: Contains synthetic test games, unknown provenance games, or duplicate game IDs.

---

## 4. Production Forecast Model & Backtest Gate

Model training (`WinProbabilityModel.train_and_select()`) and backtesting (`BacktestEngine.run_full_backtest()`) enforce a **hard production gate**:

1. **At least 3 regular seasons** must have `status == 'COMPLETE'`.
2. **Total synthetic games in database must equal 0**.

If synthetic contamination is detected (`total_synthetic_games > 0`) or fewer than 3 complete seasons exist, model training and backtesting are **strictly blocked** with a `RuntimeError`.

---

## 5. Historical Data Reset (`scripts/reset_historical_data.py`)

To safely purge all game records and derived data, run:
```bash
python scripts/reset_historical_data.py --confirm
```
This utility removes records from dependent tables in order (`GamePrediction`, `Shift`, `Shot`, `Event`, `PlayerGame`, `TeamGame`, `Game`) only when the explicit `--confirm` flag is provided.
