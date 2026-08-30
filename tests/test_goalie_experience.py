import pytest
from app.models import Team, Player, Game, GamePlayer, Event, Shot
from app.services.player_game_service import PlayerGameService
from datetime import date

def test_rich_player_profile_metadata(app, db):
    """
    Verifies that get_player_game_stats correctly parses and formats 
    extended player biographical metadata (sweater number, height, weight, birth city/country/date).
    """
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    db.session.add(cgy)
    db.session.flush()

    player = Player(
        player_id=101,
        first_name='Connor',
        last_name='Hellebuyck',
        position='G',
        shoots_catches='L',
        headshot_url='http://headshot.url',
        sweater_number=37,
        height_in_inches=76,  # 6'4"
        weight_in_pounds=207,
        birth_date=date(1993, 5, 19),
        birth_city='Commerce',
        birth_country='USA',
        current_team=cgy
    )
    db.session.add(player)
    db.session.flush()

    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=2,
        away_score=1,
        game_status='Final'
    )
    db.session.add(game)
    db.session.flush()

    # Add GamePlayer to assert sweater number resolution
    gp = GamePlayer(game_id=game.game_id, player_id=player.player_id, team_id=cgy.team_id, position='G', sweater_number=37)
    db.session.add(gp)
    db.session.commit()

    stats = PlayerGameService.get_player_game_stats(game.game_id, player.player_id)
    assert stats is not None
    assert stats["name"] == "Connor Hellebuyck"
    assert stats["headshot_url"] == "http://headshot.url"
    assert stats["sweater_number"] == 37
    assert stats["height_str"] == "6'4\""
    assert stats["weight_str"] == "207 lb"
    assert str(stats["birth_date"]) == "1993-05-19"
    assert stats["birth_city"] == "Commerce"
    assert stats["birth_country"] == "USA"

def test_goalie_situation_splits_calculation(app, db):
    """
    Verifies that get_player_game_stats calculates goalie 5v5 splits,
    power play shots faced, and goals by strength splits.
    """
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=52, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.flush()

    goalie = Player(player_id=5, first_name='Connor', last_name='Hellebuyck', position='G', current_team=wpg)
    shooter = Player(player_id=1, first_name='Jonathan', last_name='Huberdeau', position='LW', current_team=cgy)
    db.session.add_all([goalie, shooter])
    db.session.flush()

    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=wpg.team_id,
        home_score=2,
        away_score=1,
        game_status='Final'
    )
    db.session.add(game)
    db.session.flush()

    # 1. 5v5 Even Strength: 2 Shots Faced (1 Goal, 1 Save)
    e1 = Event(event_id="e1", game_id=game.game_id, period=1, period_time="01:00", elapsed_game_seconds=60, event_type="goal", team_id=cgy.team_id, primary_player_id=shooter.player_id, secondary_player_id=goalie.player_id, strength_state="5v5", team_strength_state="5v5", manpower_state="EV")
    s1 = Shot(shot_id="e1", x_coordinate=80.0, y_coordinate=5.0, distance=15.0, angle=10.0, outcome="Goal", goal=True, shooter_id=shooter.player_id, goalie_id=goalie.player_id, strength_state="5v5")
    
    e2 = Event(event_id="e2", game_id=game.game_id, period=1, period_time="02:00", elapsed_game_seconds=120, event_type="shot-on-goal", team_id=cgy.team_id, primary_player_id=shooter.player_id, secondary_player_id=goalie.player_id, strength_state="5v5", team_strength_state="5v5", manpower_state="EV")
    s2 = Shot(shot_id="e2", x_coordinate=82.0, y_coordinate=0.0, distance=10.0, angle=0.0, outcome="Saved", goal=False, shooter_id=shooter.player_id, goalie_id=goalie.player_id, strength_state="5v5")
    
    # 2. Power Play: 1 Shot Faced (1 Goal Allowed, manpower_state == 'PP')
    e3 = Event(event_id="e3", game_id=game.game_id, period=2, period_time="10:00", elapsed_game_seconds=1800, event_type="goal", team_id=cgy.team_id, primary_player_id=shooter.player_id, secondary_player_id=goalie.player_id, strength_state="5v4", team_strength_state="5v4", manpower_state="PP")
    s3 = Shot(shot_id="e3", x_coordinate=75.0, y_coordinate=12.0, distance=22.0, angle=25.0, outcome="Goal", goal=True, shooter_id=shooter.player_id, goalie_id=goalie.player_id, strength_state="5v4")

    # 3. Penalty Kill: 1 Shot Faced (1 Save, manpower_state == 'PK')
    e4 = Event(event_id="e4", game_id=game.game_id, period=3, period_time="05:00", elapsed_game_seconds=2700, event_type="shot-on-goal", team_id=cgy.team_id, primary_player_id=shooter.player_id, secondary_player_id=goalie.player_id, strength_state="4v5", team_strength_state="4v5", manpower_state="PK")
    s4 = Shot(shot_id="e4", x_coordinate=85.0, y_coordinate=-2.0, distance=8.0, angle=-5.0, outcome="Saved", goal=False, shooter_id=shooter.player_id, goalie_id=goalie.player_id, strength_state="4v5")

    db.session.add_all([e1, s1, e2, s2, e3, s3, e4, s4])
    db.session.commit()

    stats = PlayerGameService.get_player_game_stats(game.game_id, goalie.player_id)
    assert stats is not None
    assert stats["shots_faced"] == 4
    assert stats["goals_against"] == 2
    assert stats["saves"] == 2
    assert stats["save_pct"] == 50.0

    # Splits assertions
    assert stats["shots_faced_5v5"] == 2
    assert stats["saves_5v5"] == 1
    assert stats["save_pct_5v5"] == 50.0
    assert stats["shots_faced_pp"] == 1
    assert stats["goals_by_strength"]["EV"] == 1
    assert stats["goals_by_strength"]["PP"] == 1
    assert stats["goals_by_strength"]["PK"] == 0

def test_api_player_shots_manpower_state(client, app, db):
    """
    Asserts that the /api/game/<game_id>/player/<player_id>/shots endpoint 
    successfully returns the manpower_state field.
    """
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    db.session.add(cgy)
    db.session.flush()

    player = Player(player_id=1, first_name='Jonathan', last_name='Huberdeau', position='LW', current_team=cgy)
    db.session.add(player)
    db.session.flush()

    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=2,
        away_score=1,
        game_status='Final'
    )
    db.session.add(game)
    db.session.flush()

    e1 = Event(event_id="e1", game_id=game.game_id, period=1, period_time="01:00", elapsed_game_seconds=60, event_type="goal", team_id=cgy.team_id, primary_player_id=player.player_id, strength_state="5v5", team_strength_state="5v5", manpower_state="EV")
    s1 = Shot(shot_id="e1", x_coordinate=80.0, y_coordinate=5.0, distance=15.0, angle=10.0, outcome="Goal", goal=True, shooter_id=player.player_id, strength_state="5v5")
    db.session.add_all([e1, s1])
    db.session.commit()

    res = client.get(f"/api/game/{game.game_id}/player/{player.player_id}/shots")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data) == 1
    assert data[0]["manpower_state"] == "EV"
