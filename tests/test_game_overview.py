import pytest
from datetime import date
from app.models import Team, Player, Game, Event, Shot, Shift
from app.services.game_service import GameService

def test_game_overview_calculations(app, db):
    # 1. Setup mock teams
    cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    wpg = Team(team_id=52, abbreviation='WPG', name='Winnipeg Jets')
    db.session.add_all([cgy, wpg])
    db.session.flush()

    # 2. Setup mock players
    huberdeau = Player(player_id=1, first_name='Jonathan', last_name='Huberdeau', position='LW', current_team=cgy)
    kadri = Player(player_id=2, first_name='Nazem', last_name='Kadri', position='C', current_team=cgy)
    backlund = Player(player_id=3, first_name='Mikael', last_name='Backlund', position='C', current_team=cgy)
    scheifele = Player(player_id=4, first_name='Mark', last_name='Scheifele', position='C', current_team=wpg)
    hellebuyck = Player(player_id=5, first_name='Connor', last_name='Hellebuyck', position='G', current_team=wpg)
    db.session.add_all([huberdeau, kadri, backlund, scheifele, hellebuyck])
    db.session.flush()

    # 3. Setup mock game
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

    # 4. Add Shots on Goal (shots and goals)
    # CGY (Home) shots: 2 shot-on-goal + 2 goal = 4 SOG
    # WPG (Away) shots: 1 shot-on-goal + 1 goal = 2 SOG
    
    # Calgary Goal 1 (Even strength, assisted)
    g1 = Event(event_id="2023020007_1", game_id=game.game_id, period=1, period_time="05:00", elapsed_game_seconds=300, event_type="goal", team_id=cgy.team_id, primary_player_id=huberdeau.player_id, secondary_player_id=hellebuyck.player_id, assist1_player_id=kadri.player_id, strength_state="5v5")
    # Calgary Goal 2 (Power play 5v4, unassisted)
    g2 = Event(event_id="2023020007_2", game_id=game.game_id, period=2, period_time="10:00", elapsed_game_seconds=1800, event_type="goal", team_id=cgy.team_id, primary_player_id=kadri.player_id, secondary_player_id=hellebuyck.player_id, strength_state="5v4")
    # Winnipeg Goal 1 (Even strength)
    g3 = Event(event_id="2023020007_3", game_id=game.game_id, period=3, period_time="15:00", elapsed_game_seconds=3300, event_type="goal", team_id=wpg.team_id, primary_player_id=scheifele.player_id, strength_state="5v5")
    
    # Shots saved
    s1 = Event(event_id="2023020007_4", game_id=game.game_id, period=1, period_time="02:00", elapsed_game_seconds=120, event_type="shot-on-goal", team_id=cgy.team_id, primary_player_id=backlund.player_id)
    s2 = Event(event_id="2023020007_5", game_id=game.game_id, period=1, period_time="03:00", elapsed_game_seconds=180, event_type="shot-on-goal", team_id=cgy.team_id, primary_player_id=huberdeau.player_id)
    s3 = Event(event_id="2023020007_6", game_id=game.game_id, period=2, period_time="04:00", elapsed_game_seconds=1440, event_type="shot-on-goal", team_id=wpg.team_id, primary_player_id=scheifele.player_id)
    
    db.session.add_all([g1, g2, g3, s1, s2, s3])
    db.session.flush()

    # 5. Add Faceoffs
    # Total: 3 faceoffs (2 won by CGY, 1 by WPG) -> CGY = 66.7%, WPG = 33.3%
    f1 = Event(event_id="2023020007_7", game_id=game.game_id, period=1, period_time="00:10", elapsed_game_seconds=10, event_type="faceoff", team_id=cgy.team_id)
    f2 = Event(event_id="2023020007_8", game_id=game.game_id, period=1, period_time="05:10", elapsed_game_seconds=310, event_type="faceoff", team_id=cgy.team_id)
    f3 = Event(event_id="2023020007_9", game_id=game.game_id, period=2, period_time="00:10", elapsed_game_seconds=1210, event_type="faceoff", team_id=wpg.team_id)
    
    db.session.add_all([f1, f2, f3])
    db.session.flush()

    # 6. Add Penalties
    # CGY: 1 minor (2 PIM)
    # WPG: 2 minors (4 PIM)
    p1 = Event(event_id="2023020007_10", game_id=game.game_id, period=1, period_time="11:00", elapsed_game_seconds=660, event_type="penalty", team_id=cgy.team_id, primary_player_id=backlund.player_id, penalty_duration=2, penalty_description="Tripping")
    p2 = Event(event_id="2023020007_11", game_id=game.game_id, period=2, period_time="08:00", elapsed_game_seconds=1680, event_type="penalty", team_id=wpg.team_id, primary_player_id=scheifele.player_id, penalty_duration=2, penalty_description="Roughing")
    p3 = Event(event_id="2023020007_12", game_id=game.game_id, period=2, period_time="15:00", elapsed_game_seconds=2100, event_type="penalty", team_id=wpg.team_id, primary_player_id=scheifele.player_id, penalty_duration=2, penalty_description="Slashing")
    
    db.session.add_all([p1, p2, p3])
    db.session.commit()

    # 7. Run Calculations via Service
    overview = GameService.get_game_overview_stats(game.game_id)
    
    assert overview is not None
    assert overview["home_score"] == 2
    assert overview["away_score"] == 1
    
    # Validate Team Stats Comparison
    stats = overview["stats"]
    assert stats["home_sog"] == 4
    assert stats["away_sog"] == 2
    assert stats["home_shooting_pct"] == 50.0  # 2 goals on 4 SOG
    assert stats["away_shooting_pct"] == 50.0  # 1 goal on 2 SOG
    assert stats["home_pim"] == 2
    assert stats["away_pim"] == 4
    assert stats["home_fo_pct"] == 66.7
    assert stats["away_fo_pct"] == 33.3
    assert stats["home_ppg"] == 1  # Goal 2 scored in 5v4 powerplay
    assert stats["away_ppg"] == 0

    # Validate Timeline Mappings
    timeline = overview["timeline"]
    assert "1st Period" in timeline
    assert "2nd Period" in timeline
    assert "3rd Period" in timeline
    
    p1_events = [e for e in timeline["1st Period"] if e["event_type"] in ["goal", "penalty"]]
    assert len(p1_events) == 2  # Calgary Goal 1, Calgary Penalty 1
    
    # Goal 1 checks
    g_event = p1_events[0]
    assert g_event["event_type"] == "goal"
    assert g_event["scorer"] == "Jonathan Huberdeau"
    assert g_event["assists"] == "Assist: Nazem Kadri"
    assert g_event["running_score"] == "0 - 1"
    
    # Penalty 1 checks
    p_event = p1_events[1]
    assert p_event["event_type"] == "penalty"
    assert p_event["player"] == "Mikael Backlund"
    assert p_event["infraction"] == "Tripping"
    assert p_event["duration"] == 2
