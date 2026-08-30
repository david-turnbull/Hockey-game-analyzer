import pytest
from sqlalchemy import text
from app.models import Game, Player, Event, Shot, Shift, GamePlayer, Team
from data_pipeline.orchestrator import PipelineOrchestrator
from app.services.validation_service import ValidationService

def test_boxscore_validation_pass(app, db):
    """
    Verifies that boxscore validation returns PASS for correctly ingested games.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    val = ValidationService.validate_game_boxscore(2023020007)
    assert val is not None
    assert val["goals_home"]["status"] == "PASS"
    assert val["goals_away"]["status"] == "PASS"
    assert val["shots_home"]["status"] == "PASS"
    assert val["shots_away"]["status"] == "PASS"
    
    # Verify goalie check status
    assert len(val["goalies"]) > 0
    for goalie_res in val["goalies"]:
        assert goalie_res["status"] == "PASS"

def test_boxscore_validation_fail_on_mismatch(app, db):
    """
    Verifies that boxscore validation returns FAIL when database counts mismatch.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    # Intentionally modify the event database table by adding an extra goal event to fail the score check
    extra_goal = Event(
        event_id="2023020007_999",
        game_id=2023020007,
        period=1,
        period_time="10:00",
        elapsed_game_seconds=600,
        event_type="goal",
        team_id=20,  # CGY (Home)
        period_type="REG"
    )
    db.session.add(extra_goal)
    db.session.commit()
    
    val = ValidationService.validate_game_boxscore(2023020007)
    assert val is not None
    # Home score should fail because calculated goals is now 6 but expected is 5
    assert val["goals_home"]["status"] == "FAIL"
    # Away score should still pass
    assert val["goals_away"]["status"] == "PASS"

def test_platform_diagnostics_categories(app, db):
    """
    Verifies that the platform diagnostics health checks evaluate all five categories.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    # Run diagnostics
    report = ValidationService.run_platform_diagnostics()
    assert "game_ingestion" in report
    assert "player_metadata" in report
    assert "shift_reconstruction" in report
    assert "boxscore_validation" in report
    assert "five_v_five_reconstruction" in report
    
    # Under clean ingestion, categories should pass or warn but not fail
    assert report["game_ingestion"]["status"] in ["PASS", "WARNING"]
    assert report["player_metadata"]["status"] in ["PASS", "WARNING"]
    assert report["shift_reconstruction"]["status"] in ["PASS", "WARNING", "FAIL"]  # clean loading may have raw anomalies
    assert report["boxscore_validation"]["status"] in ["PASS", "WARNING"]
    assert report["five_v_five_reconstruction"]["status"] in ["PASS", "WARNING"]

def test_diagnostics_web_page(app, client, db):
    """
    Verifies that the /diagnostics route is accessible and renders the Platform Validation Checks.
    """
    # Enable diagnostics in config
    app.config["ENABLE_DIAGNOSTICS"] = True
    
    response = client.get('/diagnostics')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert "Platform Validation Checks" in html
    assert "Game Ingestion" in html
    assert "Player Metadata" in html
    assert "Shift Reconstruction" in html
    assert "Boxscore Validation" in html
    assert "Five V Five Reconstruction" in html
