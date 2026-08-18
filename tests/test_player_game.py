import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, Shot
from app.services.game_service import GameService

def test_player_game_stats_and_routes(app, db, client):
    """
    Tests that GameService correctly calculates skater and goalie stats,
    and checks that HTML routes and JSON API endpoints function correctly.
    """
    # 1. Seed mock data
    # Create team
    team = Team(team_id=1, name="Test Team", abbreviation="TST")
    db.session.add(team)
    db.session.commit()
    
    # Create players (skater and goalie)
    skater = Player(player_id=10, first_name="John", last_name="Skater", position="C", current_team_id=1)
    goalie = Player(player_id=20, first_name="Marc", last_name="Goalie", position="G", current_team_id=1)
    db.session.add_all([skater, goalie])
    db.session.commit()
    
    # Create game
    game = Game(
        game_id=100,
        season="20232024",
        game_date=date(2023, 10, 10),
        game_type="R",
        home_team_id=1,
        away_team_id=1,
        home_score=3,
        away_score=2,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()
    
    # Create shifts
    s1 = Shift(shift_id="s1", game_id=100, player_id=10, period=1, start_time="00:00", end_time="00:45", start_elapsed_seconds=0, end_elapsed_seconds=45, duration=45)
    s2 = Shift(shift_id="s2", game_id=100, player_id=10, period=2, start_time="10:00", end_time="10:35", start_elapsed_seconds=1800, end_elapsed_seconds=1835, duration=35)
    sg = Shift(shift_id="sg", game_id=100, player_id=20, period=1, start_time="00:00", end_time="20:00", start_elapsed_seconds=0, end_elapsed_seconds=1200, duration=1200)
    db.session.add_all([s1, s2, sg])
    db.session.commit()
    
    # Create shot (skater takes it, goalie faces it)
    e1 = Event(event_id="e1", game_id=100, period=1, period_time="05:00", elapsed_game_seconds=300, event_type="shot-on-goal", team_id=1, primary_player_id=10)
    db.session.add(e1)
    db.session.commit()
    
    shot = Shot(shot_id="e1", game_id=100, team_id=1, shooter_id=10, goalie_id=20, x_coordinate=75.0, y_coordinate=-5.0, distance=15.0, angle=10.0, outcome="Saved", shot_type="wrist", goal=False)
    db.session.add(shot)
    db.session.commit()
    
    # 2. Test GameService skater calculations
    skater_stats = GameService.get_player_game_stats(100, 10)
    assert skater_stats is not None
    assert skater_stats["name"] == "John Skater"
    assert skater_stats["position"] == "C"
    assert skater_stats["toi"] == "01:20"  # 45s + 35s = 80s -> 01:20
    assert skater_stats["shifts_count"] == 2
    assert skater_stats["avg_shift"] == "00:40"
    assert skater_stats["shots"] == 1
    assert skater_stats["goals"] == 0
    assert len(skater_stats["shifts_chart"]) == 2
    
    # 3. Test GameService goalie calculations
    goalie_stats = GameService.get_player_game_stats(100, 20)
    assert goalie_stats is not None
    assert goalie_stats["name"] == "Marc Goalie"
    assert goalie_stats["position"] == "G"
    assert goalie_stats["toi"] == "20:00"
    assert goalie_stats["shots_faced"] == 1
    assert goalie_stats["saves"] == 1
    assert goalie_stats["save_pct"] == 100.0
    
    # 4. Test Game Roster output in overview stats
    overview = GameService.get_game_overview_stats(100)
    assert overview is not None
    assert "rosters" in overview
    assert len(overview["rosters"]["home_skaters"]) == 1
    assert overview["rosters"]["home_skaters"][0]["name"] == "John Skater"
    assert len(overview["rosters"]["home_goalies"]) == 1
    assert overview["rosters"]["home_goalies"][0]["name"] == "Marc Goalie"
    
    # 5. Test Web Page Route
    resp = client.get("/game/100/player/10")
    assert resp.status_code == 200
    assert b"John Skater" in resp.data
    assert b"Individual Shot Attempts" in resp.data
    
    # Test Web Page Goalie Route
    resp_g = client.get("/game/100/player/20")
    assert resp_g.status_code == 200
    assert b"Marc Goalie" in resp_g.data
    assert b"Shots Faced Map" in resp_g.data
    
    # 6. Test Shots API Endpoint
    resp_api = client.get("/api/game/100/player/10/shots")
    assert resp_api.status_code == 200
    shots_data = resp_api.get_json()
    assert len(shots_data) == 1
    assert shots_data[0]["shooter_name"] == "John Skater"
    assert shots_data[0]["goalie_name"] == "Marc Goalie"
    assert shots_data[0]["outcome"] == "Saved"
