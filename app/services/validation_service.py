import os
import json
import logging
from sqlalchemy import text
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, Team

logger = logging.getLogger(__name__)

class ValidationService:
    """Service class for validating database statistics against NHL boxscores and running diagnostic health checks."""

    @staticmethod
    def get_cached_boxscore(game_id: int) -> dict:
        """Helper to load cached boxscore JSON if available."""
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        filepath = os.path.join(base_dir, 'data', 'raw', f"boxscore_{game_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading cached boxscore {filepath}: {e}")
        return None

    @staticmethod
    def validate_game_boxscore(game_id: int) -> dict:
        """
        Cross-checks calculated stats from the database against official boxscore totals.
        Returns a dictionary containing check results or None if boxscore is missing.
        """
        game = db.session.get(Game, game_id)
        if not game:
            return None
            
        box = ValidationService.get_cached_boxscore(game_id)
        if not box:
            return None
            
        results = {}
        
        # 1. Score Validation (Goals)
        # Calculated: goals in Event table (excluding Shootout, period_type != 'SO')
        calc_goals_home = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'goal',
            Event.team_id == game.home_team_id,
            Event.period_type != 'SO'
        ).count()
        
        calc_goals_away = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'goal',
            Event.team_id == game.away_team_id,
            Event.period_type != 'SO'
        ).count()
        
        exp_goals_home = box.get("homeTeam", {}).get("score", 0)
        exp_goals_away = box.get("awayTeam", {}).get("score", 0)
        
        results["goals_home"] = {
            "calculated": calc_goals_home,
            "expected": exp_goals_home,
            "status": "PASS" if calc_goals_home == exp_goals_home else "FAIL"
        }
        results["goals_away"] = {
            "calculated": calc_goals_away,
            "expected": exp_goals_away,
            "status": "PASS" if calc_goals_away == exp_goals_away else "FAIL"
        }
        
        # 2. Shots on Goal Validation
        # Calculated SOG count is goals + saves, excluding Shootout
        calc_shots_home = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.team_id == game.home_team_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            Event.period_type != 'SO'
        ).count()
        
        calc_shots_away = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.team_id == game.away_team_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            Event.period_type != 'SO'
        ).count()
        
        exp_shots_home = box.get("homeTeam", {}).get("sog", 0)
        exp_shots_away = box.get("awayTeam", {}).get("sog", 0)
        
        results["shots_home"] = {
            "calculated": calc_shots_home,
            "expected": exp_shots_home,
            "status": "PASS" if calc_shots_home == exp_shots_home else "FAIL"
        }
        results["shots_away"] = {
            "calculated": calc_shots_away,
            "expected": exp_shots_away,
            "status": "PASS" if calc_shots_away == exp_shots_away else "FAIL"
        }
        
        # 3. Penalty Minutes (PIM)
        calc_pim_home = db.session.query(db.func.sum(Event.penalty_duration)).filter(
            Event.game_id == game_id,
            Event.team_id == game.home_team_id
        ).scalar() or 0
        
        calc_pim_away = db.session.query(db.func.sum(Event.penalty_duration)).filter(
            Event.game_id == game_id,
            Event.team_id == game.away_team_id
        ).scalar() or 0
        
        # Get expected PIMs from player stats
        exp_pim_home = 0
        exp_pim_away = 0
        
        stats = box.get("playerByGameStats", {})
        for grp in ["forwards", "defense", "goalies"]:
            for p in stats.get("homeTeam", {}).get(grp, []):
                exp_pim_home += p.get("pim", 0)
            for p in stats.get("awayTeam", {}).get(grp, []):
                exp_pim_away += p.get("pim", 0)
                
        results["pim_home"] = {
            "calculated": calc_pim_home,
            "expected": exp_pim_home,
            "status": "PASS" if calc_pim_home == exp_pim_home else "FAIL"
        }
        results["pim_away"] = {
            "calculated": calc_pim_away,
            "expected": exp_pim_away,
            "status": "PASS" if calc_pim_away == exp_pim_away else "FAIL"
        }
        
        # 4. Goalie Validation
        # Check shots and saves for each goalie who recorded stats in the boxscore
        goalie_results = []
        for team_key, team_id in [("homeTeam", game.home_team_id), ("awayTeam", game.away_team_id)]:
            for g_box in stats.get(team_key, {}).get("goalies", []):
                gid = g_box.get("playerId")
                if not gid:
                    continue
                # Skip back-ups who did not play
                exp_g_shots = g_box.get("shotsAgainst", 0)
                exp_g_saves = g_box.get("saves", 0)
                if exp_g_shots == 0 and g_box.get("toi", "00:00") == "00:00":
                    continue
                    
                calc_g_shots = db.session.query(Shot).join(Event).filter(
                    Event.game_id == game_id,
                    Shot.goalie_id == gid,
                    Shot.outcome.in_(['Goal', 'Saved']),
                    Event.period_type != 'SO'
                ).count()
                
                calc_g_saves = db.session.query(Shot).join(Event).filter(
                    Event.game_id == game_id,
                    Shot.goalie_id == gid,
                    Shot.outcome == 'Saved',
                    Event.period_type != 'SO'
                ).count()
                
                name = g_box.get("name", {}).get("default", f"Goalie {gid}")
                goalie_results.append({
                    "player_id": gid,
                    "name": name,
                    "shots_calculated": calc_g_shots,
                    "shots_expected": exp_g_shots,
                    "saves_calculated": calc_g_saves,
                    "saves_expected": exp_g_saves,
                    "status": "PASS" if (calc_g_shots == exp_g_shots and calc_g_saves == exp_g_saves) else "FAIL"
                })
        results["goalies"] = goalie_results
        
        return results

    @staticmethod
    def run_platform_diagnostics() -> dict:
        """
        Runs comprehensive platform diagnostics health check across 5 categories.
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
        # Compare database player attributes with cached team roster files if available
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        raw_data_dir = os.path.join(base_dir, 'data', 'raw')
        
        # Build cached roster lookup maps to speed up check
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

        # Loop through all players in database and check if we have season roster data
        mismatches_count = 0
        players_db = Player.query.all()
        for p in players_db:
            # Query GamePlayer records for seasons/teams they played in
            gp_records = GamePlayer.query.filter_by(player_id=p.player_id).all()
            for gp in gp_records:
                game = gp.game
                team = gp.team
                if game and team:
                    r_player = get_roster_player(team.abbreviation, game.season, p.player_id)
                    if r_player:
                        r_pos = r_player.get("positionCode")
                        r_hand = r_player.get("shootsCatches")
                        
                        # Compare position (p.position stores short code C, L, R, D, G)
                        # Boxscore / GamePlayer may override, but we check player's canonical table
                        if p.position != r_pos:
                            mismatches_count += 1
                            diagnostics["player_metadata"]["details"].append(
                                f"Player metadata mismatch\n"
                                f"Player: {p.player_id} ({p.full_name})\n"
                                f"Stored position: {p.position}\n"
                                f"Roster position: {r_pos}"
                            )
                        # Compare handedness
                        if r_hand and p.shoots_catches != r_hand:
                            mismatches_count += 1
                            diagnostics["player_metadata"]["details"].append(
                                f"Player metadata mismatch\n"
                                f"Player: {p.player_id} ({p.full_name})\n"
                                f"Stored shoots/catches: {p.shoots_catches}\n"
                                f"Roster shoots/catches: {r_hand}"
                            )
                        break # Check only one season to avoid duplicates
                        
        if mismatches_count > 0:
            diagnostics["player_metadata"]["status"] = "FAIL"
            
        # 3. Shift Reconstruction Checks
        zero_duration_shifts = db.session.query(Shift).filter((Shift.duration == 0) | (Shift.is_anomaly == True)).count()
        negative_duration_shifts = db.session.query(Shift).filter(Shift.duration < 0).count()
        
        # Detect overlaps
        # Simple overlap check: query shifts by player, order by elapsed time, check if start < previous end
        overlaps_count = 0
        all_players_with_shifts = db.session.query(Shift.player_id).distinct().all()
        for p_row in all_players_with_shifts:
            pid = p_row[0]
            player_shifts = Shift.query.filter_by(player_id=pid).order_by(Shift.game_id, Shift.period, Shift.start_elapsed_seconds).all()
            prev_shift = None
            for s in player_shifts:
                if prev_shift and prev_shift.game_id == s.game_id and prev_shift.period == s.period:
                    # Check if they overlap
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
            # If there are overlaps/negatives, status is already FAIL. Otherwise, PASS with warnings.
            if diagnostics["shift_reconstruction"]["status"] == "PASS":
                diagnostics["shift_reconstruction"]["status"] = "WARNING"
                
        # 4. Boxscore Validation Checks
        # Run validate_game_boxscore on all games in the DB
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
            # Check goalies
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
        # Verify 5v5 event manpower state corresponds to calculated manpower
        # For shot/goal events in 5v5, check if raw situation code matches '1551'
        calc_manpower_mismatch = db.session.query(Event).filter(
            Event.event_type.in_(['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']),
            Event.manpower_state == 'EV',
            Event.team_strength_state == '5v5',
            Event.raw_situation_code.isnot(None),
            Event.raw_situation_code != '1551'
        ).count()
        
        # Verify events with invalid/unknown manpower states
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
                
        return diagnostics
