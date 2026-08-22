import pytest
from datetime import date
from app.models import Team, Game
from app.services.game_service import GameService

def test_game_service_queries(app, db):
    # Setup test team
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=52, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.commit()
    
    # Setup test game
    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=wpg.team_id,
        home_score=3,
        away_score=5,
        game_status='Final'
    )
    db.session.add(game)
    db.session.commit()
    
    # Test seasons query
    seasons = GameService.get_available_seasons()
    assert seasons == ['20232024']
    
    # Test teams query
    teams = GameService.get_available_teams()
    assert len(teams) == 2
    assert teams[0].name == 'Calgary Flames'
    
    # Test games list query (Calgary as focal team)
    cgy_games = GameService.get_games_list(cgy.team_id, '20232024')
    assert len(cgy_games) == 1
    cgy_game = cgy_games[0]
    assert cgy_game["game_id"] == 2023020007
    assert cgy_game["opponent_abbrev"] == 'WPG'
    assert cgy_game["home_team_abbrev"] == 'CGY'
    assert cgy_game["away_team_abbrev"] == 'WPG'
    assert cgy_game["is_home"] is True
    assert cgy_game["home_score"] == 3
    assert cgy_game["away_score"] == 5

def test_api_games_endpoint(client, db):
    # Seed mock data
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=52, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.flush()
    
    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=wpg.team_id,
        home_score=3,
        away_score=5,
        game_status='Final'
    )
    db.session.add(game)
    db.session.commit()

    # 1. Successful request
    response = client.get('/api/games?team_id=20&season=20232024')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 1
    assert data[0]["game_id"] == 2023020007
    assert data[0]["opponent_abbrev"] == 'WPG'
    
    # 2. Missing params
    response_missing = client.get('/api/games?team_id=20')
    assert response_missing.status_code == 400
    
    # 3. Invalid team id format
    response_invalid = client.get('/api/games?team_id=invalid&season=20232024')
    assert response_invalid.status_code == 400

def test_routing_views(client, db):
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    db.session.add(cgy)
    db.session.flush()

    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=3,
        away_score=3,
        game_status='Final'
    )
    db.session.add(game)
    db.session.commit()

    # Test selector homepage loads
    response_home = client.get('/')
    assert response_home.status_code == 200
    assert b"Game Selection Dashboard" in response_home.data
