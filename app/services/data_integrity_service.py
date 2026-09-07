import os
import json
import logging
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, Team

logger = logging.getLogger(__name__)

class DataIntegrityService:
    """Service class for validating relational database integrity and running health diagnostic checks."""

    @staticmethod
    def run_diagnostic_checks() -> dict:
        """
        Runs comprehensive health checks on the relational database.
        Returns check statuses and actionable details.
        """
        diagnostics = {
            "game_ingestion": {"status": "PASS", "details": []},
            "player_metadata": {"status": "PASS", "details": []},
            "shift_reconstruction": {"status": "PASS", "details": []},
            "boxscore_validation": {"status": "PASS", "details": []},
            "five_v_five_reconstruction": {"status": "PASS", "details": []}
        }
        
        # Preload lists/sets for check integrity
        game_ids = {g[0] for g in db.session.query(Game.game_id).all()}
        player_ids = {p[0] for p in db.session.query(Player.player_id).all()}
        team_ids = {t[0] for t in db.session.query(Team.team_id).all()}
        
        # 1. Game Ingestion Checks (Orphans & Missing Relationships)
        orphan_events = db.session.query(Event).filter(~Event.game_id.in_(list(game_ids))).count() if game_ids else Event.query.count()
        orphan_shots = db.session.query(Shot).filter(~Shot.shot_id.in_(
            db.session.query(Event.event_id).filter(Event.game_id.in_(list(game_ids)))
        )).count() if game_ids else Shot.query.count()
        orphan_shifts = db.session.query(Shift).filter(~Shift.game_id.in_(list(game_ids))).count() if game_ids else Shift.query.count()
        
        if orphan_events > 0:
            diagnostics["game_ingestion"]["details"].append(f"{orphan_events} orphaned event record(s) found.")
        if orphan_shots > 0:
            diagnostics["game_ingestion"]["details"].append(f"{orphan_shots} orphaned shot record(s) found.")
        if orphan_shifts > 0:
            diagnostics["game_ingestion"]["details"].append(f"{orphan_shifts} orphaned shift record(s) found.")
            
        # Check for missing GamePlayer relations (Player in shifts/events but no GamePlayer row)
        players_in_shifts = db.session.query(Shift.game_id, Shift.player_id).filter(Shift.game_id.isnot(None), Shift.player_id.isnot(None)).distinct()
        active_player_games = set(players_in_shifts.all())
        for p_field in [Event.primary_player_id, Event.secondary_player_id, Event.assist1_player_id, Event.assist2_player_id]:
            pairs = db.session.query(Event.game_id, p_field).filter(Event.game_id.isnot(None), p_field.isnot(None)).distinct().all()
            for game_id, player_id in pairs:
                active_player_games.add((game_id, player_id))
                
        missing_gp = 0
        for g_id, p_id in active_player_games:
            exists = db.session.query(GamePlayer).filter_by(game_id=g_id, player_id=p_id).first()
            if not exists:
                missing_gp += 1
                
        if missing_gp > 0:
            diagnostics["game_ingestion"]["details"].append(f"{missing_gp} active player(s) missing GamePlayer records.")
            
        if len(diagnostics["game_ingestion"]["details"]) > 0:
            diagnostics["game_ingestion"]["status"] = "FAIL"
            
        # 2. Player Metadata Checks (Roster Mismatches)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        raw_data_dir = os.path.join(base_dir, 'data', 'raw')
        
        rosters_cache = {}
        def get_roster_player(team_abbr, season, player_id):
            key = (team_abbr, season)
            if key not in rosters_cache:
                rosters_cache[key] = {}
                filename = f"roster_{team_abbr}_{season}.json"
                filepath = os.path.join(raw_data_dir, filename)
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            for grp in ["forwards", "defensemen", "goalies"]:
                                for p in data.get(grp, []):
                                    rosters_cache[key][p.get("id")] = p
                    except Exception:
                        pass
            return rosters_cache[key].get(player_id)

        mismatches_count = 0
        players_db = Player.query.all()
        for p in players_db:
            gp_records = GamePlayer.query.filter_by(player_id=p.player_id).all()
            for gp in gp_records:
                game = gp.game
                team = gp.team
                if game and team:
                    r_player = get_roster_player(team.abbreviation, game.season, p.player_id)
                    if r_player:
                        r_pos = r_player.get("positionCode")
                        r_hand = r_player.get("shootsCatches")
                        
                        if p.position != r_pos:
                            mismatches_count += 1
                            diagnostics["player_metadata"]["details"].append(
                                f"Player metadata mismatch\n"
                                f"Player: {p.player_id} ({p.full_name})\n"
                                f"Stored position: {p.position}\n"
                                f"Roster position: {r_pos}"
                            )
                        if r_hand and p.shoots_catches != r_hand:
                            mismatches_count += 1
                            diagnostics["player_metadata"]["details"].append(
                                f"Player metadata mismatch\n"
                                f"Player: {p.player_id} ({p.full_name})\n"
                                f"Stored shoots/catches: {p.shoots_catches}\n"
                                f"Roster shoots/catches: {r_hand}"
                            )
                        break
                        
        if mismatches_count > 0:
            diagnostics["player_metadata"]["status"] = "FAIL"
            
        # 3. Shift Reconstruction Checks
        zero_duration_shifts = db.session.query(Shift).filter((Shift.duration == 0) | (Shift.is_anomaly == True)).count()
        negative_duration_shifts = db.session.query(Shift).filter(Shift.duration < 0).count()
        
        overlaps_count = 0
        all_players_with_shifts = db.session.query(Shift.player_id).distinct().all()
        for p_row in all_players_with_shifts:
            pid = p_row[0]
            player_shifts = Shift.query.filter_by(player_id=pid).order_by(Shift.game_id, Shift.period, Shift.start_elapsed_seconds).all()
            prev_shift = None
            for s in player_shifts:
                if prev_shift and prev_shift.game_id == s.game_id and prev_shift.period == s.period:
                    if s.start_elapsed_seconds < prev_shift.end_elapsed_seconds:
                        overlaps_count += 1
                prev_shift = s
                
        if negative_duration_shifts > 0:
            diagnostics["shift_reconstruction"]["details"].append(f"{negative_duration_shifts} negative duration shift(s) found.")
            diagnostics["shift_reconstruction"]["status"] = "FAIL"
        if overlaps_count > 0:
            diagnostics["shift_reconstruction"]["details"].append(f"{overlaps_count} overlapping shift(s) detected.")
            diagnostics["shift_reconstruction"]["status"] = "FAIL"
            
        if zero_duration_shifts > 0:
            diagnostics["shift_reconstruction"]["details"].append(f"{zero_duration_shifts} zero-duration shift(s) flagged as anomalies.")
            if diagnostics["shift_reconstruction"]["status"] == "PASS":
                diagnostics["shift_reconstruction"]["status"] = "WARNING"
                
        # 4. Boxscore Validation Checks
        from app.services.validation_service import ValidationService
        boxscore_failures = 0
        boxscore_missing = 0
        all_games = Game.query.all()
        for g in all_games:
            val = ValidationService.validate_game_boxscore(g.game_id)
            if not val:
                boxscore_missing += 1
                continue
                
            game_failed = False
            for check in ["goals_home", "goals_away", "shots_home", "shots_away", "pim_home", "pim_away"]:
                if check in val and val[check]["status"] == "FAIL":
                    game_failed = True
                    diagnostics["boxscore_validation"]["details"].append(
                        f"Boxscore mismatch for Game {g.game_id} ({g.season}) - Metric: {check.replace('_', ' ').upper()}.\n"
                        f"Calculated: {val[check]['calculated']}, NHL Boxscore: {val[check]['expected']}"
                    )
            for g_res in val.get("goalies", []):
                if g_res["status"] == "FAIL":
                    game_failed = True
                    diagnostics["boxscore_validation"]["details"].append(
                        f"Boxscore mismatch for Game {g.game_id} Goalie: {g_res['name']} (ID {g_res['player_id']}).\n"
                        f"Shots calculated: {g_res['shots_calculated']}, expected: {g_res['shots_expected']}\n"
                        f"Saves calculated: {g_res['saves_calculated']}, expected: {g_res['saves_expected']}"
                    )
            if game_failed:
                boxscore_failures += 1
                
        if boxscore_failures > 0:
            diagnostics["boxscore_validation"]["status"] = "FAIL"
        elif boxscore_missing > 0:
            diagnostics["boxscore_validation"]["details"].append(f"{boxscore_missing} game(s) missing cached boxscore JSON feeds.")
            diagnostics["boxscore_validation"]["status"] = "WARNING"
            
        # 5. 5v5 Reconstruction Checks
        calc_manpower_mismatch = db.session.query(Event).filter(
            Event.event_type.in_(['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']),
            Event.manpower_state == 'EV',
            Event.team_strength_state == '5v5',
            Event.raw_situation_code.isnot(None),
            Event.raw_situation_code != '1551'
        ).count()
        
        invalid_manpower = db.session.query(Event).filter(
            Event.event_type.in_(['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']),
            Event.manpower_state.in_([None, 'UNKNOWN'])
        ).count()
        
        if calc_manpower_mismatch > 0:
            diagnostics["five_v_five_reconstruction"]["details"].append(
                f"{calc_manpower_mismatch} 5v5 event(s) have mismatching raw situation codes."
            )
            diagnostics["five_v_five_reconstruction"]["status"] = "FAIL"
            
        if invalid_manpower > 0:
            diagnostics["five_v_five_reconstruction"]["details"].append(
                f"{invalid_manpower} event(s) have unresolved manpower states."
            )
            if diagnostics["five_v_five_reconstruction"]["status"] == "PASS":
                diagnostics["five_v_five_reconstruction"]["status"] = "WARNING"

        # 6. Shot Model Data Quality Checks (Milestone 15)
        shots_analyzed = db.session.query(Shot).count()
        missing_coords = db.session.query(Shot).filter(
            (Shot.x_coordinate_normalized.is_(None)) | (Shot.y_coordinate_normalized.is_(None))
        ).count()
        impossible_coords = db.session.query(Shot).filter(
            (Shot.x_coordinate_normalized.isnot(None)) & (
                (Shot.x_coordinate_normalized < -100) | (Shot.x_coordinate_normalized > 100) |
                (Shot.y_coordinate_normalized < -42.5) | (Shot.y_coordinate_normalized > 42.5)
            )
        ).count()
        coord_norm_failures = db.session.query(Shot).filter(
            (Shot.x_coordinate_normalized.isnot(None)) & (Shot.x_coordinate_normalized < 0)
        ).count()
        missing_shooters = db.session.query(Shot).filter(Shot.shooter_id.is_(None)).count()
        missing_goalies = db.session.query(Shot).filter(
            Shot.goalie_id.is_(None),
            Shot.empty_net == False,
            Shot.outcome.in_(['Goal', 'Saved'])
        ).count()
        unknown_shot_types = db.session.query(Shot).filter(
            (Shot.shot_type.is_(None)) | (Shot.shot_type.in_(['Unknown', 'other', '']))
        ).count()
        missing_times = db.session.query(Shot).join(Event).filter(
            Event.elapsed_game_seconds.is_(None)
        ).count()

        summary = {
            "shots_analyzed": shots_analyzed,
            "missing_coordinates": missing_coords,
            "impossible_coordinates": impossible_coords,
            "coordinate_normalization_failures": coord_norm_failures,
            "missing_shooters": missing_shooters,
            "missing_goalies": missing_goalies,
            "unknown_shot_types": unknown_shot_types,
            "missing_event_times": missing_times
        }

        diagnostics["shot_model_data_quality"] = {
            "status": "PASS",
            "details": [],
            "summary": summary
        }

        if missing_coords > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{missing_coords} shot(s) missing coordinates.")
        if impossible_coords > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{impossible_coords} shot(s) with coordinates out of rink bounds.")
            diagnostics["shot_model_data_quality"]["status"] = "FAIL"
        if missing_shooters > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{missing_shooters} shot(s) missing shooter IDs.")
            diagnostics["shot_model_data_quality"]["status"] = "FAIL"
        if missing_goalies > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{missing_goalies} shot(s) on goal missing goalie attribution.")
            if diagnostics["shot_model_data_quality"]["status"] == "PASS":
                diagnostics["shot_model_data_quality"]["status"] = "WARNING"
        if unknown_shot_types > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{unknown_shot_types} shot(s) with unknown or unclassified shot type.")
        if missing_times > 0:
            diagnostics["shot_model_data_quality"]["details"].append(f"{missing_times} shot(s) with missing game clocks.")
            diagnostics["shot_model_data_quality"]["status"] = "FAIL"
                
        return diagnostics
