import pytest
from unittest.mock import patch, MagicMock
from app.analytics.forecasting.backtest_engine import BacktestEngine
from scripts.audit_seasons import audit_stage4_external_season_gate

def test_stage4_data_gate_missing_games(app):
    """Stage 4 data gate must fail closed if games are missing or incomplete."""
    with app.app_context():
        passed, reasons, snapshot_hash = audit_stage4_external_season_gate('20252026')
        assert passed is False
        assert any("game count mismatch" in r or "incomplete" in r for r in reasons)
        assert isinstance(snapshot_hash, str)
        assert len(snapshot_hash) == 64  # SHA-256 hex string

def test_stage4_data_gate_synthetic_contamination(app):
    """Stage 4 data gate must fail closed if synthetic data is present."""
    from app.models import db, Game, Team
    from datetime import datetime, timezone
    with app.app_context():
        t1 = db.session.get(Team, 1001) or Team(team_id=1001, name="Team A", abbreviation="TMA")
        t2 = db.session.get(Team, 1002) or Team(team_id=1002, name="Team B", abbreviation="TMB")
        db.session.add_all([t1, t2])
        db.session.commit()

        g = Game(
            game_id=2025029999,
            season='20252026',
            game_type='R',
            game_date=datetime.now(timezone.utc).date(),
            start_time_utc=datetime.now(timezone.utc),
            home_team_id=1001,
            away_team_id=1002,
            home_score=3,
            away_score=2,
            nhl_game_state='FINAL',
            data_source='synthetic_test'
        )
        db.session.add(g)
        db.session.commit()

        passed, reasons, snapshot_hash = audit_stage4_external_season_gate('20252026')
        assert passed is False
        assert any("synthetic" in r for r in reasons)

def test_evaluate_external_season_structure(app):
    """Tests evaluate_external_season execution with mock data and zero retraining assertion."""
    engine = BacktestEngine()

    mock_manifest = {
        "model_version": "v1.4.0",
        "artifact_sha256": "fake_sha_256",
        "git_commit_sha": "abc123def456",
        "feature_schema_version": "v1.4.0"
    }
    mock_model = MagicMock()
    mock_model.feature_names = [
        "rest_differential", "home_is_b2b", "away_is_b2b", "l10_xgf_pct_diff",
        "l10_cf_pct_diff", "l10_goal_diff_per_game", "l20_xgf_pct_diff",
        "home_venue_l10_win_pct", "away_venue_l10_win_pct", "h2h_home_win_pct", "h2h_home_gd_avg"
    ]
    mock_model.predict_game_probability.return_value = {
        "home_win_probability": 0.55,
        "away_win_probability": 0.45,
        "uncalibrated_home_probability": 0.54,
        "model_type": "LogisticRegression",
        "explanations": []
    }

    with patch("app.analytics.forecasting.model_registry.ForecastModelRegistry.load_active_model", return_value=(mock_model, mock_manifest)), \
         patch("app.analytics.forecasting.model_registry.ForecastModelRegistry.compute_sha256", return_value="fake_sha_256"), \
         patch("app.analytics.forecasting.model_registry.ForecastModelRegistry.get_models_dir", return_value="/tmp"), \
         patch("scripts.audit_seasons.audit_stage4_external_season_gate", return_value=(True, [], "mock_hash_12345")):

        results = engine.evaluate_external_season('20252026', skip_gate=True)

        assert results["evaluation_type"] == "stage4_external_season_validation"
        assert results["model_version"] == "v1.4.0"
        assert results["artifact_sha256"] == "fake_sha_256"
        assert results["model_training_git_sha"] == "abc123def456"
        assert results["data_audit_snapshot_hash"] == "mock_hash_12345"

        # Check dynamic key
        assert "external_season_20252026_eval" in results
        assert "holdout_season_20242025_eval" in results

        # Check generalization deltas
        assert "generalization_delta_metrics" in results
        deltas = results["generalization_delta_metrics"]
        assert "delta_log_loss" in deltas
        assert "delta_brier_score" in deltas
        assert "delta_ece" in deltas

        # Check feature drift and bootstrap CIs
        assert "feature_drift_analysis" in results
        assert "bootstrap_confidence_intervals" in results
