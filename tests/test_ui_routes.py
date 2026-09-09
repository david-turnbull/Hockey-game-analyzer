import pytest
from datetime import date
from app.models import db as _db, Team, Player, Game, Event, Shot, Shift, GamePlayer

@pytest.fixture
def setup_ui_data(app, db):
    """Sets up deterministic season test data for UI route testing."""
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    skater = Player(player_id=10, first_name='Mikael', last_name='Backlund', position='C', sweater_number=11)
    goalie = Player(player_id=25, first_name='Jacob', last_name='Markstrom', position='G', sweater_number=25)
    db.session.add_all([cgy, edm, skater, goalie])
    db.session.commit()

    g = Game(
        game_id=2024020901, season='20242025', game_date=date(2024, 10, 15),
        game_type='R', home_team_id=1, away_team_id=2, home_score=3, away_score=2,
        nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    gp_s = GamePlayer(game_id=g.game_id, player_id=10, team_id=1, position='C', sweater_number=11)
    gp_g = GamePlayer(game_id=g.game_id, player_id=25, team_id=1, position='G', sweater_number=25)
    shift_s = Shift(shift_id='s10', game_id=g.game_id, player_id=10, period=1, start_time='00:00',
                    end_time='10:00', start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600, team_id=1)
    shift_g = Shift(shift_id='s25', game_id=g.game_id, player_id=25, period=1, start_time='00:00',
                    end_time='20:00', start_elapsed_seconds=0, end_elapsed_seconds=3600, duration=3600, team_id=1)

    ev_g = Event(event_id='e_goal', game_id=g.game_id, period=1, period_time='05:00',
                 period_type='REG', event_type='goal', team_id=1, primary_player_id=10)
    shot_g = Shot(shot_id='e_goal', game_id=g.game_id, shooter_id=10, goalie_id=25, team_id=1,
                  outcome='Goal', xg=0.35, goal=True)

    db.session.add_all([gp_s, gp_g, shift_s, shift_g, ev_g, shot_g])
    db.session.commit()
    return {"season": "20242025", "team_id": 1, "skater_id": 10, "goalie_id": 25}

def test_season_redirect(client, setup_ui_data):
    res = client.get('/season')
    assert res.status_code == 302
    assert '/season/20242025' in res.headers['Location']

def test_season_overview(client, setup_ui_data):
    res = client.get('/season/20242025')
    assert res.status_code == 200
    assert b"NHL Season Analytics" in res.data
    assert b"Team Analytical Standings" in res.data
    assert b"Calgary Flames" in res.data

def test_season_overview_situation_filter(client, setup_ui_data):
    res = client.get('/season/20242025?situation=5v5')
    assert res.status_code == 200
    assert b"5v5" in res.data

def test_team_season_view(client, setup_ui_data):
    res = client.get('/team/1/season/20242025')
    assert res.status_code == 200
    assert b"Calgary Flames" in res.data
    assert b"Season Dashboard" in res.data
    assert b"Rolling Form" in res.data

def test_team_season_not_found(client, setup_ui_data):
    res = client.get('/team/9999999/season/20242025')
    assert res.status_code == 404

def test_skater_season_view(client, setup_ui_data):
    res = client.get('/player/10/season/20242025')
    assert res.status_code == 200
    assert b"Mikael Backlund" in res.data
    assert b"Season Profile" in res.data
    assert b"5v5 Even-Strength On-Ice Possession Profile" in res.data

def test_goalie_season_view(client, setup_ui_data):
    res = client.get('/goalie/25/season/20242025')
    assert res.status_code == 200
    assert b"Jacob Markstrom" in res.data
    assert b"Goalie Profile" in res.data
    assert b"Goals Saved Above Exp" in res.data

def test_skater_goalie_cross_redirects(client, setup_ui_data):
    # Skater route called on goalie (id 25) -> redirects to goalie route
    res = client.get('/player/25/season/20242025')
    assert res.status_code == 302
    assert '/goalie/25/season/20242025' in res.headers['Location']

    # Goalie route called on skater (id 10) -> redirects to player route
    res = client.get('/goalie/10/season/20242025')
    assert res.status_code == 302
    assert '/player/10/season/20242025' in res.headers['Location']
