import os
import sys
import argparse
import logging
import time
from typing import Dict, Any, List
from flask import current_app
from sqlalchemy import func

sys.path.insert(0, os.path.abspath("."))

from app.models import db, Game, Player, GamePlayer, PlayerGameAnalytics
from app.services.player_game_analytics_builder import PlayerGameAnalyticsBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backfill_player_game_analytics")

def audit_game_analytics(season: str = None) -> Dict[str, Any]:
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
    ctx = None
    if not current_app:
        from app import create_app
        app = create_app()
        ctx = app.app_context()
        ctx.push()

    try:
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
    finally:
        if ctx:
            ctx.pop()

def run_backfill(season: str = None, force: bool = False, batch_size: int = 50) -> Dict[str, Any]:
    """
    Runs historical backfill and automatic repair for player game analytics.
    
    If force is False, completeness detection checks actual vs expected non-goalie skater rows per game:
    - Skips fully complete games.
    - Automatically repairs missing and incomplete (partially built) games.
    
    Returns:
        Summary dict containing counts for complete, missing, incomplete, repaired, failed, and total games.
    """
    ctx = None
    if not current_app:
        from app import create_app
        app = create_app()
        ctx = app.app_context()
        ctx.push()

    try:
        # Audit completeness
        audit_res = audit_game_analytics(season=season)
        complete_ids = audit_res["complete"]
        incomplete_ids = audit_res["incomplete"]
        missing_ids = audit_res["missing"]

        all_target_ids = complete_ids + incomplete_ids + missing_ids
        total_games = len(all_target_ids)

        if total_games == 0:
            logger.info("No games found matching criteria.")
            return {
                "total": 0, "complete": 0, "missing": 0,
                "incomplete": 0, "repaired": 0, "failed": 0, "skipped": 0
            }

        logger.info(f"--- Player-Game Analytics Backfill Audit (Season: {season or 'ALL'}) ---")
        logger.info(f"Total Target Games: {total_games}")
        logger.info(f"  -> Complete: {len(complete_ids)}")
        logger.info(f"  -> Incomplete (partial): {len(incomplete_ids)}")
        logger.info(f"  -> Missing (unbuilt): {len(missing_ids)}")

        if force:
            games_to_process = all_target_ids
            skipped_ids = []
            logger.info("Force flag enabled: Rebuilding ALL games regardless of status.")
        else:
            games_to_process = missing_ids + incomplete_ids
            skipped_ids = complete_ids
            logger.info(f"Processing {len(games_to_process)} games ({len(skipped_ids)} complete games skipped)...")

        processed_count = 0
        repaired_count = 0
        failed_count = 0

        t0 = time.time()

        for i, gid in enumerate(games_to_process, 1):
            try:
                records = PlayerGameAnalyticsBuilder.build_game_analytics(gid)
                repaired_count += 1
            except Exception as e:
                failed_count += 1
                logger.error(f"Error building analytics for game {gid}: {e}")

            processed_count += 1

            if processed_count % batch_size == 0 or processed_count == len(games_to_process):
                elapsed = time.time() - t0
                rate = processed_count / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress: {processed_count}/{len(games_to_process)} games "
                    f"({rate:.1f} games/sec) - Repaired: {repaired_count}, Failed: {failed_count}"
                )

        summary = {
            "total": total_games,
            "complete_initial": len(complete_ids),
            "missing_initial": len(missing_ids),
            "incomplete_initial": len(incomplete_ids),
            "processed": processed_count,
            "skipped": len(skipped_ids),
            "repaired": repaired_count,
            "failed": failed_count
        }

        logger.info(f"--- Backfill Summary ---")
        logger.info(f"Total: {total_games} | Skipped Complete: {len(skipped_ids)} | Repaired: {repaired_count} | Failed: {failed_count}")
        return summary
    finally:
        if ctx:
            ctx.pop()

def main():
    parser = argparse.ArgumentParser(description="PuckLens v1.5 Player-Game Analytics Historical Backfill Utility")
    parser.add_argument("--season", type=str, default="all", help="Target season (e.g. 20232024 or 'all')")
    parser.add_argument("--force", action="store_true", help="Force rebuild of games even if analytics exist")
    parser.add_argument("--audit", action="store_true", help="Audit analytics completeness without rebuilding")
    parser.add_argument("--batch-size", type=int, default=50, help="Progress logging batch size (default: 50)")
    args = parser.parse_args()

    if args.audit:
        res = audit_game_analytics(season=args.season)
        print("\n=== PuckLens Player-Game Analytics Completeness Audit ===")
        print(f"Season: {args.season}")
        print(f"Total Games Analyzed: {len(res['complete']) + len(res['incomplete']) + len(res['missing'])}")
        print(f"  -> Complete Games: {len(res['complete'])}")
        print(f"  -> Incomplete Games (Partial): {len(res['incomplete'])}")
        print(f"  -> Missing Games (Unbuilt): {len(res['missing'])}")
        if res['incomplete']:
            print(f"Incomplete Game IDs: {res['incomplete']}")
        if res['missing']:
            print(f"Missing Game IDs (first 20): {res['missing'][:20]}")
    else:
        run_backfill(season=args.season, force=args.force, batch_size=args.batch_size)

if __name__ == "__main__":
    main()
