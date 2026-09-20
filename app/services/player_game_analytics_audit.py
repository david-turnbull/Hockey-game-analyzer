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
                'total_game_rows': Total Game schedule rows for season.
                'ingested_games': Count of games with ingested GamePlayer roster records.
                'complete': List[int] (game_ids where expected_count > 0 and actual_count == expected_count)
                'incomplete': List[int] (game_ids where actual_count > 0 and actual_count != expected_count)
                'missing': List[int] (game_ids where actual_count == 0)
                'derived_coverage_pct': float (complete / ingested_games * 100)
                'expected_counts': Dict[int, int]
                'actual_counts': Dict[int, int]
        """
        # 1. Total Game schedule rows for season
        total_game_query = db.session.query(Game.game_id)
        if season and season.lower() != 'all':
            total_game_query = total_game_query.filter(Game.season == season)
        total_game_rows = total_game_query.count()

        # 2. Ingested games that have GamePlayer roster records
        gp_games_query = (
            db.session.query(GamePlayer.game_id)
            .join(Game, GamePlayer.game_id == Game.game_id)
            .distinct()
            .order_by(GamePlayer.game_id.asc())
        )
        if season and season.lower() != 'all':
            gp_games_query = gp_games_query.filter(Game.season == season)
        target_game_ids = [r[0] for r in gp_games_query.all()]

        ingested_games = len(target_game_ids)
        if ingested_games == 0:
            return {
                "total_game_rows": total_game_rows,
                "ingested_games": 0,
                "complete": [], "incomplete": [], "missing": [],
                "derived_coverage_pct": 0.0,
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

        coverage_pct = round((len(complete) / ingested_games * 100.0), 2) if ingested_games > 0 else 0.0

        return {
            "total_game_rows": total_game_rows,
            "ingested_games": ingested_games,
            "complete": complete,
            "incomplete": incomplete,
            "missing": missing,
            "derived_coverage_pct": coverage_pct,
            "expected_counts": expected_counts,
            "actual_counts": actual_counts
        }

    @classmethod
    def is_derived_coverage_complete(cls, season: str) -> bool:
        """
        Fast check to verify whether derived coverage is 100% complete across all ingested games in a season:
        - Compares distinct ingested game count in GamePlayer vs distinct game count in PlayerGameAnalytics.
        """
        has_pga = (
            db.session.query(PlayerGameAnalytics.game_id)
            .filter(PlayerGameAnalytics.season == season)
            .first() is not None
        )
        if not has_pga:
            return False

        subq = db.session.query(Game.game_id).filter(Game.season == season)
        gp_games_cnt = (
            db.session.query(func.count(func.distinct(GamePlayer.game_id)))
            .filter(GamePlayer.game_id.in_(subq))
            .scalar() or 0
        )
        if gp_games_cnt == 0:
            return False

        pga_games_cnt = (
            db.session.query(func.count(func.distinct(PlayerGameAnalytics.game_id)))
            .filter(PlayerGameAnalytics.season == season)
            .scalar() or 0
        )

        return gp_games_cnt == pga_games_cnt

    @classmethod
    def is_season_complete(cls, season: str) -> bool:
        """Compatibility wrapper for is_derived_coverage_complete."""
        return cls.is_derived_coverage_complete(season=season)

def audit_game_analytics(season: Optional[str] = None) -> Dict[str, Any]:
    return PlayerGameAnalyticsAuditService.audit_game_analytics(season=season)
