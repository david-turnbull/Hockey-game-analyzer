import os
import pytest
import subprocess
import sys
from datetime import datetime, timezone
from app.models import Game, Event, Shift, Team, db
from data_pipeline.ingest.nhl_api import NHLApiClient
from data_pipeline.transform.normalizer import DataNormalizer
from data_pipeline.loaders.db_loader import DatabaseLoader
from scripts.audit_seasons import audit_season_data
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.backtest_engine import BacktestEngine

def test_synthetic_generation_quarantine():
    """Verifies that synthetic data generation requires --testing-only flag."""
    script_path = os.path.join("scripts", "generate_synthetic_test_data.py")
    res = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    assert res.returncode != 0

def test_reingestion_timestamp_and_provenance_update(app, db):
    """Verifies that re-ingestion updates start_time_utc and data_source on existing games."""
    normalizer = DataNormalizer()
    loader = DatabaseLoader(db.session)
    with app.app_context():
        # Seed Teams for foreign key constraints
        t1 = Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team(team_id=2, abbreviation="VAN", name="Vancouver Canucks")
        db.session.add_all([t1, t2])
        db.session.commit()

        # Create initial game with synthetic tag and old timestamp
        old_time = datetime(2023, 10, 10, 19, 0, 0, tzinfo=timezone.utc)
        new_time = datetime(2023, 10, 10, 20, 0, 0, tzinfo=timezone.utc)

        raw_game_1 = {
            "id": 2023020001,
            "season": 20232024,
            "gameType": 2,
            "gameDate": "2023-10-10",
            "startTimeUTC": old_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gameState": "OFF",
            "homeTeam": {"id": 1, "score": 3},
            "awayTeam": {"id": 2, "score": 2}
        }
        
        g1 = normalizer.transform_game(raw_game_1, data_source='synthetic_test')
        db.session.add(g1)
        db.session.commit()

        # Verify initial state
        g_db = Game.query.get(2023020001)
        assert g_db.data_source == 'synthetic_test'

        # Re-ingest with nhl_api source and new timestamp
        raw_game_2 = {
            "id": 2023020001,
            "season": 20232024,
            "gameType": 2,
            "gameDate": "2023-10-10",
            "startTimeUTC": new_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gameState": "OFF",
            "homeTeam": {"id": 1, "score": 3},
            "awayTeam": {"id": 2, "score": 2}
        }
        g2 = normalizer.transform_game(raw_game_2, data_source='nhl_api')
        loader.load_game_data(g2, [], [], [], [], [])

        g_db_updated = Game.query.get(2023020001)
        assert g_db_updated.data_source == 'nhl_api'
        assert g_db_updated.start_time_utc.replace(tzinfo=timezone.utc) == new_time

def test_audit_season_data_metrics_and_synthetic_invalidation(app, db):
    """Verifies audit metric computation and status invalidation on synthetic contamination."""
    with app.app_context():
        # Clear existing games
        db.session.query(Game).delete()
        db.session.commit()

        # Seed Teams for foreign key constraints
        if not db.session.get(Team, 1):
            db.session.add(Team(team_id=1, abbreviation="CGY", name="Calgary Flames"))
        if not db.session.get(Team, 2):
            db.session.add(Team(team_id=2, abbreviation="VAN", name="Vancouver Canucks"))
        db.session.commit()

        g = Game(
            game_id=2023020002,
            season="20232024",
            game_type="R",
            game_date=datetime(2023, 10, 11).date(),
            start_time_utc=datetime(2023, 10, 11, 19, 0, tzinfo=timezone.utc),
            home_team_id=1,
            away_team_id=2,
            home_score=4,
            away_score=1,
            nhl_game_state="OFF",
            data_source="synthetic_test"
        )
        db.session.add(g)
        db.session.commit()

        summary = audit_season_data(app)
        assert summary["total_synthetic_games"] == 1
        assert summary["seasons"]["20232024"]["status"] == "INVALID"
        assert summary["production_forecast_data_gate"]["pass"] is False
        assert any("Synthetic data detected" in r for r in summary["production_forecast_data_gate"]["reasons"])

def test_production_training_gate_enforcement(app, db):
    """Verifies that WinProbabilityModel and BacktestEngine raise RuntimeError when data gate fails."""
    with app.app_context():
        model = WinProbabilityModel()
        with pytest.raises(RuntimeError, match="PRODUCTION FORECAST TRAINING BLOCKED"):
            model.train_and_select()

        engine = BacktestEngine()
        with pytest.raises(RuntimeError, match="PRODUCTION BACKTEST BLOCKED"):
            engine.run_full_backtest()

def test_malformed_disk_cache_handling(tmp_path):
    """Verifies that NHLApiClient._validate_json_file rejects truncated or invalid JSON files."""
    client = NHLApiClient()
    
    # Valid JSON
    valid_file = tmp_path / "valid.json"
    valid_file.write_text('{"status": "ok"}', encoding='utf-8')
    assert bool(client._validate_json_file(str(valid_file))) is True

    # Invalid / corrupted JSON
    invalid_file = tmp_path / "corrupt.json"
    invalid_file.write_text('{"status": "ok', encoding='utf-8')
    assert client._validate_json_file(str(invalid_file)) is None

    # Empty file
    empty_file = tmp_path / "empty.json"
    empty_file.write_text('', encoding='utf-8')
    assert client._validate_json_file(str(empty_file)) is None

def test_reset_script_safety_gate():
    """Verifies that reset_historical_data.py requires --confirm flag."""
    script_path = os.path.join("scripts", "reset_historical_data.py")
    res = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    assert res.returncode != 0
    assert "SAFETY GATE BLOCKED" in res.stderr or "SAFETY GATE BLOCKED" in res.stdout or "ERROR" in res.stderr or "ERROR" in res.stdout
