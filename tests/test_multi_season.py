import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from data_pipeline.loaders.db_loader import DatabaseLoader

def test_multi_season_isolation(app, db):
    """
    Verify that games, shots, events, shifts, and rosters for different seasons
    coexist safely in the database and never leak into queries for another season.
    """
    # 1. Setup teams
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=22, abbreviation='EDM', name='Edmonton Oilers')
    db.session.add_all([cgy, edm])
    db.session.commit()

    # 2. Setup a player who plays across two seasons
    player = Player(
        player_id=8478402,
        first_name='Connor',
        last_name='McDavid',
        position='C',
        current_team_id=22
    )
    db.session.add(player)
    db.session.commit()

    # 3. Create Season 1 (2023-24) Game
    game_s1 = Game(
        game_id=2023020001,
        season='20232024',
        game_date=date(2023, 10, 11),
        game_type='R',
        home_team_id=20,
        away_team_id=22,
        home_score=3,
        away_score=4,
        nhl_game_state='FINAL'
    )
    db.session.add(game_s1)
    db.session.flush()

    # Add S1 events, shot, and roster entry
    gp_s1 = GamePlayer(game_id=game_s1.game_id, player_id=player.player_id, team_id=22, position='C', sweater_number=97)
    ev_s1 = Event(
        event_id='2023020001_10',
        game_id=game_s1.game_id,
        period=1,
        period_time='05:00',
        elapsed_game_seconds=300,
        event_type='shot-on-goal',
        team_id=22,
        primary_player_id=player.player_id,
        team_strength_state='5v5'
    )
    shot_s1 = Shot(
        shot_id='2023020001_10',
        game_id=game_s1.game_id,
        team_id=22,
        shooter_id=player.player_id,
        distance=20.0,
        angle=15.0,
        outcome='Saved',
        goal=False,
        xg=0.12,
        strength_state='EV'
    )
    db.session.add_all([gp_s1, ev_s1, shot_s1])

    # 4. Create Season 2 (2024-25) Game
    game_s2 = Game(
        game_id=2024020001,
        season='20242025',
        game_date=date(2024, 10, 12),
        game_type='R',
        home_team_id=22,
        away_team_id=20,
        home_score=5,
        away_score=2,
        nhl_game_state='FINAL'
    )
    db.session.add(game_s2)
    db.session.flush()

    gp_s2 = GamePlayer(game_id=game_s2.game_id, player_id=player.player_id, team_id=22, position='C', sweater_number=97)
    ev_s2 = Event(
        event_id='2024020001_20',
        game_id=game_s2.game_id,
        period=2,
        period_time='10:00',
        elapsed_game_seconds=1800,
        event_type='goal',
        team_id=22,
        primary_player_id=player.player_id,
        team_strength_state='5v5'
    )
    shot_s2 = Shot(
        shot_id='2024020001_20',
        game_id=game_s2.game_id,
        team_id=22,
        shooter_id=player.player_id,
        distance=12.0,
        angle=5.0,
        outcome='Goal',
        goal=True,
        xg=0.35,
        strength_state='EV'
    )
    db.session.add_all([gp_s2, ev_s2, shot_s2])
    db.session.commit()

    # 5. Isolation verification:
    # Query Season 20232024
    s1_games = Game.query.filter_by(season='20232024').all()
    assert len(s1_games) == 1
    assert s1_games[0].game_id == 2023020001

    s1_shots = db.session.query(Shot).join(Game, Shot.game_id == Game.game_id).filter(Game.season == '20232024').all()
    assert len(s1_shots) == 1
    assert s1_shots[0].shot_id == '2023020001_10'
    assert s1_shots[0].outcome == 'Saved'

    # Query Season 20242025
    s2_games = Game.query.filter_by(season='20242025').all()
    assert len(s2_games) == 1
    assert s2_games[0].game_id == 2024020001

    s2_shots = db.session.query(Shot).join(Game, Shot.game_id == Game.game_id).filter(Game.season == '20242025').all()
    assert len(s2_shots) == 1
    assert s2_shots[0].shot_id == '2024020001_20'
    assert s2_shots[0].outcome == 'Goal'

    # Cross-season sum should have both, but individual seasons remain strictly separated
    all_shots = Shot.query.all()
    assert len(all_shots) == 2


def test_duplicate_ingestion_idempotence(app, db):
    """
    Verify that repeatedly ingesting the same game produces identical records
    without duplicates or foreign key violations.
    """
    loader = DatabaseLoader(db.session)

    def create_game_objects():
        team_home = Team(team_id=1, abbreviation='HOM', name='Home Team')
        team_away = Team(team_id=2, abbreviation='AWA', name='Away Team')
        player = Player(player_id=101, first_name='John', last_name='Doe', position='F')

        game = Game(
            game_id=2024020999,
            season='20242025',
            game_date=date(2024, 11, 1),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=1,
            away_score=0,
            nhl_game_state='FINAL'
        )
        gp = GamePlayer(game_id=2024020999, player_id=101, team_id=1, position='F', sweater_number=10)
        event = Event(
            event_id='2024020999_1',
            game_id=2024020999,
            period=1,
            period_time='01:00',
            elapsed_game_seconds=60,
            event_type='goal',
            team_id=1,
            primary_player_id=101
        )
        shot = Shot(
            shot_id='2024020999_1',
            game_id=2024020999,
            team_id=1,
            shooter_id=101,
            distance=15.0,
            angle=10.0,
            outcome='Goal',
            goal=True,
            xg=0.22
        )
        return game, [team_home, team_away], [player], [event], [shot], [], [gp]

    # First load
    game, teams, players, events, shots, shifts, gps = create_game_objects()
    success = loader.load_game_data(game, teams, players, events, shots, shifts, gps)
    assert success is True
    db.session.commit()

    assert Game.query.filter_by(game_id=2024020999).count() == 1
    assert Event.query.filter_by(game_id=2024020999).count() == 1
    assert Shot.query.filter_by(game_id=2024020999).count() == 1

    # Second load (idempotence with fresh objects representing fresh ingest run)
    game2, teams2, players2, events2, shots2, shifts2, gps2 = create_game_objects()
    success2 = loader.load_game_data(game2, teams2, players2, events2, shots2, shifts2, gps2)
    assert success2 is True
    db.session.commit()

    assert Game.query.filter_by(game_id=2024020999).count() == 1
    assert Event.query.filter_by(game_id=2024020999).count() == 1
    assert Shot.query.filter_by(game_id=2024020999).count() == 1
