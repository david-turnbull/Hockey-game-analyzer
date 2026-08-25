import pytest
from datetime import date
from app.models import Game, Team, Player, GamePlayer, Shift
from app.services.player_game_service import PlayerGameService
from app.services.game_service import GameService

def test_historical_player_team_attribution(app, db):
    """
    Verifies that querying game statistics resolves a player's team historical assignment
    correctly via the GamePlayer model, even if the player's current_team_id has changed
    to a different team in the meantime.
    """
    # 1. Seed Teams
    cgy = Team(team_id=1, name="Calgary Flames", abbreviation="CGY")
    van = Team(team_id=2, name="Vancouver Canucks", abbreviation="VAN")
    db.session.add_all([cgy, van])
    db.session.commit()

    # 2. Seed Game A (between Calgary and Vancouver)
    game_a = Game(
        game_id=1001,
        season="20232024",
        game_date=date(2023, 10, 10),
        game_type="R",
        home_team_id=1,  # CGY
        away_team_id=2,  # VAN
        home_score=3,
        away_score=2,
        game_status="Final"
    )
    db.session.add(game_a)
    db.session.commit()

    # 3. Seed Player 100 on Calgary (first team) for Game A
    # In real database, player's current_team_id gets updated to Vancouver (2) on trade
    player = Player(
        player_id=100,
        first_name="Elias",
        last_name="Lindholm",
        position="C",
        shoots_catches="R",
        current_team_id=2  # Now Lindholm is on Vancouver (current_team_id=2)
    )
    db.session.add(player)
    db.session.commit()

    # 4. Seed the authoritative GamePlayer record (Lindholm played for CGY in Game A)
    gp = GamePlayer(
        game_id=1001,
        player_id=100,
        team_id=1,  # CGY
        position="C"
    )
    db.session.add(gp)
    db.session.commit()

    # 5. Seed a shift for Lindholm in Game A
    shift = Shift(
        shift_id="shift_lindholm_1",
        game_id=1001,
        player_id=100,
        team_id=1,
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    db.session.add(shift)
    db.session.commit()

    # 6. Verify PlayerGameService.get_player_game_stats resolves team_id to CGY (1), not VAN (2)
    stats = PlayerGameService.get_player_game_stats(1001, 100)
    assert stats is not None
    assert stats["team_id"] == 1  # Authoritative for this game
    assert stats["is_home"] is True  # Since home team is CGY (1)

    # 7. Check GameService overview rosters resolves Lindholm under home team (CGY)
    overview = GameService.get_game_overview_stats(1001)
    assert overview is not None
    home_skaters = [p["player_id"] for p in overview["rosters"]["home_skaters"]]
    away_skaters = [p["player_id"] for p in overview["rosters"]["away_skaters"]]
    assert 100 in home_skaters
    assert 100 not in away_skaters

def test_game_player_loader_idempotence(app, db):
    """
    Verifies that loading the same game data twice does not create duplicate GamePlayer rows.
    """
    from data_pipeline.loaders.db_loader import DatabaseLoader
    from app.models import GamePlayer
    
    loader = DatabaseLoader()
    
    # Create test models
    game = Game(game_id=2001, season="20232024", game_date=date(2023, 10, 12), game_type="R", home_team_id=1, away_team_id=2)
    # Seed teams first
    team1 = Team(team_id=1, name="Team 1", abbreviation="TM1")
    team2 = Team(team_id=2, name="Team 2", abbreviation="TM2")
    db.session.add_all([team1, team2])
    db.session.commit()
    
    player = Player(player_id=150, first_name="Test", last_name="Player", position="D", current_team_id=1)
    db.session.add(player)
    db.session.commit()
    
    # Define GamePlayer records
    gp = GamePlayer(game_id=2001, player_id=150, team_id=1, position="D")
    
    # Load first time
    success1 = loader.load_game_data(
        game,
        teams=[team1, team2],
        players=[player],
        game_players=[gp],
        events=[],
        shots=[],
        shifts=[]
    )
    assert success1 is True
    assert GamePlayer.query.filter_by(game_id=2001, player_id=150).count() == 1
    
    # Load second time (same objects/data)
    gp2 = GamePlayer(game_id=2001, player_id=150, team_id=1, position="D")
    success2 = loader.load_game_data(
        game,
        teams=[team1, team2],
        players=[player],
        game_players=[gp2],
        events=[],
        shots=[],
        shifts=[]
    )
    assert success2 is True
    assert GamePlayer.query.filter_by(game_id=2001, player_id=150).count() == 1  # Should still be 1 (idempotent!)
