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
from app.services.player_game_analytics_audit import audit_game_analytics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backfill_player_game_analytics")

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
