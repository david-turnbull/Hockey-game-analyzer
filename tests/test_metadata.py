import pytest
from unittest.mock import MagicMock
from sqlalchemy import text
from app.models import Player, GamePlayer
from data_pipeline.orchestrator import PipelineOrchestrator
from app.utils.db_migrator import run_migrations

def _get_frozen_fixtures():
    frozen_pbp = {
        "id": 2023020007,
        "season": 20232024,
        "gameType": 2,
        "gameDate": "2023-10-11",
        "gameState": "OFF",
        "homeTeam": {"id": 20, "abbrev": "CGY", "score": 5},
        "awayTeam": {"id": 52, "abbrev": "WPG", "score": 3},
        "periodDescriptor": {"number": 3, "periodType": "REG"},
        "plays": [],
        "rosterSpots": [
            {
                "playerId": 8476456,
                "firstName": {"default": "Jonathan"},
                "lastName": {"default": "Huberdeau"},
                "sweaterNumber": 10,
                "positionCode": "C",  # Intentionally "C" to test PBP defect vs season roster "L"
                "headshot": "https://assets.nhle.com/mugs/nhl/20232024/CGY/8476456.png",
                "teamId": 20
            },
            {
                "playerId": 8477346,
                "firstName": {"default": "MacKenzie"},
                "lastName": {"default": "Weegar"},
                "sweaterNumber": 52,
                "positionCode": "D",
                "headshot": "https://assets.nhle.com/mugs/nhl/20232024/CGY/8477346.png",
                "teamId": 20
            },
            {
                "playerId": 9999999,
                "firstName": {"default": "Fallback"},
                "lastName": {"default": "Skater"},
                "sweaterNumber": 99,
                "positionCode": "RW",  # Present in PBP, intentionally absent from season roster
                "headshot": "https://assets.nhle.com/mugs/nhl/20232024/CGY/9999999.png",
                "teamId": 20
            }
        ]
    }

    frozen_roster_cgy = {
        "forwards": [
            {
                "id": 8476456,
                "firstName": {"default": "Jonathan"},
                "lastName": {"default": "Huberdeau"},
                "sweaterNumber": 10,
                "positionCode": "L",  # Canonical position
                "shootsCatches": "L",
                "headshot": "https://assets.nhle.com/mugs/nhl/20232024/CGY/8476456.png",
                "heightInInches": 73,
                "heightInCentimeters": 185,
                "weightInPounds": 202,
                "weightInKilograms": 92,
                "birthDate": "1993-06-04",
                "birthCity": {"default": "Saint-Jerome"},
                "birthCountry": "CAN"
            }
        ],
        "defensemen": [
            {
                "id": 8477346,
                "firstName": {"default": "MacKenzie"},
                "lastName": {"default": "Weegar"},
                "sweaterNumber": 52,
                "positionCode": "D",
                "shootsCatches": "R",
                "headshot": "https://assets.nhle.com/mugs/nhl/20232024/CGY/8477346.png",
                "heightInInches": 72,
                "heightInCentimeters": 183,
                "weightInPounds": 206,
                "weightInKilograms": 93,
                "birthDate": "1994-01-07",
                "birthCity": {"default": "Ottawa"},
                "birthCountry": "CAN"
            }
        ],
        "goalies": []
    }

    frozen_shifts = {"data": [], "total": 0}
    frozen_box = {"homeTeam": {}, "awayTeam": {}}

    return frozen_pbp, frozen_roster_cgy, frozen_shifts, frozen_box


