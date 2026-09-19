#!/usr/bin/env python
"""
Automated CLI command for generating official pregame predictions for upcoming games.
Intended for execution via external automation (cron / scheduler).
"""

import sys
import os
import json
import argparse
import logging

# Add root directory to sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.services.prediction_generator_service import PredictionGeneratorService

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="Generate official pregame predictions for upcoming NHL games.")
    parser.add_argument("--season", type=str, default=None, help="Target season (e.g., 20242025)")
    parser.add_argument("--lookahead-hours", type=int, default=48, help="Lookahead window in hours (default: 48)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate prediction generation without writing to database")

    args = parser.parse_args()

    app = create_app("production" if os.environ.get("FLASK_ENV") == "production" else "development")
    with app.app_context():
        logger.info(f"Starting official pregame prediction generation (lookahead={args.lookahead_hours}h, dry_run={args.dry_run})...")
        summary = PredictionGeneratorService.generate_official_pregame_predictions(
            season=args.season,
            lookahead_hours=args.lookahead_hours,
            dry_run=args.dry_run
        )
        print(json.dumps(summary, indent=2))

        if summary["error_count"] > 0:
            logger.error(f"Prediction generation completed with {summary['error_count']} errors.")
            sys.exit(1)
        else:
            logger.info(f"Prediction generation completed successfully. Generated: {summary['generated_count']}, Skipped: {summary['skipped_existing_count']}.")
            sys.exit(0)

if __name__ == "__main__":
    main()
