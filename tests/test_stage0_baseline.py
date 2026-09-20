import pytest
from datetime import date
from app.models import Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.player_season_service import PlayerSeasonService
from app.services.team_season_service import TeamSeasonService

@pytest.fixture
def sample_stage0_data(db):
    """Populates test DB with sample season data for baseline tests."""
    t1 = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    t2 = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    
    p1 = Player(player_id=101, first_name='Mikael', last_name='Backlund', position='C')
    p2 = Player(player_id=102, first_name='Blake', last_name='Coleman', position='RW')
    p3 = Player(player_id=103, first_name='Connor', last_name='McDavid', position='C')
    
    db.session.add_all([t1, t2, p1, p2, p3])
    db.session.commit()

    g1 = Game(
        game_id=2023020001,
        season='20232024',
        game_date=date(2023, 10, 12),
        game_type='R',
        home_team_id=1,
        away_team_id=2,
        home_score=4,
        away_score=2,
        nhl_game_state='FINAL'
    )
    db.session.add(g1)
    db.session.commit()

    gp1 = GamePlayer(game_id=2023020001, player_id=101, team_id=1, position='C')
    gp2 = GamePlayer(game_id=2023020001, player_id=102, team_id=1, position='RW')
    gp3 = GamePlayer(game_id=2023020001, player_id=103, team_id=2, position='C')
    db.session.add_all([gp1, gp2, gp3])

    s1 = Shift(
        shift_id='2023020001_101_1_0',
        game_id=2023020001,
        player_id=101,
        period=1,
        start_time='00:00',
        end_time='10:00',
        start_elapsed_seconds=0,
        end_elapsed_seconds=600,
        duration=600,
        team_id=1,
        is_anomaly=False
    )
    s2 = Shift(
        shift_id='2023020001_102_1_0',
        game_id=2023020001,
        player_id=102,
        period=1,
        start_time='00:00',
        end_time='10:00',
        start_elapsed_seconds=0,
        end_elapsed_seconds=600,
        duration=600,
        team_id=1,
        is_anomaly=False
    )
    db.session.add_all([s1, s2])

    ev1 = Event(
        event_id='2023020001_10',
        game_id=2023020001,
        period=1,
        period_time='05:00',
        elapsed_game_seconds=300,
        event_type='goal',
        team_id=1,
        primary_player_id=101,
        assist1_player_id=102
    )
    sh1 = Shot(
        shot_id='2023020001_10',
        game_id=2023020001,
        shooter_id=101,
        team_id=1,
        outcome='Goal',
        shot_type='Snap',
        distance=15.0,
        xg=0.35
    )
    db.session.add_all([ev1, sh1])
    db.session.commit()

def test_stage0_skater_season_stats_invariants(app, db, sample_stage0_data):
    """
    Verifies baseline mathematical invariants for skater season statistics.
    Ensures points = goals + assists, shooting_pct calculation, and 5v5 structure.
    """
    skaters = PlayerSeasonService.get_season_skaters_summary(
        season="20232024",
        include_on_ice_5v5=True
    )
    assert len(skaters) > 0, "Season skater summary should return records"

    for skater in skaters:
        # Invariant 1: points == goals + assists
        assert skater["points"] == skater["goals"] + skater["assists"], f"Points mismatch for player {skater['player_id']}"
        
        # Invariant 2: goals_minus_xg == round(goals - xg, 2)
        expected_g_minus_xg = round(skater["goals"] - skater["xg"], 2)
        assert abs(skater["goals_minus_xg"] - expected_g_minus_xg) < 0.01

        # Invariant 3: shooting_pct == round(goals / shots * 100, 2) if shots > 0 else 0.0
        if skater["shots"] > 0:
            exp_sh_pct = round(skater["goals"] / skater["shots"] * 100, 2)
            assert abs(skater["shooting_pct"] - exp_sh_pct) < 0.01
        else:
            assert skater["shooting_pct"] == 0.0

        # Invariant 4: 5v5 on-ice metrics structure presence
        assert "on_ice_5v5" in skater
        oi = skater["on_ice_5v5"]
        assert "cf" in oi and "ca" in oi and "cf_pct" in oi
        assert "ff" in oi and "fa" in oi and "ff_pct" in oi
        assert "on_ice_xgf" in oi and "on_ice_xga" in oi and "on_ice_xg_pct" in oi

        # Invariant 5: CF% calculation ratio
        tot_c = oi["cf"] + oi["ca"]
        if tot_c > 0:
            exp_cf_pct = round(oi["cf"] / tot_c * 100, 2)
            assert abs(oi["cf_pct"] - exp_cf_pct) < 0.01
        else:
            assert oi["cf_pct"] == 50.0

def test_stage0_single_player_query_equivalence(app, db, sample_stage0_data):
    """
    Verifies that querying single player season stats matches the player entry in full summary.
    """
    all_skaters = PlayerSeasonService.get_season_skaters_summary(season="20232024", include_on_ice_5v5=True)
    assert len(all_skaters) > 0

    top_skater = all_skaters[0]
    pid = top_skater["player_id"]

    single_skater = PlayerSeasonService.get_skater_season_stats(player_id=pid, season="20232024")
    assert single_skater is not None
    assert single_skater["player_id"] == pid
    assert single_skater["goals"] == top_skater["goals"]
    assert single_skater["assists"] == top_skater["assists"]
    assert single_skater["points"] == top_skater["points"]
    assert single_skater["toi_seconds"] == top_skater["toi_seconds"]
    assert single_skater["on_ice_5v5"]["cf"] == top_skater["on_ice_5v5"]["cf"]
    assert single_skater["on_ice_5v5"]["ca"] == top_skater["on_ice_5v5"]["ca"]

def test_stage0_team_season_stats_invariants(app, db, sample_stage0_data):
    """
    Verifies baseline mathematical invariants for team season statistics.
    """
    teams_summary = TeamSeasonService.get_season_teams_summary(season="20232024", situation="5v5")
    assert len(teams_summary) > 0

    for team in teams_summary:
        assert "team_id" in team
        assert "gp" in team
        assert team["w"] + team["l"] + team["otl"] == team["gp"]
