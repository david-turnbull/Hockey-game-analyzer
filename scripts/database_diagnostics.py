import os
import sys

# Ensure project root in sys.path so we can run from anywhere
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models.base import db
from app.models import Game, Team, Player, Event, Shot, Shift, GamePlayer

def run_diagnostics():
    app = create_app('development')
    with app.app_context():
        # Get count of each entity
        games_count = Game.query.count()
        teams_count = Team.query.count()
        players_count = Player.query.count()
        events_count = Event.query.count()
        shots_count = Shot.query.count()
        shifts_count = Shift.query.count()
        game_players_count = GamePlayer.query.count()
        
        # Detect integrity issues
        game_ids = {g[0] for g in db.session.query(Game.game_id).all()}
        team_ids = {t[0] for t in db.session.query(Team.team_id).all()}
        player_ids = {p[0] for p in db.session.query(Player.player_id).all()}
        
        orphan_events_count = db.session.query(Event).filter(~Event.game_id.in_(list(game_ids))).count() if game_ids else Event.query.count()
        orphan_shots_count = db.session.query(Shot).filter(~Shot.shot_id.in_(
            db.session.query(Event.event_id).filter(Event.game_id.in_(list(game_ids)))
        )).count() if game_ids else Shot.query.count()
        orphan_shifts_count = db.session.query(Shift).filter(~Shift.game_id.in_(list(game_ids))).count() if game_ids else Shift.query.count()
        
        # Orphan GamePlayer entries (missing valid game, player, or team)
        orphan_game_players = db.session.query(GamePlayer).filter(
            ~GamePlayer.game_id.in_(list(game_ids)) |
            ~GamePlayer.player_id.in_(list(player_ids)) |
            ~GamePlayer.team_id.in_(list(team_ids))
        ).count() if (game_ids and player_ids and team_ids) else GamePlayer.query.count()

        # Missing GamePlayer relationships: Player appears in game shifts or events, but has no GamePlayer row
        players_in_shifts = db.session.query(Shift.game_id, Shift.player_id).filter(Shift.game_id.isnot(None), Shift.player_id.isnot(None)).distinct()
        active_player_games = set(players_in_shifts.all())

        for p_field in [Event.primary_player_id, Event.secondary_player_id, Event.assist1_player_id, Event.assist2_player_id]:
            pairs = db.session.query(Event.game_id, p_field).filter(Event.game_id.isnot(None), p_field.isnot(None)).distinct().all()
            for game_id, player_id in pairs:
                active_player_games.add((game_id, player_id))

        missing_game_player_relations = 0
        for g_id, p_id in active_player_games:
            exists = db.session.query(GamePlayer).filter_by(game_id=g_id, player_id=p_id).first()
            if not exists:
                missing_game_player_relations += 1

        invalid_evt_primary = db.session.query(Event).filter(Event.primary_player_id.isnot(None), ~Event.primary_player_id.in_(list(player_ids))).count() if player_ids else 0
        invalid_evt_secondary = db.session.query(Event).filter(Event.secondary_player_id.isnot(None), ~Event.secondary_player_id.in_(list(player_ids))).count() if player_ids else 0
        invalid_evt_assist1 = db.session.query(Event).filter(Event.assist1_player_id.isnot(None), ~Event.assist1_player_id.in_(list(player_ids))).count() if player_ids else 0
        invalid_evt_assist2 = db.session.query(Event).filter(Event.assist2_player_id.isnot(None), ~Event.assist2_player_id.in_(list(player_ids))).count() if player_ids else 0
        
        invalid_shot_shooter = db.session.query(Shot).filter(Shot.shooter_id.isnot(None), ~Shot.shooter_id.in_(list(player_ids))).count() if player_ids else 0
        invalid_shot_goalie = db.session.query(Shot).filter(Shot.goalie_id.isnot(None), ~Shot.goalie_id.in_(list(player_ids))).count() if player_ids else 0
        
        invalid_shift_player = db.session.query(Shift).filter(Shift.player_id.isnot(None), ~Shift.player_id.in_(list(player_ids))).count() if player_ids else 0
        
        invalid_player_refs = (invalid_evt_primary + invalid_evt_secondary + invalid_evt_assist1 + invalid_evt_assist2 +
                               invalid_shot_shooter + invalid_shot_goalie + invalid_shift_player)
                               
        zero_duration_shifts = db.session.query(Shift).filter((Shift.duration == 0) | (Shift.is_anomaly == True)).count()
        negative_duration_shifts = db.session.query(Shift).filter(Shift.duration < 0).count()
        
        # Mismatches: Shift team does not agree with GamePlayer roster team
        shift_team_mismatches = db.session.query(Shift).join(
            GamePlayer,
            (Shift.game_id == GamePlayer.game_id) & (Shift.player_id == GamePlayer.player_id)
        ).filter(Shift.team_id != GamePlayer.team_id).count()

        # Duplicate GamePlayer records (should be 0 because (game_id, player_id) is composite PK)
        duplicate_game_players = db.session.query(
            GamePlayer.game_id, GamePlayer.player_id
        ).group_by(GamePlayer.game_id, GamePlayer.player_id).having(db.func.count() > 1).count()

        unknown_period_types_evt = db.session.query(Event).filter((Event.period_type.is_(None)) | (~Event.period_type.in_(['REG', 'OT', 'SO']))).count()
        unknown_period_types_shift = db.session.query(Shift).filter((Shift.period_type.is_(None)) | (~Shift.period_type.in_(['REG', 'OT', 'SO']))).count()
        unknown_period_types = unknown_period_types_evt + unknown_period_types_shift
        
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        invalid_manpower_states = db.session.query(Event).filter(
            Event.event_type.in_(shot_event_types),
            (Event.manpower_state.is_(None)) | (~Event.manpower_state.in_(['EV', 'PP', 'PK', 'EMPTY_NET_FOR', 'EMPTY_NET_AGAINST', 'SO']))
        ).count()
        
        shots_without_shooters = db.session.query(Shot).filter(Shot.shooter_id.is_(None)).count()
        events_with_invalid_clocks = db.session.query(Event).filter(Event.elapsed_game_seconds.is_(None)).count()
        
        integrity_issues_sum = (orphan_events_count + orphan_shots_count + orphan_shifts_count + 
                                orphan_game_players + invalid_player_refs + negative_duration_shifts + 
                                shots_without_shooters + shift_team_mismatches + missing_game_player_relations +
                                duplicate_game_players)
        warnings_sum = zero_duration_shifts + unknown_period_types + invalid_manpower_states + events_with_invalid_clocks
        
        if integrity_issues_sum > 0:
            result_status = "FAIL"
        elif warnings_sum > 0:
            result_status = "PASS WITH WARNINGS"
        else:
            result_status = "PASS"
            
        print("NHL Database Integrity Report")
        print("=============================")
        print(f"Games: {games_count:>14,}")
        print(f"Teams: {teams_count:>14,}")
        print(f"Players: {players_count:>12,}")
        print(f"GamePlayer records: {game_players_count:>5,}")
        print(f"Events: {events_count:>13,}")
        print(f"Shot attempts: {shots_count:>7,}")
        print(f"Shifts: {shifts_count:>13,}")
        print()
        print("Integrity")
        print("---------")
        print(f"Orphan events: {orphan_events_count:>10}")
        print(f"Orphan shots: {orphan_shots_count:>13}")
        print(f"Orphan shifts: {orphan_shifts_count:>12}")
        print(f"Orphan GamePlayer records: {orphan_game_players:>4}")
        print(f"Duplicate GamePlayer records: {duplicate_game_players:>1}")
        print(f"Historical team mismatches: {shift_team_mismatches:>2}")
        print(f"Zero-duration shifts: {zero_duration_shifts:>6}")
        print(f"Negative-duration shifts: {negative_duration_shifts:>3}")
        print(f"Shots missing required shooters: {shots_without_shooters:>1}")
        print()
        print("Warnings")
        print("--------")
        print(f"Invalid manpower states: {invalid_manpower_states:>2}")
        print(f"Unknown period types: {unknown_period_types:>6}")
        print(f"Other warnings: {events_with_invalid_clocks:>11}")
        print()
        print(f"Result: {result_status}")

if __name__ == '__main__':
    run_diagnostics()
