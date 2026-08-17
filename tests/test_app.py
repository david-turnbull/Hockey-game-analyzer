from app.models import Team, Player, Game, Event, Shot, Shift
from datetime import date

def test_index_route(client):
    """Test that the game selector homepage loads successfully."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Game Selection Dashboard" in response.data

    response_diag = client.get('/diagnostics')
    assert response_diag.status_code == 200
    assert b"Platform Diagnostics" in response_diag.data
    assert b"Flask Application Info" in response_diag.data

def test_database_models_and_relationships(app, db):
    """Test creating records and checking relationships across all tables."""
    # 1. Create a Team
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    db.session.add(cgy)
    db.session.commit()
    
    retrieved_team = Team.query.filter_by(abbreviation='CGY').first()
    assert retrieved_team is not None
    assert retrieved_team.name == 'Calgary Flames'
    
    # 2. Create a Player and link to Team
    player = Player(
        player_id=8476458,
        first_name='Jonathan',
        last_name='Huberdeau',
        position='LW',
        shoots_catches='L',
        current_team=cgy
    )
    db.session.add(player)
    db.session.commit()
    
    retrieved_player = db.session.get(Player, 8476458)
    assert retrieved_player is not None
    assert retrieved_player.current_team.abbreviation == 'CGY'
    assert retrieved_player.full_name == 'Jonathan Huberdeau'
    assert player in cgy.players
    
    # 3. Create a Game
    game = Game(
        game_id=2023020001,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=cgy.team_id,
        away_team_id=cgy.team_id, # Simplified for test
        home_score=4,
        away_score=3,
        game_status='Final'
    )
    db.session.add(game)
    db.session.commit()
    
    retrieved_game = db.session.get(Game, 2023020001)
    assert retrieved_game is not None
    assert retrieved_game.season == '20232024'
    
    # 4. Create an Event linked to the Game
    event = Event(
        event_id="2023020001_10",
        game_id=game.game_id,
        period=1,
        period_time="05:30",
        elapsed_game_seconds=330,
        event_type="Shot",
        team_id=cgy.team_id,
        primary_player_id=player.player_id,
        x_coordinate=10.0,
        y_coordinate=20.0,
        strength_state="5v5"
    )
    db.session.add(event)
    db.session.commit()
    
    retrieved_event = db.session.get(Event, "2023020001_10")
    assert retrieved_event is not None
    assert retrieved_event.game.game_id == game.game_id
    assert retrieved_event.primary_player.last_name == 'Huberdeau'
    
    # 5. Create a Shot linked to the Event
    shot = Shot(
        shot_id=event.event_id,
        shooter_id=player.player_id,
        goalie_id=None,
        shot_type='Wrist',
        x_coordinate=10.0,
        y_coordinate=20.0,
        distance=30.0,
        angle=15.0,
        outcome='Saved',
        goal=False,
        strength_state='5v5'
    )
    db.session.add(shot)
    db.session.commit()
    
    retrieved_shot = db.session.get(Shot, event.event_id)
    assert retrieved_shot is not None
    assert retrieved_shot.event.event_type == 'Shot'
    assert retrieved_shot.shooter.first_name == 'Jonathan'
    assert event.shot == retrieved_shot
    
    # 6. Create a Shift
    shift = Shift(
        shift_id="2023020001_8476458_1_0",
        game_id=game.game_id,
        player_id=player.player_id,
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    db.session.add(shift)
    db.session.commit()
    
    retrieved_shift = db.session.get(Shift, "2023020001_8476458_1_0")
    assert retrieved_shift is not None
    assert retrieved_shift.duration == 45
    assert retrieved_shift.player.player_id == player.player_id
    assert retrieved_shift in game.shifts
    assert retrieved_shift in player.shifts
