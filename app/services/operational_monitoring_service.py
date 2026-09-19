import logging
import math
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import joinedload

from app.models import db, Game, GamePrediction, Event
from app.analytics.forecasting.model_registry import ForecastModelRegistry, ModelUnavailableError

logger = logging.getLogger(__name__)

MIN_SAMPLE_THRESHOLD_DEFAULT = 30
EPSILON = 1e-15

class OperationalMonitoringService:
    """
    Service providing sample-aware operational monitoring strictly over persisted predictions.
    Does NOT invoke feature generation or model inference.
    """

    @classmethod
    def get_active_model_status(cls) -> Dict[str, Any]:
        """
        Returns status and metadata for active production model.
        """
        try:
            _, manifest = ForecastModelRegistry.load_active_model()
            return {
                "status": "ACTIVE",
                "model_version": manifest.get("model_version"),
                "artifact_sha256": manifest.get("artifact_sha256"),
                "feature_schema_version": manifest.get("feature_schema_version", "v1"),
                "trained_at": manifest.get("trained_at"),
                "training_sample_count": manifest.get("training_sample_count")
            }
        except ModelUnavailableError as e:
            return {
                "status": "UNAVAILABLE",
                "error": str(e)
            }

    @classmethod
    def get_coverage_summary(cls) -> Dict[str, Any]:
        """
        Calculates official pregame prediction coverage, upcoming game prediction status,
        and unresolved predictions strictly from persisted records.
        """
        now_utc = datetime.now(timezone.utc)

        # Query all official predictions
        official_preds = GamePrediction.query.filter_by(prediction_type='official_pregame').all()
        total_official_preds = len(official_preds)

        # Count per model version and SHA
        by_version = {}
        for p in official_preds:
            key = (p.model_version, p.model_sha256 or "unknown")
            by_version[key] = by_version.get(key, 0) + 1

        version_breakdown = [
            {"model_version": k[0], "model_sha256": k[1], "count": v}
            for k, v in by_version.items()
        ]

        # Query upcoming games
        upcoming_games = Game.query.filter(
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.start_time_utc > now_utc
        ).all()

        upcoming_game_ids = {g.game_id for g in upcoming_games}
        predicted_upcoming_ids = {p.game_id for p in official_preds if p.game_id in upcoming_game_ids}
        missing_upcoming_ids = upcoming_game_ids - predicted_upcoming_ids

        # Unresolved games (games finished or in progress that have predictions)
        unresolved_preds = [p for p in official_preds if not p.is_outcome_resolved]

        return {
            "audited_at": now_utc.isoformat(),
            "total_official_predictions": total_official_preds,
            "version_breakdown": version_breakdown,
            "upcoming_games_total": len(upcoming_games),
            "upcoming_games_predicted": len(predicted_upcoming_ids),
            "upcoming_games_missing_prediction": len(missing_upcoming_ids),
            "missing_upcoming_game_ids": sorted(list(missing_upcoming_ids)),
            "unresolved_official_predictions_count": len(unresolved_preds)
        }

    @classmethod
    def get_calibration_and_performance(
        cls,
        min_sample_threshold: int = MIN_SAMPLE_THRESHOLD_DEFAULT
    ) -> Dict[str, Any]:
        """
        Computes calibration and accuracy metrics grouped by (model_version, model_sha256)
        strictly over persisted, resolved official predictions.
        Clips probabilities with epsilon=1e-15 before Log Loss calculation.
        Computes score MAE using Stage 5 regulation+OT target rules (subtracting 1 winner goal for shootouts).
        Enforces min_sample_threshold returning INSUFFICIENT_SAMPLE if sample count is too low.
        """
        now_utc = datetime.now(timezone.utc)

        # Fetch resolved official predictions with eager-loaded games
        resolved_preds = GamePrediction.query.options(
            joinedload(GamePrediction.game)
        ).filter(
            GamePrediction.prediction_type == 'official_pregame'
        ).all()

        resolved_preds = [p for p in resolved_preds if p.is_outcome_resolved and p.game]

        # Group by (model_version, model_sha256)
        groups: Dict[tuple, List[GamePrediction]] = {}
        for p in resolved_preds:
            key = (p.model_version, p.model_sha256 or "unknown")
            groups.setdefault(key, []).append(p)

        group_results = []

        for (version, sha), preds in groups.items():
            sample_count = len(preds)

            if sample_count < min_sample_threshold:
                group_results.append({
                    "model_version": version,
                    "model_sha256": sha,
                    "sample_count": sample_count,
                    "min_sample_threshold": min_sample_threshold,
                    "status": "INSUFFICIENT_SAMPLE",
                    "message": f"Sample count {sample_count} is below threshold {min_sample_threshold} required for calibration conclusions."
                })
                continue

            # Compute metrics for group with sufficient samples
            brier_list = []
            log_loss_list = []
            correct_winner_count = 0
            score_mae_list = []
            res_bias_list = []

            for p in preds:
                g = p.game
                box_h = g.home_score
                box_a = g.away_score

                # Check shootout target resolution via Event table or game state
                has_so = db.session.query(Event.event_id).filter(
                    Event.game_id == g.game_id,
                    Event.period_type == 'SO'
                ).first() is not None

                if has_so:
                    if box_h > box_a:
                        reg_h, reg_a = box_h - 1, box_a
                    elif box_a > box_h:
                        reg_h, reg_a = box_h, box_a - 1
                    else:
                        reg_h, reg_a = box_h, box_a
                else:
                    reg_h, reg_a = box_h, box_a

                reg_total = reg_h + reg_a
                actual_home_win = 1.0 if reg_h > reg_a else (0.0 if reg_a > reg_h else 0.5)

                p_home = float(np.clip(p.home_win_probability, EPSILON, 1.0 - EPSILON))

                # Brier Score
                brier_list.append((p_home - actual_home_win) ** 2)

                # Log Loss (clipped)
                if actual_home_win == 1.0:
                    log_loss_list.append(-math.log(p_home))
                elif actual_home_win == 0.0:
                    log_loss_list.append(-math.log(1.0 - p_home))
                else:
                    # Tie/shootout required
                    log_loss_list.append(-math.log(0.5))

                # Winner Accuracy
                if (p_home > 0.5 and reg_h > reg_a) or (p_home < 0.5 and reg_a > reg_h):
                    correct_winner_count += 1

                # Score MAE (Stage 5 reg+OT goals)
                exp_tot = p.expected_home_goals + p.expected_away_goals
                score_mae_list.append(abs(reg_total - exp_tot))
                res_bias_list.append(reg_total - exp_tot)

            group_results.append({
                "model_version": version,
                "model_sha256": sha,
                "sample_count": sample_count,
                "min_sample_threshold": min_sample_threshold,
                "status": "EVALUATED",
                "brier_score": round(float(np.mean(brier_list)), 4),
                "log_loss": round(float(np.mean(log_loss_list)), 4),
                "win_accuracy": round(float(correct_winner_count / sample_count), 4),
                "score_mae_reg_ot": round(float(np.mean(score_mae_list)), 4),
                "residual_bias_reg_ot": round(float(np.mean(res_bias_list)), 4)
            })

        return {
            "audited_at": now_utc.isoformat(),
            "total_resolved_official_predictions": len(resolved_preds),
            "groups": group_results
        }
