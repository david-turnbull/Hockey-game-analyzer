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
        Delegates validation to DataIntegrityService.
        """
        from app.services.data_integrity_service import DataIntegrityService
        return DataIntegrityService.run_diagnostic_checks()
