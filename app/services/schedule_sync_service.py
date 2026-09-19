import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from app.models import db, Game

logger = logging.getLogger(__name__)

class ScheduleSyncService:
    """
    Service for auditing schedule data freshness, start-time completion,
    and syncing official game schedules from NHL API.
    """

    @classmethod
    def check_schedule_freshness(cls, season: str = "20242025") -> Dict[str, Any]:
        """
        Audits schedule integrity and timestamp completion for a given season.
        """
        now_utc = datetime.now(timezone.utc)
        games = Game.query.filter(
            Game.season == season,
            Game.game_type == 'R',
            Game.data_source == 'nhl_api'
        ).all()

        total_games = len(games)
        missing_start_time = [g.game_id for g in games if not g.start_time_utc]
        upcoming_games = [g for g in games if g.start_time_utc and (g.start_time_utc.replace(tzinfo=timezone.utc) if g.start_time_utc.tzinfo is None else g.start_time_utc) > now_utc]

        is_fresh = (total_games > 0 and len(missing_start_time) == 0)

        return {
            "season": season,
            "total_games": total_games,
            "missing_start_time_count": len(missing_start_time),
            "missing_start_time_game_ids": missing_start_time,
            "upcoming_games_count": len(upcoming_games),
            "is_fresh": is_fresh,
            "checked_at": now_utc.isoformat()
        }

    @classmethod
    def sync_upcoming_schedule(cls, team_abbr: str, season: str) -> Dict[str, Any]:
        """
        Synchronizes upcoming game start times and states for a team and season from NHLApiClient.
        """
        try:
            from data_pipeline.ingest.nhl_api import NHLApiClient
            api_client = NHLApiClient()
            schedule_data = api_client.get_season_schedule(team_abbr, season)
        except Exception as e:
            logger.error(f"Failed to fetch schedule for {team_abbr} {season}: {e}")
            return {"success": False, "error": str(e)}

        if not schedule_data or "games" not in schedule_data:
            return {"success": True, "updated_count": 0}

        updated_count = 0
        reg_games = [g for g in schedule_data["games"] if g.get("gameType") == 2]

        for g_data in reg_games:
            game_id = g_data.get("id")
            if not game_id:
                continue

            game_db = db.session.get(Game, game_id)
            if not game_db:
                continue

            start_utc_str = g_data.get("startTimeUTC")
            if start_utc_str:
                try:
                    dt = datetime.fromisoformat(start_utc_str.replace("Z", "+00:00"))
                    if game_db.start_time_utc != dt:
                        game_db.start_time_utc = dt
                        updated_count += 1
                except Exception as ex:
                    logger.warning(f"Could not parse startTimeUTC '{start_utc_str}' for game {game_id}: {ex}")

            game_state = g_data.get("gameState")
            if game_state and game_db.nhl_game_state != game_state:
                game_db.nhl_game_state = game_state
                updated_count += 1

        if updated_count > 0:
            db.session.commit()
            logger.info(f"Updated schedule for {updated_count} games for team {team_abbr} {season}.")

        return {"success": True, "updated_count": updated_count}
