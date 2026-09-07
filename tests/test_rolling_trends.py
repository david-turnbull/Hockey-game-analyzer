import pytest
from datetime import date, timedelta
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.rolling_service import RollingService

def test_team_rolling_trends_chronology_and_isolation(app, db):
    """
    Given ordered games, verify:
    1. Exact last-N selection without future-game leakage.
    2. Correct calculation of xGF%, xG differential, CF%, FF%, etc.
    """
    team = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    opp = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    shooter = Player(player_id=10, first_name='Shooter', last_name='One', position='F')
    db.session.add_all([team, opp, shooter])
    db.session.commit()

    # Create 7 games chronologically spaced by 2 days
    # Games 1-4: CGY dominates (xGF = 3.0, xGA = 1.0 each game, CF = 10, CA = 4)
    # Games 5-7: CGY struggles (xGF = 1.0, xGA = 3.0 each game, CF = 4, CA = 10)
    games = []
    events = []
    shots = []
    base_date = date(2024, 10, 1)

    for i in range(1, 8):
        g = Game(
            game_id=2024020100 + i,
            season='20242025',
            game_date=base_date + timedelta(days=i * 2),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=3 if i <= 4 else 1,
            away_score=1 if i <= 4 else 3,
            nhl_game_state='FINAL'
        )
        games.append(g)

    db.session.add_all(games)
    db.session.flush()

    for idx, g in enumerate(games, 1):
        if idx <= 4:
            cgy_xg = 3.0
            opp_xg = 1.0
            cgy_attempts = 10
            opp_attempts = 4
        else:
            cgy_xg = 1.0
            opp_xg = 3.0
            cgy_attempts = 4
            opp_attempts = 10

        # CGY shot
        e_cgy = Event(event_id=f"e_cgy_{idx}", game_id=g.game_id, period=1, period_time='05:00',
                      event_type='goal', team_id=1)
        s_cgy = Shot(shot_id=f"e_cgy_{idx}", game_id=g.game_id, team_id=1, shooter_id=10,
                     outcome='Goal', goal=True, xg=cgy_xg)
        # Opp shot
        e_opp = Event(event_id=f"e_opp_{idx}", game_id=g.game_id, period=2, period_time='05:00',
                      event_type='goal', team_id=2)
        s_opp = Shot(shot_id=f"e_opp_{idx}", game_id=g.game_id, team_id=2, shooter_id=10,
                     outcome='Goal', goal=True, xg=opp_xg)

        # Additional attempts to match Corsi
        for a_idx in range(cgy_attempts - 1):
            ea = Event(event_id=f"ea_cgy_{idx}_{a_idx}", game_id=g.game_id, period=1, period_time='06:00',
                       event_type='shot-on-goal', team_id=1)
            sa = Shot(shot_id=f"ea_cgy_{idx}_{a_idx}", game_id=g.game_id, team_id=1, shooter_id=10,
                      outcome='Saved', goal=False, xg=0.0)
            events.append(ea)
            shots.append(sa)

        for a_idx in range(opp_attempts - 1):
            ea = Event(event_id=f"ea_opp_{idx}_{a_idx}", game_id=g.game_id, period=2, period_time='06:00',
                       event_type='shot-on-goal', team_id=2)
            sa = Shot(shot_id=f"ea_opp_{idx}_{a_idx}", game_id=g.game_id, team_id=2, shooter_id=10,
                      outcome='Saved', goal=False, xg=0.0)
            events.append(ea)
            shots.append(sa)

        events.extend([e_cgy, e_opp])
        shots.extend([s_cgy, s_opp])

    db.session.add_all(events + shots)
    db.session.commit()

    rolling_res = RollingService.get_team_rolling_trends(team_id=1, season='20242025', window_sizes=[5])
    assert "5" in rolling_res["windows"]
    pts = rolling_res["windows"]["5"]
    assert len(pts) == 7

    # At game 4 (index 3): window covers games 1-4 (all strong games)
    # xGF = 4 * 3.0 = 12.0, xGA = 4 * 1.0 = 4.0 -> xGF% = 12 / 16 = 75.0%
    pt_g4 = pts[3]
    assert pt_g4["game_index"] == 4
    assert pt_g4["games_in_window"] == 4
    assert pytest.approx(pt_g4["xgf_pct"], 0.1) == 75.0
    assert pytest.approx(pt_g4["xg_diff"], 0.1) == 8.0

    # At game 7 (index 6): window of 5 covers games 3, 4, 5, 6, 7
    # Games 3,4: xGF = 6.0, xGA = 2.0
    # Games 5,6,7: xGF = 3.0, xGA = 9.0
    # Window total: xGF = 9.0, xGA = 11.0 -> xGF% = 9 / 20 = 45.0%
    pt_g7 = pts[6]
    assert pt_g7["game_index"] == 7
    assert pt_g7["games_in_window"] == 5
    assert pytest.approx(pt_g7["xgf_pct"], 0.1) == 45.0
    assert pytest.approx(pt_g7["xg_diff"], 0.1) == -2.0

    # Verify game 4 had NO leakage from games 5, 6, 7
    assert pt_g4["xgf_pct"] > pt_g7["xgf_pct"]

    # Verify template field bindings and aliases
    assert pt_g4["game_number"] == 4
    assert pt_g4["opponent"] == "EDM"
    assert pt_g4["opponent_display"] == "vs EDM"
    assert pt_g4["is_home"] is True
    assert pt_g4["rolling_xg_pct"] == pt_g4["xgf_pct"]
    assert pt_g4["rolling_cf_pct"] == pt_g4["cf_pct"]
    assert pt_g4["rolling_xg_diff"] == pt_g4["xg_diff"]

