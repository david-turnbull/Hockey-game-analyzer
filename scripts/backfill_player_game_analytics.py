import os
import sys
import argparse
import logging
import time
from flask import current_app

sys.path.insert(0, os.path.abspath("."))

from app.models import db, Game, PlayerGameAnalytics
from app.services.player_game_analytics_builder import PlayerGameAnalyticsBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("backfill_player_game_analytics")

def run_backfill(season: str = None, force: bool = False, batch_size: int = 50):
    ctx = None
    if not current_app:
        from app import create_app
        app = create_app()
        ctx = app.app_context()
        ctx.push()

    try:
        # Build query for target games
        query = db.session.query(Game.game_id, Game.season).order_by(Game.game_date.asc(), Game.game_id.asc())
        
        if season and season.lower() != 'all':
            query = query.filter(Game.season == season)
            
        all_games = query.all()
        total_games = len(all_games)
        
        if total_games == 0:
            logger.info("No games found matching criteria.")
            return

        logger.info(f"Starting historical backfill for {total_games} games (Season: {season or 'ALL'}, Force: {force})...")

        # Find games already built if force is False
        existing_game_ids = set()
        if not force:
            res = db.session.query(PlayerGameAnalytics.game_id).distinct().all()
            existing_game_ids = {r[0] for r in res}
            logger.info(f"Found {len(existing_game_ids)} games with existing derived analytics.")

        games_to_process = [g for g in all_games if force or g.game_id not in existing_game_ids]
        skipped_count = total_games - len(games_to_process)
        
        logger.info(f"Processing {len(games_to_process)} games ({skipped_count} skipped)...")

        processed_count = 0
        success_count = 0
        error_count = 0

        t0 = time.time()

        for i, g_row in enumerate(games_to_process, 1):
            gid = g_row.game_id
            try:
                records = PlayerGameAnalyticsBuilder.build_game_analytics(gid)
                success_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"Error building analytics for game {gid}: {e}")

            processed_count += 1

            if processed_count % batch_size == 0 or processed_count == len(games_to_process):
                elapsed = time.time() - t0
                rate = processed_count / elapsed if elapsed > 0 else 0
                logger.info(f"Progress: {processed_count}/{len(games_to_process)} games completed ({rate:.1f} games/sec) - Success: {success_count}, Errors: {error_count}")

        logger.info(f"Backfill complete! Total: {total_games}, Processed: {processed_count}, Skipped: {skipped_count}, Errors: {error_count}")
    finally:
        if ctx:
            ctx.pop()

def main():
    parser = argparse.ArgumentParser(description="PuckLens v1.5 Player-Game Analytics Historical Backfill Utility")
    parser.add_argument("--season", type=str, default="all", help="Target season (e.g. 20232024 or 'all')")
    parser.add_argument("--force", action="store_true", help="Force rebuild of games even if analytics exist")
    parser.add_argument("--batch-size", type=int, default=50, help="Progress logging batch size (default: 50)")
    args = parser.parse_args()

    run_backfill(season=args.season, force=args.force, batch_size=args.batch_size)

if __name__ == "__main__":
    main()
