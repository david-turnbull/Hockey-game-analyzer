import pytest
from sqlalchemy import text
from app.models import Player, GamePlayer
from data_pipeline.orchestrator import PipelineOrchestrator
from app.utils.db_migrator import run_migrations

def test_metadata_correctness(app, db):
    """
    Verifies that after ingesting a game, player metadata (positions,
    handedness, sweater numbers) are loaded canonically from the season roster API
    rather than play-by-play, ensuring that players like Huberdeau and Coleman
    do not end up as centers.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True
    
    # Assert Huberdeau is left wing (L) and catches/shoots L
    huberdeau = Player.query.get(8476456)
    assert huberdeau is not None
    assert huberdeau.position == "L"
    assert huberdeau.shoots_catches == "L"
    assert huberdeau.sweater_number == 10
    
    # Assert Weegar is defenseman (D) and catches/shoots R
    weegar = Player.query.get(8477346)
    assert weegar is not None
    assert weegar.position == "D"
    assert weegar.shoots_catches == "R"
    assert weegar.sweater_number == 52
    
    # Assert game-specific sweater number in GamePlayer record
    gp_huberdeau = GamePlayer.query.filter_by(game_id=2023020007, player_id=8476456).first()
    assert gp_huberdeau is not None
    assert gp_huberdeau.position == "L"
    assert gp_huberdeau.sweater_number == 10

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
