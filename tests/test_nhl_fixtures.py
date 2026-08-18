import pytest
from data_pipeline.orchestrator import PipelineOrchestrator
from app.models import Game, Team, Player, Event, Shot, Shift
from app.services.game_service import GameService

def test_normal_game_fixture(app, db):
    """Tests loading and verifying a normal game (2023020007)."""
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success
    
    # Assert teams loaded
    teams = Team.query.all()
    assert len(teams) == 2
    
    # Assert scores are correct
    game = db.session.get(Game, 2023020007)
    assert game.home_score == 5
    assert game.away_score == 3
    
    # Assert coordinates are normalized (X should be standard, but check that they are inside standard rink bounds)
    shots = Shot.query.all()
    assert len(shots) > 0
    for shot in shots:
        assert -100 <= shot.x_coordinate <= 100
        assert -42.6 <= shot.y_coordinate <= 42.6
        
    # Run GameService overview checks
    overview = GameService.get_game_overview_stats(2023020007)
    assert overview is not None
    assert overview["home_score"] == 5
    assert overview["away_score"] == 3
    assert "1st Period" in overview["timeline"]
    assert "2nd Period" in overview["timeline"]
    assert "3rd Period" in overview["timeline"]

def test_shootout_game_fixture(app, db):
    """Tests loading and verifying a shootout game (2023020039)."""
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020039)
    assert success
    
    game = db.session.get(Game, 2023020039)
    assert game is not None
    
    # Check that shootout events were loaded with the correct properties
    shootout_events = Event.query.filter(Event.period_type == 'SO').all()
    assert len(shootout_events) > 0
    
    for event in shootout_events:
        assert event.period == 5
        assert event.period_type == 'SO'
        assert event.raw_situation_code in ['1010', '0101']
        assert event.manpower_state == 'SO'
        assert event.team_strength_state == '1v0'
        
    # Check game overview stats
    overview = GameService.get_game_overview_stats(2023020039)
    assert overview is not None
    
    # Assert shootout goals not counted as PPGs
    stats = overview["stats"]
    assert stats["home_ppg"] == 0
    assert stats["away_ppg"] == 1  # 1 PPG was scored in regulation by CGY (Away)
    
    # Assert shootout attempts not counted as normal SOG
    # SOG counts should not include shootout attempts
    assert stats["home_sog"] == 23
    assert stats["away_sog"] == 40
    
    # Timeline period label: assert "Shootout" is in the timeline keys
    assert "Shootout" in overview["timeline"]
    assert "Overtime" in overview["timeline"]
