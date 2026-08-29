import pytest
from unittest.mock import patch
from app.models import Team, Player, Game, Shift, GamePlayer
from datetime import date

def test_schedule_api_endpoint(client, db):
    """
    Verifies that the /api/schedule endpoint fetches the team's official season schedule,
    correctly flags which games are already ingested, and parses scores.
    """
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=21, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.flush()

    # Ingest a mock game in the database
    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=20,
        away_team_id=21,
        home_score=5,
        away_score=3,
        game_status='Final'
    )
    db.session.add(game)
    db.session.commit()

    mock_schedule = {
        "games": [
            {
                "id": 2023020007,
                "gameDate": "2023-10-11",
                "gameType": 2,
                "gameState": "FINAL",
                "homeTeam": {"abbrev": "CGY", "score": 5},
                "awayTeam": {"abbrev": "WPG", "score": 3}
            },
            {
                "id": 2023020025,
                "gameDate": "2023-10-14",
                "gameType": 2,
                "gameState": "FINAL",
                "homeTeam": {"abbrev": "PIT", "score": 5},
                "awayTeam": {"abbrev": "CGY", "score": 2}
            },
            {
                "id": 2023020039,
                "gameDate": "2023-10-16",
                "gameType": 2,
                "gameState": "FUT",
                "homeTeam": {"abbrev": "WSH", "score": 0},
                "awayTeam": {"abbrev": "CGY", "score": 0}
            }
        ]
    }

    with patch('data_pipeline.ingest.nhl_api.NHLApiClient.get_season_schedule', return_value=mock_schedule):
        res = client.get('/api/schedule?team_id=20&season=20232024')
        assert res.status_code == 200
        data = res.get_json()
        assert len(data) == 3
        
        # Verify first game (ingested)
        assert data[0]["game_id"] == 2023020007
        assert data[0]["is_ingested"] is True
        assert data[0]["opponent_abbrev"] == "WPG"
        assert data[0]["home_score"] == 5
        assert data[0]["away_score"] == 3
        
        # Verify second game (not ingested)
        assert data[1]["game_id"] == 2023020025
        assert data[1]["is_ingested"] is False
        assert data[1]["game_status"] == "FINAL"
        
        # Verify third game (future)
        assert data[2]["game_id"] == 2023020039
        assert data[2]["is_ingested"] is False
        assert data[2]["game_status"] == "FUT"


def test_on_ice_players_api_endpoint(client, db):
    """
    Verifies that the /api/game/<game_id>/on-ice endpoint returns overlapping shifts,
    strictly enforces the boundary rules, and formats details properly.
    """
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=21, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.flush()

    # Home and Away players
    p1 = Player(player_id=1, first_name='Mikael', last_name='Backlund', position='C', sweater_number=11, current_team=cgy)
    p2 = Player(player_id=2, first_name='Nazem', last_name='Kadri', position='C', sweater_number=91, current_team=cgy)
    p3 = Player(player_id=3, first_name='Mark', last_name='Scheifele', position='C', sweater_number=55, current_team=wpg)
    db.session.add_all([p1, p2, p3])
    db.session.flush()

    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=20,
        away_team_id=21,
        home_score=5,
        away_score=3,
        game_status='Final'
    )
    db.session.add(game)
    db.session.flush()

    # Shift 1 (Backlund): 0s to 60s
    s1 = Shift(
        shift_id="2023020007_1_1_0",
        game_id=2023020007,
        player_id=1,
        team_id=20,
        period=1,
        start_time="00:00",
        end_time="01:00",
        start_elapsed_seconds=0,
        end_elapsed_seconds=60,
        duration=60,
        is_anomaly=False
    )
    # Shift 2 (Kadri): 60s to 120s
    s2 = Shift(
        shift_id="2023020007_2_1_60",
        game_id=2023020007,
        player_id=2,
        team_id=20,
        period=1,
        start_time="01:00",
        end_time="02:00",
        start_elapsed_seconds=60,
        end_elapsed_seconds=120,
        duration=60,
        is_anomaly=False
    )
    # Shift 3 (Scheifele): 30s to 90s
    s3 = Shift(
        shift_id="2023020007_3_1_30",
        game_id=2023020007,
        player_id=3,
        team_id=21,
        period=1,
        start_time="00:30",
        end_time="01:30",
        start_elapsed_seconds=30,
        end_elapsed_seconds=90,
        duration=60,
        is_anomaly=False
    )
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # Query exactly at 60 seconds (01:00)
    # Boundary rule checks:
    # Nazem Kadri (starts at 60s) -> INCLUDED
    # Mikael Backlund (ends at 60s) -> EXCLUDED
    # Mark Scheifele (30s to 90s) -> INCLUDED
    res = client.get('/api/game/2023020007/on-ice?period=1&time=01:00')
    assert res.status_code == 200
    data = res.get_json()

    # Verify home team (Calgary)
    home_players = data["home"]
    assert len(home_players) == 1
    assert home_players[0]["player_id"] == 2 # Nazem Kadri is included
    assert home_players[0]["name"] == "Nazem Kadri"

    # Verify away team (Winnipeg)
    away_players = data["away"]
    assert len(away_players) == 1
    assert away_players[0]["player_id"] == 3 # Mark Scheifele is included


def test_on_demand_ingestion_api_endpoint(client, db):
    """
    Verifies that POST /api/game/<game_id>/ingest triggers the pipeline orchestrator,
    saves the imported game, and commits successfully.
    """
    with patch('data_pipeline.orchestrator.PipelineOrchestrator.ingest_game', return_value=(True, {"game_id": 2023020025})) as mock_ingest:
        res = client.post('/api/game/2023020025/ingest')
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["summary"]["game_id"] == 2023020025
        mock_ingest.assert_called_once_with(2023020025)
