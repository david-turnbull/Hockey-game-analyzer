import pytest
from datetime import date
from data_pipeline.transform.normalizer import (
    normalize_coordinates,
    calculate_shot_metrics,
    parse_situation_code,
    DataNormalizer
)
from data_pipeline.validation.ingestion_validator import IngestionValidator
from data_pipeline.loaders.db_loader import DatabaseLoader
from app.models import Team, Player, Game, Event, Shot, Shift

def test_coordinate_normalization():
    # Test cases for normalize_coordinates(x, y, period, home_defending_side, is_home_team)
    
    # 1. Home defends 'left' (attacks right): Home team shooting from right side. No flip.
    x, y = normalize_coordinates(80, 10, 1, 'left', is_home_team=True)
    assert x == 80 and y == 10
    
    # 2. Home defends 'left' (attacks right): Away team shooting. Flip needed (Away attacks left).
    x, y = normalize_coordinates(-80, -10, 1, 'left', is_home_team=False)
    assert x == 80 and y == 10
    
    # 3. Home defends 'right' (attacks left): Home team shooting. Flip needed (Home attacks left).
    x, y = normalize_coordinates(-80, -10, 1, 'right', is_home_team=True)
    assert x == 80 and y == 10
    
    # 4. Home defends 'right' (attacks left): Away team shooting. No flip (Away attacks right).
    x, y = normalize_coordinates(80, 10, 1, 'right', is_home_team=False)
    assert x == 80 and y == 10
    
    # 5. Null coordinates check
    x, y = normalize_coordinates(None, None, 1, 'left', is_home_team=True)
    assert x is None and y is None

def test_shot_metrics_calculation():
    # Net is at (89, 0)
    # 1. Shot directly in front of the net at (89, 0)
    metrics = calculate_shot_metrics(89, 0)
    assert metrics["distance"] == 0.0
    assert metrics["angle"] == 0.0
    
    # 2. Shot from (89, 10) - 10 ft away on the goal line
    metrics = calculate_shot_metrics(89, 10)
    assert metrics["distance"] == 10.0
    assert metrics["angle"] == 90.0
    
    # 3. Shot from (59, 30) - 30 ft back, 30 ft offset (dx=30, dy=30)
    metrics = calculate_shot_metrics(59, 30)
    assert pytest.approx(metrics["distance"], 0.1) == 42.43
    assert pytest.approx(metrics["angle"], 0.1) == 45.0
    
    # 4. Null inputs
    metrics = calculate_shot_metrics(None, None)
    assert metrics["distance"] is None
    assert metrics["angle"] is None

def test_situation_code_parsing():
    # situationCode format: [Away Goalie, Away Skaters, Home Skaters, Home Goalie]
    
    # 1. Standard 5v5, goalie in net
    strength, empty = parse_situation_code("1551", is_home_team=True)
    assert strength == "5v5"
    assert not empty
    
    # 2. Home team Power Play (5v4), Away goalie in net (1 skaters: 4 away, 5 home)
    strength, empty = parse_situation_code("1451", is_home_team=True)
    assert strength == "5v4"
    assert not empty
    
    # 3. Home team attacking, Away goalie pulled (0 goalie status for Away)
    strength, empty = parse_situation_code("0551", is_home_team=True)
    assert strength == "5v5"
    assert empty
    
    # 4. Away team attacking (is_home=False), Home goalie pulled (0 goalie status for Home)
    strength, empty = parse_situation_code("1550", is_home_team=False)
    assert strength == "5v5"
    assert empty
    
    # 5. Invalid input
    strength, empty = parse_situation_code(None, is_home_team=True)
    assert strength == "5v5"
    assert not empty

def test_data_quality_checker():
    checker = IngestionValidator()
    
    # Check invalid coordinates warning
    invalid_event = Event(
        event_id="test_1",
        game_id=1,
        period=1,
        period_time="01:00",
        elapsed_game_seconds=60,
        event_type="Shot",
        x_coordinate=150.0,  # invalid X
        y_coordinate=20.0
    )
    
    # We should have warnings after validation
    checker.validate_event(invalid_event, known_player_ids=set(), known_team_ids=set())
    summary = checker.get_summary()
    assert summary["warnings_count"] > 0
    assert any("X Coordinate out of bounds" in w["message"] for w in summary["warnings"])
    
    # Check shift durations and overlaps
    checker_shift = IngestionValidator()
    shift1 = Shift(
        shift_id="shift_1",
        game_id=1,
        player_id=100,
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    shift2 = Shift(
        shift_id="shift_2",
        game_id=1,
        player_id=100,
        period=1,
        start_time="00:30",  # Overlaps with shift 1
        end_time="01:15",
        start_elapsed_seconds=30,
        end_elapsed_seconds=75,
        duration=45
    )
    
    checker_shift.validate_shifts([shift1, shift2])
    summary_shift = checker_shift.get_summary()
    assert any("Overlapping shifts found" in w["message"] for w in summary_shift["warnings"])

def test_database_loader_idempotency(app, db):
    loader = DatabaseLoader(db.session)
    
    # Create sample game records
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    player = Player(player_id=8476456, first_name='Jonathan', last_name='Huberdeau', position='L', current_team=cgy)
    
    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=3,
        away_score=2,
        game_status='Final'
    )
    
    event = Event(
        event_id="2023020007_1",
        game_id=game.game_id,
        period=1,
        period_time="01:00",
        elapsed_game_seconds=60,
        event_type="shot-on-goal",
        team_id=cgy.team_id,
        primary_player_id=player.player_id
    )
    
    shot = Shot(
        shot_id=event.event_id,
        shooter_id=player.player_id,
        x_coordinate=80.0,
        y_coordinate=10.0,
        distance=13.45,
        angle=47.73,
        outcome='Saved'
    )
    
    shift = Shift(
        shift_id="2023020007_8476456_1_0",
        game_id=game.game_id,
        player_id=player.player_id,
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    
    # First load
    success = loader.load_game_data(
        game, [cgy], [player], [event], [shot], [shift]
    )
    assert success
    
    # Assert records exist
    assert db.session.get(Game, 2023020007) is not None
    assert db.session.get(Event, "2023020007_1") is not None
    assert db.session.get(Shot, "2023020007_1") is not None
    assert db.session.get(Shift, "2023020007_8476456_1_0") is not None
    
    # Re-load (identical data) - should not cause duplicate PK errors or expand list
    # Construct new instances to match real-world pipeline reload scenario
    game_reload = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=3,
        away_score=2,
        game_status='Final'
    )
    
    event_reload = Event(
        event_id="2023020007_1",
        game_id=game_reload.game_id,
        period=1,
        period_time="01:00",
        elapsed_game_seconds=60,
        event_type="shot-on-goal",
        team_id=cgy.team_id,
        primary_player_id=player.player_id
    )
    
    shot_reload = Shot(
        shot_id=event_reload.event_id,
        shooter_id=player.player_id,
        x_coordinate=80.0,
        y_coordinate=10.0,
        distance=13.45,
        angle=47.73,
        outcome='Saved'
    )
    
    shift_reload = Shift(
        shift_id="2023020007_8476456_1_0",
        game_id=game_reload.game_id,
        player_id=player.player_id,
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    
    success_reload = loader.load_game_data(
        game_reload, [cgy], [player], [event_reload], [shot_reload], [shift_reload]
    )
    assert success_reload
    
    # Assert records still exist uniquely
    assert db.session.get(Game, 2023020007) is not None
    assert db.session.get(Event, "2023020007_1") is not None
