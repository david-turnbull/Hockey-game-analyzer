from app.models import db, Game, Player, Shift, GamePlayer
from app.services.player_profile_service import PlayerProfileService
from app.services.player_timeline_service import PlayerTimelineService
from app.services.goalie_stats_service import GoalieStatsService
from app.services.skater_stats_service import SkaterStatsService
from app.services.on_ice_service import OnIceService

class PlayerGameService:
    """Service handling detailed statistics, timelines, and shift charts for players per game."""

    @staticmethod
    def get_player_game_stats(game_id: int, player_id: int) -> dict:
        """
        Retrieves detailed statistics, visual chart data, and timeline
        events for a specific player in a specific game.
        Coordinates and delegates to modular sub-services.
        """
        game = db.session.get(Game, game_id)
        player = db.session.get(Player, player_id)
        
        if not game or not player:
            return None
            
        home_team = game.home_team
        away_team = game.away_team
        
        # Resolve historical game-player team and position assignment authoritatively
        gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
        
        profile = PlayerProfileService.resolve_profile_metadata(game, player, gp)
        
        # Fetch shifts
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.player_id == player_id
        ).order_by(Shift.period.asc(), Shift.start_elapsed_seconds.asc()).all()
        
        # Calculate TOI and Shift metrics using centralized OnIceService validity rules
        valid_shifts = [s for s in shifts if OnIceService.is_valid_shift(s)]
        valid_shift_count = len(valid_shifts)
        raw_shift_count = len(shifts)
        toi_seconds = sum(s.duration for s in valid_shifts)
        
        # Average shift length using only valid shifts
        avg_shift_seconds = int(toi_seconds / valid_shift_count) if valid_shift_count > 0 else 0
        
        # Format TOI helper
        def format_toi(total_seconds):
            mins = total_seconds // 60
            secs = total_seconds % 60
            return f"{mins:02d}:{secs:02d}"
            
        toi_str = format_toi(toi_seconds)
        avg_shift_str = format_toi(avg_shift_seconds)
        
        # Fetch player events for timeline (delegated to timeline service)
        timeline = PlayerTimelineService.get_player_timeline(
            game_id, player_id, game.home_team_id, home_team.abbreviation, away_team.abbreviation
        )
        
        stats = {
            "player_id": profile["player_id"],
            "name": profile["name"],
            "position": profile["position"],
            "shoots_catches": profile["shoots_catches"],
            "headshot_url": profile["headshot_url"],
            "sweater_number": profile["sweater_number"],
            "height_str": profile["height_str"],
            "weight_str": profile["weight_str"],
            "birth_date": profile["birth_date"],
            "birth_city": profile["birth_city"],
            "birth_country": profile["birth_country"],
            "team_name": profile["team_name"],
            "team_abbrev": profile["team_abbrev"],
            "team_id": profile["team_id"],
            "is_home": profile["is_home"],
            "game_id": game.game_id,
            "game_date": game.game_date,
            "game_status": game.game_status,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "home_team_abbrev": home_team.abbreviation,
            "away_team_abbrev": away_team.abbreviation,
            "toi": toi_str,
            "shifts_count": valid_shift_count,
            "raw_shifts_count": raw_shift_count,
            "avg_shift": avg_shift_str,
            "timeline": timeline,
            # Shift chart data
            "shifts_chart": [
                {
                    "period": s.period,
                    "period_type": s.period_type,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "start_seconds": s.start_elapsed_seconds - (s.period - 1) * 1200 if s.start_elapsed_seconds is not None else 0,
                    "end_seconds": s.end_elapsed_seconds - (s.period - 1) * 1200 if s.end_elapsed_seconds is not None else 0,
                    "duration": s.duration,
                    "is_anomaly": s.is_anomaly
                } for s in shifts
            ]
        }
        
        # Goalie vs. Skater metrics delegation
        if profile["position"] == 'G':
            goalie_stats = GoalieStatsService.calculate_goalie_stats(game_id, player_id)
            stats.update(goalie_stats)
        else:
            skater_stats = SkaterStatsService.calculate_skater_stats(game_id, player_id)
            stats.update(skater_stats)
            
        return stats
