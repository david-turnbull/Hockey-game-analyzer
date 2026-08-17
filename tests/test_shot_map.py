import pytest
from datetime import date
from app.models import Team, Player, Game, Event, Shot

def test_api_shots_endpoint(client, db):
    # 1. Setup mock teams
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    db.session.add(cgy)
    db.session.flush()

    # 2. Setup mock players
    huberdeau = Player(player_id=1, first_name='Jonathan', last_name='Huberdeau', position='LW', current_team=cgy)
    db.session.add(huberdeau)
    db.session.flush()

    # 3. Setup mock game
    game = Game(
        game_id=2023020007,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id,
        home_score=1,
        away_score=0,
        game_status='Final'
    )
    db.session.add(game)
    db.session.flush()

    # 4. Add Event and Shot
    e1 = Event(
        event_id="2023020007_1",
        game_id=game.game_id,
        period=1,
        period_time="05:00",
        elapsed_game_seconds=300,
        event_type="goal",
        team_id=cgy.team_id,
        primary_player_id=huberdeau.player_id,
        x_coordinate=75.0,  # raw coordinate
        y_coordinate=20.0,  # raw coordinate
        strength_state="5v5"
    )
    db.session.add(e1)
    db.session.flush()

    shot = Shot(
        shot_id=e1.event_id,
        shooter_id=huberdeau.player_id,
        x_coordinate=85.0,  # normalized coordinate
        y_coordinate=-15.0,  # normalized coordinate
        distance=15.0,
        angle=45.0,
        outcome="Goal",
        goal=True,
        shot_type="Wrist"
    )
    db.session.add(shot)
    db.session.commit()

    # 5. Test API fetch
    response = client.get('/api/shots?game_id=2023020007')
    assert response.status_code == 200
    
    data = response.json
    assert isinstance(data, list)
    assert len(data) == 1
    
    shot_item = data[0]
    assert shot_item["shot_id"] == "2023020007_1"
    assert shot_item["raw_x"] == 75.0
    assert shot_item["raw_y"] == 20.0
    assert shot_item["norm_x"] == 85.0
    assert shot_item["norm_y"] == -15.0
    assert shot_item["distance"] == 15.0
    assert shot_item["angle"] == 45.0
    assert shot_item["outcome"] == "Goal"
    assert shot_item["shot_type"] == "Wrist"
    assert shot_item["shooter_name"] == "Jonathan Huberdeau"
    assert shot_item["team_abbrev"] == "CGY"

    # Test error cases
    response_400_missing = client.get('/api/shots')
    assert response_400_missing.status_code == 400

    response_400_invalid = client.get('/api/shots?game_id=notanint')
    assert response_400_invalid.status_code == 400

    response_empty = client.get('/api/shots?game_id=999999')
    assert response_empty.status_code == 200
    assert response_empty.json == []
