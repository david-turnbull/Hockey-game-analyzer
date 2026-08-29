import pytest
from app.models import Game, Player, Event, Shot, Shift
from data_pipeline.orchestrator import PipelineOrchestrator
from app.services.game_service import GameService

def test_rich_event_parsing_and_normalization(app, db):
    """
    Verifies that play-by-play ingestion parses rich details and normalized coordinates.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    # 1. Verify Blocked Shot maps shooting player and blocking player
    blocked_event = Event.query.filter_by(game_id=2023020007, event_type='blocked-shot').first()
    if blocked_event:
        assert blocked_event.primary_player_id is not None  # shooter
        assert blocked_event.secondary_player_id is not None  # blocker
        # Verify normalized coordinates exist on the event model itself
        assert blocked_event.x_coordinate_normalized is not None
        assert blocked_event.y_coordinate_normalized is not None
        
    # 2. Verify Faceoff winner, loser, and zone code
    faceoff_event = Event.query.filter_by(game_id=2023020007, event_type='faceoff').first()
    if faceoff_event:
        assert faceoff_event.primary_player_id is not None  # winner
        assert faceoff_event.secondary_player_id is not None  # loser
        assert faceoff_event.zone_code in ['N', 'D', 'O']
        assert faceoff_event.x_coordinate_normalized is not None
        assert faceoff_event.y_coordinate_normalized is not None

    # 3. Verify Penalty details (duration, infraction, served_by if available)
    penalty_event = Event.query.filter_by(game_id=2023020007, event_type='penalty').first()
    if penalty_event:
        assert penalty_event.primary_player_id is not None  # committed by
        assert penalty_event.penalty_duration is not None
        assert penalty_event.penalty_description is not None
        # penalty_type_code should be parsed (e.g. MIN, MAJ)
        assert penalty_event.penalty_type_code is not None

def test_timeline_enrichment(app, db):
    """
    Verifies that the chronological timeline fetches and formats hits, faceoffs, missed shots, and blocked shots.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    overview = GameService.get_game_overview_stats(2023020007)
    assert overview is not None
    assert "timeline" in overview
    
    # Flatten all timeline events across periods
    all_events = []
    for period_events in overview["timeline"].values():
        all_events.extend(period_events)
        
    event_types = {ev["event_type"] for ev in all_events}
    
    # Assert we support and parsed more event types beyond just goals and penalties
    assert "goal" in event_types
    assert "penalty" in event_types
    
    # Find faceoff, hit, or block in the timeline and assert descriptions are formatted
    for ev in all_events:
        if ev["event_type"] == "faceoff":
            assert "winner" in ev
            assert "loser" in ev
            assert "description" in ev
            assert "won faceoff vs" in ev["description"]
        elif ev["event_type"] == "hit":
            assert "hitter" in ev
            assert "hittee" in ev
            assert "description" in ev
            assert "hit" in ev["description"]
        elif ev["event_type"] == "blocked-shot":
            assert "shooter" in ev
            assert "blocker" in ev
            assert "description" in ev
            assert "blocked by" in ev["description"]