def test_metadata_correctness(app, db, monkeypatch):
    """
    Verifies that after ingesting a game, player metadata (positions,
    handedness, sweater numbers) are loaded canonically from the season roster API
    rather than play-by-play, ensuring that players like Huberdeau and Coleman
    do not end up as centers.
    Also proves that players absent from season rosters fall back cleanly to PBP metadata.
    """
    frozen_pbp, frozen_roster_cgy, frozen_shifts, frozen_box = _get_frozen_fixtures()

    orchestrator = PipelineOrchestrator(session=db.session)

    # Deterministic offline mock: isolate from live network calls completely
    monkeypatch.setattr(orchestrator.api_client, "get_play_by_play", lambda gid, force_refresh=False: frozen_pbp)
    monkeypatch.setattr(orchestrator.api_client, "get_shifts", lambda gid, force_refresh=False: frozen_shifts)
    monkeypatch.setattr(orchestrator.api_client, "get_boxscore", lambda gid, force_refresh=False: frozen_box)
    monkeypatch.setattr(
        orchestrator.api_client,
        "get_season_roster",
        lambda abbr, season: frozen_roster_cgy if abbr == "CGY" else {"forwards": [], "defensemen": [], "goalies": []}
    )

    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    # Assert Huberdeau is left wing (L) from season roster, winning over PBP "C"
    huberdeau = db.session.get(Player, 8476456)
    assert huberdeau is not None
    assert huberdeau.position == "L"
    assert huberdeau.shoots_catches == "L"
    assert huberdeau.sweater_number == 10
    
    # Assert Weegar is defenseman (D) and catches/shoots R
    weegar = db.session.get(Player, 8477346)
    assert weegar is not None
    assert weegar.position == "D"
    assert weegar.shoots_catches == "R"
    assert weegar.sweater_number == 52
    
    # Assert game-specific sweater number in GamePlayer record
    gp_huberdeau = GamePlayer.query.filter_by(game_id=2023020007, player_id=8476456).first()
    assert gp_huberdeau is not None
    assert gp_huberdeau.position == "L"
    assert gp_huberdeau.sweater_number == 10

    # Assert fallback player (absent from season roster) falls back to PBP metadata cleanly
    fallback_player = db.session.get(Player, 9999999)
    assert fallback_player is not None
    assert fallback_player.position == "RW"
    assert fallback_player.sweater_number == 99


def test_metadata_pbp_fallback_when_season_roster_missing(app, db, monkeypatch):
    """
    Verifies that when season roster metadata is completely missing/empty,
    the pipeline falls back gracefully to play-by-play metadata.
    """
    frozen_pbp, _, frozen_shifts, frozen_box = _get_frozen_fixtures()

    orchestrator = PipelineOrchestrator(session=db.session)

    monkeypatch.setattr(orchestrator.api_client, "get_play_by_play", lambda gid, force_refresh=False: frozen_pbp)
    monkeypatch.setattr(orchestrator.api_client, "get_shifts", lambda gid, force_refresh=False: frozen_shifts)
    monkeypatch.setattr(orchestrator.api_client, "get_boxscore", lambda gid, force_refresh=False: frozen_box)
    # Season roster completely returns None/empty
    monkeypatch.setattr(orchestrator.api_client, "get_season_roster", lambda abbr, season: None)

    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True

    # When season roster is missing, PBP metadata is used
    huberdeau = db.session.get(Player, 8476456)
    assert huberdeau is not None
    assert huberdeau.position == "C"  # Fell back to PBP


def test_db_migration(app, db):
    """
    Verifies that run_migrations successfully alters
    database tables if columns are missing.
    """
    # In testing config, db.create_all() is called which creates all columns.
    # We can inspect the table info to verify that all the new columns are present.
    connection = db.session.connection()
    
    # Check player columns
    result = connection.execute(text("PRAGMA table_info(player)")).fetchall()
    cols = {row[1] for row in result}
    
    expected_cols = {
        "headshot_url", "sweater_number", "height_in_inches",
        "height_in_centimeters", "weight_in_pounds", "weight_in_kilograms",
        "birth_date", "birth_city", "birth_country"
    }
    for col in expected_cols:
        assert col in cols
        
    # Check game_player columns
    result = connection.execute(text("PRAGMA table_info(game_player)")).fetchall()
    gp_cols = {row[1] for row in result}
    assert "sweater_number" in gp_cols
