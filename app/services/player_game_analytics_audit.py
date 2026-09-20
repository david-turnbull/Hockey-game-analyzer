import logging
from typing import Dict, Any, List, Optional
from sqlalchemy import func
from app.models import db, Game, Player, GamePlayer, PlayerGameAnalytics

logger = logging.getLogger(__name__)

class PlayerGameAnalyticsAuditService:
    """
    Service for auditing player game analytics completeness and verifying
    season-wide readiness for derived query paths.
    """

    @classmethod
    def audit_game_analytics(cls, season: Optional[str] = None) -> Dict[str, Any]:
        """
        Audits derived player game analytics completeness across games by comparing expected
        non-goalie GamePlayer count against actual PlayerGameAnalytics row count per game.

        Returns:
            Dict with keys:
                'complete': List[int] (game_ids where expected_count > 0 and actual_count == expected_count)
                'incomplete': List[int] (game_ids where actual_count > 0 and actual_count != expected_count)
                'missing': List[int] (game_ids where actual_count == 0)
                'expected_counts': Dict[int, int]
                'actual_counts': Dict[int, int]
        """
        # Query target games
        game_query = db.session.query(Game.game_id).order_by(Game.game_date.asc(), Game.game_id.asc())
        if season and season.lower() != 'all':
            game_query = game_query.filter(Game.season == season)
        target_game_ids = [r[0] for r in game_query.all()]

        if not target_game_ids:
            return {
                "complete": [], "incomplete": [], "missing": [],
                "expected_counts": {}, "actual_counts": {}
            }

        # Expected non-goalie skater count per game from GamePlayer
        gp_query = (
            db.session.query(
                GamePlayer.game_id,
                func.count(GamePlayer.player_id)
            )
            .join(Player, GamePlayer.player_id == Player.player_id)
            .filter(
                GamePlayer.game_id.in_(target_game_ids),
                Player.position != 'G'
            )
            .group_by(GamePlayer.game_id)
        )
        expected_counts = {gid: cnt for gid, cnt in gp_query.all()}

        # Actual PlayerGameAnalytics row count per game
        pga_query = (
            db.session.query(
                PlayerGameAnalytics.game_id,
                func.count(PlayerGameAnalytics.player_id)
            )
            .filter(PlayerGameAnalytics.game_id.in_(target_game_ids))
            .group_by(PlayerGameAnalytics.game_id)
        )
        actual_counts = {gid: cnt for gid, cnt in pga_query.all()}

        complete = []
        incomplete = []
        missing = []

        for gid in target_game_ids:
            exp = expected_counts.get(gid, 0)
            act = actual_counts.get(gid, 0)

            if act == 0:
                missing.append(gid)
            elif exp > 0 and act == exp:
                complete.append(gid)
            else:
                incomplete.append(gid)

        return {
            "complete": complete,
            "incomplete": incomplete,
            "missing": missing,
            "expected_counts": expected_counts,
            "actual_counts": actual_counts
        }

    @classmethod
    def is_season_complete(cls, season: str) -> bool:
        """
        Checks whether a target season is fully backfilled and 100% complete according to audit rules:
        - Must have at least 1 game with expected skater data.
        - Must have 0 missing games.
        - Must have 0 incomplete games.
        """
        res = cls.audit_game_analytics(season=season)
        complete = res["complete"]
        incomplete = res["incomplete"]
        missing = res["missing"]

        if not complete:
            return False
        if len(incomplete) > 0 or len(missing) > 0:
            return False

        return True

def audit_game_analytics(season: Optional[str] = None) -> Dict[str, Any]:
    return PlayerGameAnalyticsAuditService.audit_game_analytics(season=season)
