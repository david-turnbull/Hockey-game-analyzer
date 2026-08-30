import pytest
import logging
import os
from sqlalchemy.exc import IntegrityError
from app import create_app
from app.models import Game, Team, Player, Event, Shot, Shift
from data_pipeline.transform.normalizer import parse_time_to_seconds, parse_situation_code_raw, derive_event_manpower
from data_pipeline.validation.ingestion_validator import IngestionValidator

def test_sqlite_foreign_key_enforcement(app, db):
    """Verifies that inserting a record with a non-existent foreign key fails."""
    invalid_event = Event(
        event_id="fk_test_event",
        game_id=999999999,  # does not exist
        period=1,
        period_time="10:00",
        elapsed_game_seconds=600,
        event_type="hit"
    )
    db.session.add(invalid_event)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

def test_duplicate_logging_handlers(app):
    """Verifies that calling create_app multiple times does not add duplicate FileHandlers."""
    initial_handlers_count = len(app.logger.handlers)
    
    # Call create_app again
    app2 = create_app('testing')
    handlers_count2 = len(app2.logger.handlers)
    
    # Call create_app a third time
    app3 = create_app('testing')
    handlers_count3 = len(app3.logger.handlers)
    
    # Assert counts remain identical (idempotent)
    assert handlers_count2 == initial_handlers_count
    assert handlers_count3 == initial_handlers_count

def test_position_aware_shift_validation():
    """Verifies that goalie shifts are validated using separate thresholds from skater shifts."""
    checker = IngestionValidator()
    
    # Skater shift > 300s (excessive)
    skater_shift = Shift(
        shift_id="skater_shift",
        game_id=1,
        player_id=101,
        period=1,
        start_time="00:00",
        end_time="06:00",
        start_elapsed_seconds=0,
        end_elapsed_seconds=360,
        duration=360
    )
    
    # Goalie shift > 300s but <= 4800s (not excessive for goalies)
    goalie_shift = Shift(
        shift_id="goalie_shift",
        game_id=1,
        player_id=102,
        period=1,
        start_time="00:00",
        end_time="30:00",
        start_elapsed_seconds=0,
        end_elapsed_seconds=1800,
        duration=1800
    )
    
    # Goalie shift > 4800s (excessive goalie shift)
    excessive_goalie_shift = Shift(
        shift_id="excessive_goalie_shift",
        game_id=1,
        player_id=102,
        period=1,
        start_time="00:00",
        end_time="85:00",
        start_elapsed_seconds=0,
        end_elapsed_seconds=5100,
        duration=5100
    )
    
    # Map player positions
    player_positions = {101: "C", 102: "G"}
    
    # Validate skater shift
    checker.validate_shifts([skater_shift], player_positions)
    warnings = checker.get_summary()["warnings"]
    assert any("Excessive shift duration: 360s" in w["message"] for w in warnings)
    
    # Reset checker and validate goalie shift (should NOT warn)
    checker2 = IngestionValidator()
    checker2.validate_shifts([goalie_shift], player_positions)
    assert len(checker2.get_summary()["warnings"]) == 0
    
    # Validate excessive goalie shift (should warn)
    checker3 = IngestionValidator()
    checker3.validate_shifts([excessive_goalie_shift], player_positions)
    warnings3 = checker3.get_summary()["warnings"]
    assert any("Excessive goalie shift duration: 5100s" in w["message"] for w in warnings3)

def test_zero_duration_shift_anomaly():
    """Verifies that zero-duration shifts are preserved but flagged as anomalies."""
    checker = IngestionValidator()
    zero_shift = Shift(
        shift_id="zero_shift",
        game_id=1,
        player_id=101,
        period=1,
        start_time="10:00",
        end_time="10:00",
        start_elapsed_seconds=600,
        end_elapsed_seconds=600,
        duration=0
    )
    
    valid_shifts = checker.validate_shifts([zero_shift])
    assert len(valid_shifts) == 1
    assert valid_shifts[0].is_anomaly is True
    assert valid_shifts[0].anomaly_description == "Zero-duration shift"
    
    warnings = checker.get_summary()["warnings"]
    assert any("Zero-duration shift detected" in w["message"] for w in warnings)

def test_invalid_clock_handling():
    """Verifies that invalid clock values return None and emit warnings."""
    # Test parser
    assert parse_time_to_seconds("abc") is None
    assert parse_time_to_seconds("") is None
    assert parse_time_to_seconds("10:60") is None
    assert parse_time_to_seconds("-05:00") is None
    assert parse_time_to_seconds("05") is None
    
    # Test validation warning
    checker = IngestionValidator()
    invalid_event = Event(
        event_id="invalid_clock_event",
        game_id=1,
        period=1,
        period_time="99:99",
        elapsed_game_seconds=None,  # parsed as invalid
        event_type="hit"
    )
    
    valid = checker.validate_event(invalid_event, known_player_ids=set(), known_team_ids=set())
    assert valid is True  # preserved, not rejected
    warnings = checker.get_summary()["warnings"]
    assert any("Malformed or missing clock value" in w["message"] for w in warnings)

def test_strengthened_shot_validation():
    """Verifies that missing shot shooters cause fatal validation rejection."""
    checker = IngestionValidator()
    
    # 1. Shot with shooter not in roster
    shot_no_roster = Shot(
        shot_id="shot_1",
        shooter_id=999,  # not in roster
        x_coordinate=80.0,
        y_coordinate=5.0,
        distance=10.0,
        angle=10.0,
        outcome="Saved"
    )
    
    valid1 = checker.validate_shot(shot_no_roster, known_player_ids={1, 2})
    assert valid1 is False  # rejected!
    
    # 2. Shot with missing shooter ID
    shot_missing_shooter = Shot(
        shot_id="shot_2",
        shooter_id=None,
        x_coordinate=80.0,
        y_coordinate=5.0,
        distance=10.0,
        angle=10.0,
        outcome="Saved"
    )
    
    valid2 = checker.validate_shot(shot_missing_shooter, known_player_ids={1, 2})
    assert valid2 is False  # rejected!
