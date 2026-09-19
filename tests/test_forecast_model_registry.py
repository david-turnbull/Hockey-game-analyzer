import os
import json
import pytest
import numpy as np
from app.analytics.forecasting.model_registry import ForecastModelRegistry, ModelUnavailableError
from app.analytics.forecasting.win_probability import WinProbabilityModel, FEATURE_NAMES

def test_no_dummy_model_fallback():
    """Verifies that an unfitted WinProbabilityModel raises RuntimeError on predict_game_probability (no dummy fallback)."""
    model = WinProbabilityModel()
    dummy_feats = {fname: 1.0 for fname in FEATURE_NAMES}
    with pytest.raises(RuntimeError, match="Fail-closed: cannot generate predictions"):
        model.predict_game_probability(dummy_feats)

def test_missing_artifact_fails_closed(tmp_path, monkeypatch):
    """Verifies that ForecastModelRegistry raises ModelUnavailableError when artifact file is missing."""
    monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))
    with pytest.raises(ModelUnavailableError, match="Production model artifact 'v9.9.9' not found"):
        ForecastModelRegistry.load_active_model(model_version="v9.9.9", force_reload=True)

def test_missing_manifest_fails_closed(tmp_path, monkeypatch):
    """Verifies that ForecastModelRegistry raises ModelUnavailableError when manifest file is missing."""
    monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))
    
    # Create fake pkl but no json
    pkl_file = tmp_path / "pucklens-win-v9.9.8.pkl"
    pkl_file.write_bytes(b"fake pickle content")

    with pytest.raises(ModelUnavailableError, match="metadata manifest 'v9.9.8' not found"):
        ForecastModelRegistry.load_active_model(model_version="v9.9.8", force_reload=True)

def test_sha256_hash_mismatch_fails_closed(tmp_path, monkeypatch):
    """Verifies that ForecastModelRegistry rejects model artifact if SHA-256 hash does not match manifest."""
    monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))

    pkl_file = tmp_path / "pucklens-win-v9.9.7.pkl"
    json_file = tmp_path / "pucklens-win-v9.9.7.json"

    pkl_file.write_bytes(b"actual pickle payload")
    
    manifest = {
        "model_name": "pucklens-win",
        "model_version": "v9.9.7",
        "model_architecture": "LogisticRegression",
        "artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "feature_names": FEATURE_NAMES
    }
    json_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelUnavailableError, match="SHA-256 hash mismatch"):
        ForecastModelRegistry.load_active_model(model_version="v9.9.7", force_reload=True)

def test_feature_schema_mismatch_fails_closed(tmp_path, monkeypatch):
    """Verifies that ForecastModelRegistry rejects artifact if manifest feature schema differs from runtime."""
    monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))

    pkl_file = tmp_path / "pucklens-win-v9.9.6.pkl"
    json_file = tmp_path / "pucklens-win-v9.9.6.json"

    pkl_file.write_bytes(b"content")
    actual_sha256 = ForecastModelRegistry.compute_sha256(str(pkl_file))

    manifest = {
        "model_name": "pucklens-win",
        "model_version": "v9.9.6",
        "model_architecture": "LogisticRegression",
        "artifact_sha256": actual_sha256,
        "feature_names": ["invalid_feature_A", "invalid_feature_B"]
    }
    json_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelUnavailableError, match="Feature schema mismatch"):
        ForecastModelRegistry.load_active_model(model_version="v9.9.6", force_reload=True)

def test_model_version_mismatch_fails_closed(tmp_path, monkeypatch):
    """Verifies that ForecastModelRegistry rejects model if manifest model_version differs from requested version."""
    monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))

    pkl_file = tmp_path / "pucklens-win-v9.9.5.pkl"
    json_file = tmp_path / "pucklens-win-v9.9.5.json"

    pkl_file.write_bytes(b"content")
    actual_sha256 = ForecastModelRegistry.compute_sha256(str(pkl_file))

    manifest = {
        "model_name": "pucklens-win",
        "model_version": "v9.9.0-wrong",
        "model_architecture": "LogisticRegression",
        "artifact_sha256": actual_sha256,
        "feature_names": FEATURE_NAMES
    }
    json_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ModelUnavailableError, match="Model version mismatch"):
        ForecastModelRegistry.load_active_model(model_version="v9.9.5", force_reload=True)

def test_valid_model_loading_and_deterministic_predictions(app, db, tmp_path, monkeypatch):
    """Verifies valid model artifact loading through registry and deterministic prediction generation."""
    from scripts.train_forecast_model import main as train_main
    from datetime import date, datetime

    with app.app_context():
        # Seed mock games
        from app.models import Team, Game
        t1 = Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])
        for s in ['20212022', '20222023', '20232024']:
            for i in range(5):
                g = Game(
                    game_id=int(f"{s[:4]}02{i+1:04d}"), season=s, game_type='R',
                    game_date=date(int(s[:4]), 10, 10 + i),
                    start_time_utc=datetime(int(s[:4]), 10, 10 + i, 19, 0, 0),
                    home_team_id=1, away_team_id=2,
                    home_score=3 if i % 2 == 0 else 1,
                    away_score=1 if i % 2 == 0 else 3,
                    nhl_game_state='OFF', data_source='nhl_api'
                )
                db.session.add(g)
        db.session.commit()

        monkeypatch.setattr(ForecastModelRegistry, "get_models_dir", lambda: str(tmp_path))
        
        # Train model into tmp_path
        model = WinProbabilityModel()
        model.train_and_select(skip_gate=True)
        
        pkl_path = tmp_path / "pucklens-win-v1.4.0.pkl"
        json_path = tmp_path / "pucklens-win-v1.4.0.json"
        
        model.save_model(str(pkl_path))
        sha256 = ForecastModelRegistry.compute_sha256(str(pkl_path))
        manifest = model.generate_metadata_manifest(artifact_sha256=sha256)
        
        json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        try:
            # Load through registry
            loaded_model, loaded_manifest = ForecastModelRegistry.load_active_model(model_version="v1.4.0", force_reload=True)
            assert loaded_model is not None
            assert loaded_manifest["artifact_sha256"] == sha256

            # Deterministic predictions test
            dummy_feats = {fname: 1.0 for fname in FEATURE_NAMES}
            pred1 = loaded_model.predict_game_probability(dummy_feats)
            pred2 = loaded_model.predict_game_probability(dummy_feats)

            assert pred1["home_win_probability"] == pred2["home_win_probability"]
            assert pred1["model_type"] == pred2["model_type"]
        finally:
            ForecastModelRegistry._cached_model = None
            ForecastModelRegistry._cached_manifest = None
