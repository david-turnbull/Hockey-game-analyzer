import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app.models import db, Game, GamePrediction
from app.services.forecast_service import ForecastService

logger = logging.getLogger(__name__)

class PredictionGeneratorService:
    """
    Idempotent, race-safe official pregame prediction generator service.
    Enforces strict pre-puck-drop cutoff (now_utc < start_time_utc) and atomic transactions.
    """

    @classmethod
    def generate_official_pregame_predictions(
        cls,
        season: Optional[str] = None,
        lookahead_hours: Optional[int] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Scans upcoming regular-season games within lookahead_hours and generates official pregame predictions.
        Race-safe and idempotent: handles concurrent parallel workers via IntegrityError rollback.
        """
        from flask import current_app

        if lookahead_hours is None:
            try:
                lookahead_hours = current_app.config.get("FORECAST_DEFAULT_LOOKAHEAD_HOURS", 48)
            except Exception:
                lookahead_hours = 48

        now_utc = datetime.now(timezone.utc)
        max_start_utc = now_utc + timedelta(hours=lookahead_hours)

        query = Game.query.options(
            joinedload(Game.home_team),
            joinedload(Game.away_team)
        ).filter(
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.start_time_utc > now_utc,
            Game.start_time_utc <= max_start_utc
        )

        if season:
            query = query.filter(Game.season == season)

        games = query.order_by(Game.start_time_utc.asc(), Game.game_id.asc()).all()

        game_ids = [g.game_id for g in games]
        existing_official_ids = set(
            row[0] for row in db.session.query(GamePrediction.game_id).filter(
                GamePrediction.prediction_type == 'official_pregame',
                GamePrediction.game_id.in_(game_ids)
            ).all()
        ) if game_ids else set()

        generated_ids = []
        skipped_existing = []
        rejected_cutoff = []
        errors = []

        for g in games:
            # Check existing official_pregame prediction snapshot
            if g.game_id in existing_official_ids:
                skipped_existing.append(g.game_id)
                continue

            # Strict cutoff check
            g_start = g.start_time_utc
            if g_start.tzinfo is None:
                g_start = g_start.replace(tzinfo=timezone.utc)

            if now_utc >= g_start:
                rejected_cutoff.append(g.game_id)
                logger.warning(f"Skipping prediction for game {g.game_id}: started at {g_start.isoformat()}")
                continue

            if dry_run:
                generated_ids.append(g.game_id)
                continue

            # Generate prediction race-safely
            try:
                res = ForecastService.create_prediction(g.game_id, prediction_type='official_pregame')
                if "error" in res:
                    errors.append({"game_id": g.game_id, "error": res["error"], "message": res.get("message")})
                else:
                    generated_ids.append(g.game_id)
                    logger.info(f"Generated official pregame prediction for game {g.game_id}")
            except IntegrityError:
                db.session.rollback()
                skipped_existing.append(g.game_id)
                logger.info(f"Concurrent generator race handled for game {g.game_id}; existing prediction retained.")
            except Exception as e:
                db.session.rollback()
                logger.exception(f"Failed to generate prediction for game {g.game_id}: {e}")
                errors.append({"game_id": g.game_id, "error": "EXCEPTION", "message": str(e)})

        return {
            "executed_at": now_utc.isoformat(),
            "lookahead_hours": lookahead_hours,
            "dry_run": dry_run,
            "total_games_scanned": len(games),
            "generated_count": len(generated_ids),
            "skipped_existing_count": len(skipped_existing),
            "rejected_cutoff_count": len(rejected_cutoff),
            "error_count": len(errors),
            "generated_game_ids": generated_ids,
            "errors": errors
        }
