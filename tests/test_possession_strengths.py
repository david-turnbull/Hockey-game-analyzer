import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, Shot
from app.services.possession_service import PossessionService

def test_possession_strength_exclusions(app, db):
    """
    Verifies that Corsi/Fenwick metrics filtered by 5v5 contain only true 5-on-5 play,
    specifically excluding 4v4, 3v3, power play, penalty kill, empty-net, and shootouts.
    """
    # 1. Seed Teams and Players
    home_team = Team(team_id=1, name="Home", abbreviation="HOM")
    away_team = Team(team_id=2, name="Away", abbreviation="AWA")
    db.session.add_all([home_team, away_team])
    db.session.commit()

    h1 = Player(player_id=11, first_name="Home", last_name="Skater1", position="C", current_team_id=1)
    a1 = Player(player_id=21, first_name="Away", last_name="Skater1", position="RW", current_team_id=2)
    db.session.add_all([h1, a1])
    db.session.commit()

    # 2. Seed Game
    game = Game(
        game_id=4001,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type="R",
        home_team_id=1,
        away_team_id=2,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 3. Seed shifts (both on ice for period 1 from 0 to 1000s)
    s_h = Shift(shift_id="s_h", game_id=4001, player_id=11, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s_a = Shift(shift_id="s_a", game_id=4001, player_id=21, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    db.session.add_all([s_h, s_a])
    db.session.commit()

    # 4. Seed events under various strengths
    # Helper to create event + shot
    def create_shot_event(evt_id, seconds, type_code, h_skaters, a_skaters, p_type="REG", team_id=1):
        e = Event(
            event_id=evt_id,
            game_id=4001,
            period=1,
            period_time="00:00",
            elapsed_game_seconds=seconds,
            event_type="shot-on-goal",
            team_id=team_id,
            primary_player_id=11,
            manpower_state="EV" if h_skaters == a_skaters else "PP",
            team_strength_state=f"{h_skaters}v{a_skaters}",
            raw_situation_code=type_code,
            home_skaters=h_skaters,
            away_skaters=a_skaters,
            period_type=p_type
        )
        db.session.add(e)
        db.session.commit()
        sh = Shot(
            shot_id=evt_id,
            game_id=4001,
            team_id=team_id,
            shooter_id=11,
            outcome="Saved",
            goal=False,
            x_coordinate=80.0,
            y_coordinate=0.0
        )
        db.session.add(sh)
        db.session.commit()

    # E1: True 5v5 shot (Included in 5v5)
    create_shot_event("evt_5v5", 100, "1551", 5, 5)

    # E2: 4v4 shot (Excluded from 5v5)
    create_shot_event("evt_4v4", 200, "1441", 4, 4)

    # E3: 3v3 shot (Excluded from 5v5)
    create_shot_event("evt_3v3", 300, "1331", 3, 3)

    # E4: 5v4 shot (Excluded from 5v5)
    create_shot_event("evt_5v4", 400, "1451", 5, 4)

    # E5: Empty net shot (Excluded from 5v5)
    create_shot_event("evt_en", 500, "0551", 5, 5)

    # E6: Shootout shot (Excluded from 5v5)
    create_shot_event("evt_so", 600, "1551", 5, 5, p_type="SO")

    # 5. Run calculations
    pos_5v5 = PossessionService.calculate_possession_stats(4001, mode="5v5")
    
    # Verify that only the true 5v5 shot (E1) is included for h1 (cf = 1)
    assert 11 in pos_5v5
    assert pos_5v5[11]["cf"] == 1

    # Verify that in EV mode (all even strength), E1, E2, E3 are included (cf = 3)
    # Note: E5 is also an even strength situation (5v5 skaters, though net is empty), so it is counted under EV mode, making CF = 4.
    pos_ev = PossessionService.calculate_possession_stats(4001, mode="EV")
    assert 11 in pos_ev
    assert pos_ev[11]["cf"] == 4
