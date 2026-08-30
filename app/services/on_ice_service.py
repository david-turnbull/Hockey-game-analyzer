from sqlalchemy.orm import joinedload
from app.models import db, Shift, Player

class OnIceService:
    """Authoritative service for determining which players are active on the ice at any given second."""

    @staticmethod
    def get_players_on_ice(game_id: int, elapsed_seconds: int, team_id: int = None) -> list:
        """
        Retrieves structured player information for all players on the ice at a specific second.
        Implements the half-open interval convention [start, end) and centralizes shift validity rules.
        """
        if elapsed_seconds is None or elapsed_seconds < 0:
            return []

        # Query database shifts covering the elapsed_seconds time
        query = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.start_elapsed_seconds <= elapsed_seconds,
            elapsed_seconds < Shift.end_elapsed_seconds,
            Shift.is_anomaly == False,
            Shift.duration > 0,
            Shift.start_elapsed_seconds.isnot(None),
            Shift.end_elapsed_seconds.isnot(None)
        )

        if team_id is not None:
            query = query.filter(Shift.team_id == team_id)

        shifts = query.options(joinedload(Shift.player)).all()
        
        results = []
        for s in shifts:
            results.append({
                "player_id": s.player_id,
                "team_id": s.team_id,
                "position": s.player.position if s.player else "skater",
                "full_name": s.player.full_name if s.player else f"Unknown Player {s.player_id}"
            })
        return results

    @staticmethod
    def is_valid_shift(s) -> bool:
        """
        Authoritative check for shift validity.
        A shift is valid if it has valid timestamps, is not anomalous, and has a positive duration.
        """
        if s.start_elapsed_seconds is None or s.end_elapsed_seconds is None:
            return False
        if s.is_anomaly or s.duration is None or s.duration <= 0:
            return False
        return True

    @staticmethod
    def filter_active_shifts(shifts: list, elapsed_seconds: int, team_id: int = None) -> list:
        """
        In-memory filtering of a pre-loaded shift collection for a specific second.
        Applies identical shift validity rules and the half-open [start, end) interval convention.
        Designed to optimize bulk processing loops (such as line combinations or possession metrics).
        """
        if elapsed_seconds is None or elapsed_seconds < 0:
            return []

        active = []
        for s in shifts:
            if not OnIceService.is_valid_shift(s):
                continue
            if s.start_elapsed_seconds <= elapsed_seconds < s.end_elapsed_seconds:
                if team_id is None or s.team_id == team_id:
                    active.append(s)
        return active

    @staticmethod
    def build_active_players_timeline(shifts: list, max_time: int, home_team_id: int) -> tuple:
        """
        Builds second-by-second active player collections for both teams, pre-calculating
        them in a single pass to optimize bulk analysis (like line combinations).
        All rules (valid shifts and half-open [start, end) intervals) are owned here.
        """
        home_players = [set() for _ in range(max_time + 2)]
        away_players = [set() for _ in range(max_time + 2)]
        
        for s in shifts:
            if not OnIceService.is_valid_shift(s):
                continue
                
            start = max(0, s.start_elapsed_seconds)
            end = min(max_time, s.end_elapsed_seconds)
            
            for t in range(start, end):
                if s.team_id == home_team_id:
                    home_players[t].add(s.player_id)
                else:
                    away_players[t].add(s.player_id)
                    
        return home_players, away_players

    @staticmethod
    def get_skaters_on_ice(game_id: int, elapsed_seconds: int, team_id: int = None) -> list:
        """Helper to retrieve active skaters on the ice (excluding goalies)."""
        players = OnIceService.get_players_on_ice(game_id, elapsed_seconds, team_id)
        return [p for p in players if p["position"] != "G"]

    @staticmethod
    def get_goalie_on_ice(game_id: int, elapsed_seconds: int, team_id: int = None) -> list:
        """Helper to retrieve active goalie(s) on the ice."""
        players = OnIceService.get_players_on_ice(game_id, elapsed_seconds, team_id)
        return [p for p in players if p["position"] == "G"]

    @staticmethod
    def period_time_to_game_elapsed(period: int, period_time_str: str) -> int:
        """
        Converts a period-specific time string (MM:SS) into game-elapsed seconds.
        E.g. period 1, "01:00" -> 60
             period 2, "01:00" -> 1260
        """
        if not period_time_str or ':' not in period_time_str:
            return 0
        try:
            parts = period_time_str.split(':')
            minutes = int(parts[0])
            seconds = int(parts[1])
            elapsed_seconds = (period - 1) * 1200 + minutes * 60 + seconds
            return elapsed_seconds
        except ValueError:
            return 0
