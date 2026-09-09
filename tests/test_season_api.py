import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer

@pytest.fixture
def setup_season_data(app, db):
    """Sets up deterministic season test data for API testing."""
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    skater = Player(player_id=10, first_name='Mikael', last_name='Backlund', position='C')
    goalie = Player(player_id=25, first_name='Jacob', last_name='Markstrom', position='G')
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
                 event_type='goal', team_id=1, primary_player_id=10)
    sh_g = Shot(shot_id='e_goal', game_id=g.game_id, team_id=1, shooter_id=10, goalie_id=25,
                outcome='Goal', goal=True, xg=0.35, empty_net=False)

    db.session.add_all([gp_s, gp_g, shift_s, shift_g, ev_g, sh_g])
    db.session.commit()
    return {"season": "20242025", "team_id": 1, "skater_id": 10, "goalie_id": 25}


def test_api_seasons(client, setup_season_data):
    res = client.get('/api/seasons')
    assert res.status_code == 200
    data = res.get_json()
    assert "seasons" in data
    assert "20242025" in data["seasons"]


def test_api_season_teams(client, setup_season_data):
    season = setup_season_data["season"]
    res = client.get(f'/api/seasons/{season}/teams')
    assert res.status_code == 200
    data = res.get_json()
    assert data["season"] == season
    assert len(data["teams"]) > 0
    cgy = next(t for t in data["teams"] if t["team_id"] == 1)
    assert cgy["team_abbrev"] == "CGY"
    assert cgy["gf"] == 1


def test_api_team_season(client, setup_season_data):
    season = setup_season_data["season"]
    team_id = setup_season_data["team_id"]
    res = client.get(f'/api/teams/{team_id}/season/{season}')
    assert res.status_code == 200
    data = res.get_json()
    assert data["team_id"] == team_id
    assert "xgf" in data
    assert "cf" in data

    # 404 for invalid team
    res404 = client.get(f'/api/teams/9999/season/{season}')
    assert res404.status_code == 404


def test_api_team_season_trends(client, setup_season_data):
    season = setup_season_data["season"]
    team_id = setup_season_data["team_id"]
    res = client.get(f'/api/teams/{team_id}/season/{season}/trends?windows=5,10')
    assert res.status_code == 200
    data = res.get_json()
    assert "windows" in data
    assert "5" in data["windows"]


def test_api_team_season_rosters(client, setup_season_data):
    season = setup_season_data["season"]
    team_id = setup_season_data["team_id"]

    res_p = client.get(f'/api/teams/{team_id}/season/{season}/players')
    assert res_p.status_code == 200
    assert len(res_p.get_json()["players"]) >= 1

    res_g = client.get(f'/api/teams/{team_id}/season/{season}/goalies')
    assert res_g.status_code == 200
    assert len(res_g.get_json()["goalies"]) >= 1


def test_api_player_and_goalie_season(client, setup_season_data):
    season = setup_season_data["season"]
    skater_id = setup_season_data["skater_id"]
    goalie_id = setup_season_data["goalie_id"]

    res_p = client.get(f'/api/players/{skater_id}/season/{season}?include_trends=true')
    assert res_p.status_code == 200
    data_p = res_p.get_json()
    assert data_p["player_id"] == skater_id
    assert "goals" in data_p
    assert "xg" in data_p

    res_g = client.get(f'/api/goalies/{goalie_id}/season/{season}?include_trends=true')
    assert res_g.status_code == 200
    data_g = res_g.get_json()
    assert data_g["player_id"] == goalie_id
    assert "gsax" in data_g


def test_api_season_leaders(client, setup_season_data):
    season = setup_season_data["season"]

    res_p = client.get(f'/api/seasons/{season}/leaders?category=skaters&metric=goals')
    assert res_p.status_code == 200
    data_p = res_p.get_json()
    assert data_p["metric"] == "goals"
    assert len(data_p["leaders"]) > 0

    res_g = client.get(f'/api/seasons/{season}/leaders?category=goalies&metric=gsax')
    assert res_g.status_code == 200
    data_g = res_g.get_json()
    assert data_g["metric"] == "gsax"
    assert len(data_g["leaders"]) > 0
