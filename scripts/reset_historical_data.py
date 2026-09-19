import os
import sys
import argparse
import logging

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Game, Team, Player, Event, Shot, Shift, GamePlayer, GamePrediction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def reset_historical_data(confirm: bool = False):
    if not confirm:
        logger.error("SAFETY GATE BLOCKED: --confirm flag is required to reset historical data.")
        print("ERROR: Safety flag --confirm is required to reset historical database records.")
        print("Usage: python scripts/reset_historical_data.py --confirm")
        sys.exit(1)

    app = create_app('development')
    with app.app_context():
        logger.warning("Resetting historical database records...")

        deleted_counts = {}

        # Delete dependent child tables first
        for model, name in [
            (GamePrediction, "GamePrediction"),
            (Shift, "Shift"),
            (Shot, "Shot"),
            (Event, "Event"),
            (GamePlayer, "GamePlayer"),
            (Game, "Game"),
        ]:
            count = db.session.query(model).delete()
            deleted_counts[name] = count
            logger.info(f"Deleted {count} records from {name}")

        db.session.commit()
        logger.info("Historical data reset complete.")
        print("Historical database reset completed successfully:")
        for name, count in deleted_counts.items():
            print(f"  - {name}: {count} records removed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PuckLens Historical Data Reset Utility")
    parser.add_argument("--confirm", action="store_true", help="Explicit confirmation to clear all game data")
    args = parser.parse_args()

    reset_historical_data(confirm=args.confirm)
