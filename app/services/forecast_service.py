import os
import json
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.models import db, Game, GamePrediction, Team
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.score_projection import PoissonScoreModel
from app.analytics.forecasting.model_registry import ForecastModelRegistry, ModelUnavailableError

logger = logging.getLogger(__name__)

def get_trained_win_model() -> WinProbabilityModel:
    """Loads active production WinProbabilityModel through ForecastModelRegistry. Fails closed if unavailable."""
    model_instance, _ = ForecastModelRegistry.load_active_model()
    return model_instance


def make_error_response(error_code: str, message: str, status_code: int = 400) -> Dict[str, Any]:
    """Helper to return standardized structured API error responses with ISO UTC timestamps."""
    return {
        "error": error_code,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status_code": status_code
    }


class ForecastService:
    """
    Service layer providing unified access to game forecasts, immutable prediction persistence,
    and historical backtesting summaries.
    """

    @classmethod
    def get_or_create_prediction(
        cls,
        game_id: int,
        prediction_type: str = 'official_pregame',
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieves existing GamePrediction snapshot or generates a new immutable prediction snapshot.
        For official_pregame, returns any existing official snapshot for the game_id regardless of model version.
        If no official snapshot exists, strictly enforces pre-puck-drop cutoff without exception.
        """
        game = db.session.get(Game, game_id)
        if not game:
            return make_error_response("GAME_NOT_FOUND", f"Game {game_id} not found.", 404)

        if game.data_source != 'nhl_api':
            return make_error_response("SYNTHETIC_DATA_BLOCKED", f"Predictions blocked on non-production data source '{game.data_source}'", 400)

        # 1. Official Pregame Invariant: Always check for existing official snapshot BEFORE model resolution
        if prediction_type == 'official_pregame':
            existing_official = GamePrediction.query.filter_by(
                game_id=game_id,
                prediction_type='official_pregame'
            ).first()
            if existing_official:
                return cls.format_prediction_dict(existing_official)

            # Strict Cutoff Safeguard: Puck drop timestamp MUST be in the future
            if not game.start_time_utc:
                return make_error_response(
                    "MISSING_START_TIME",
                    f"Official pregame predictions require a valid UTC start timestamp on game {game_id}.",
                    400
                )

            game_start = game.start_time_utc
            if game_start.tzinfo is None:
                game_start = game_start.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)

            if now_utc >= game_start:
                return make_error_response(
                    "GAME_ALREADY_STARTED",
                    f"Official pregame prediction cannot be created after puck drop ({game_start.isoformat()}).",
                    400
                )

        # Load active production model & manifest
        try:
            win_model, manifest = ForecastModelRegistry.load_active_model()
        except ModelUnavailableError as e:
            logger.error(f"Prediction blocked for game {game_id}: {e}")
            return make_error_response("MODEL_UNAVAILABLE", str(e), 503)

        model_version = manifest["model_version"]
        model_sha256 = manifest["artifact_sha256"]
        feature_schema_version = manifest.get("feature_schema_version", "v1")

        # 2. Non-Official Predictions: Check existing by exact identity (game_id, model_version, prediction_type, run_id)
        if prediction_type != 'official_pregame':
            query = GamePrediction.query.filter_by(
                game_id=game_id,
                model_version=model_version,
                prediction_type=prediction_type
            )
            if prediction_type == 'ad_hoc' and run_id:
                query = query.filter_by(run_id=run_id)

            existing_pred = query.first()
            if existing_pred:
                return cls.format_prediction_dict(existing_pred)

        # Calculate pregame features & generate predictions
        pregame_feats = PregameFeatureService.get_pregame_features(game)
        win_res = win_model.predict_game_probability(pregame_feats)
        score_res = PoissonScoreModel.project_score_distribution(pregame_feats)

        feature_payload_json = json.dumps(pregame_feats, sort_keys=True)
        feature_payload_sha256 = hashlib.sha256(feature_payload_json.encode('utf-8')).hexdigest()
        cutoff_time = game.start_time_utc
        active_run_id = run_id or ('official' if prediction_type == 'official_pregame' else str(uuid.uuid4()))

        # Build immutable snapshot
        prediction = GamePrediction(
            game_id=game_id,
            created_at=datetime.now(timezone.utc),
            home_win_probability=win_res["home_win_probability"],
            away_win_probability=win_res["away_win_probability"],
            expected_home_goals=score_res["expected_home_goals"],
            expected_away_goals=score_res["expected_away_goals"],
            prediction_type=prediction_type,
            model_sha256=model_sha256,
            feature_schema_version=feature_schema_version,
            run_id=active_run_id,
            input_cutoff_time_utc=cutoff_time,
            feature_payload_json=feature_payload_json,
            feature_payload_sha256=feature_payload_sha256,
            score_matrix_json=json.dumps(score_res),
            feature_importance_json=json.dumps(win_res["explanations"]),
            model_version=model_version,
            is_official=(prediction_type == 'official_pregame')
        )

        try:
            db.session.add(prediction)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            if prediction_type == 'official_pregame':
                existing_pred = GamePrediction.query.filter_by(game_id=game_id, prediction_type='official_pregame').first()
            else:
                existing_pred = GamePrediction.query.filter_by(game_id=game_id, model_version=model_version, prediction_type=prediction_type).first()
            if existing_pred:
                return cls.format_prediction_dict(existing_pred)
            raise

        return cls.format_prediction_dict(prediction)

    @classmethod
    def format_prediction_dict(cls, pred: GamePrediction) -> Dict[str, Any]:
        """
        Formats GamePrediction database instance into clean API dictionary representation.
        """
        g = pred.game
        score_data = json.loads(pred.score_matrix_json) if pred.score_matrix_json else {}
        explanations = json.loads(pred.feature_importance_json) if pred.feature_importance_json else []

        home_team = db.session.get(Team, g.home_team_id) if g else None
        away_team = db.session.get(Team, g.away_team_id) if g else None

        return {
            "prediction_id": pred.prediction_id,
            "game_id": pred.game_id,
            "created_at": pred.created_at.isoformat() if pred.created_at else None,
            "prediction_type": pred.prediction_type,
            "model_version": pred.model_version,
            "model_sha256": pred.model_sha256,
            "feature_schema_version": pred.feature_schema_version,
            "run_id": pred.run_id,
            "input_cutoff_time_utc": pred.input_cutoff_time_utc.isoformat() if pred.input_cutoff_time_utc else None,
            "feature_payload_sha256": pred.feature_payload_sha256,
            "is_official": pred.is_official,
            "is_outcome_resolved": pred.is_outcome_resolved,
            "actual_winner": pred.actual_winner,
            "game": {
                "season": g.season if g else None,
                "game_date": g.game_date.strftime("%Y-%m-%d") if g else None,
                "start_time_utc": g.start_time_utc.isoformat() if g and g.start_time_utc else None,
                "home_team_id": g.home_team_id if g else None,
                "away_team_id": g.away_team_id if g else None,
                "home_team_abbrev": home_team.abbreviation if home_team else "HOME",
                "away_team_abbrev": away_team.abbreviation if away_team else "AWAY",
                "home_team_name": home_team.name if home_team else "Home Team",
                "away_team_name": away_team.name if away_team else "Away Team",
                "home_score": g.home_score if g else 0,
                "away_score": g.away_score if g else 0,
                "nhl_game_state": g.nhl_game_state if g else "FUT"
            },
            "win_probability": {
                "home_win_probability": pred.home_win_probability,
                "away_win_probability": pred.away_win_probability,
                "home_win_pct_display": f"{round(pred.home_win_probability * 100, 1)}%",
                "away_win_pct_display": f"{round(pred.away_win_probability * 100, 1)}%"
            },
            "score_projection": score_data,
            "explanations": explanations
        }

    @classmethod
    def get_upcoming_forecasts(cls, limit: int = 12) -> List[Dict[str, Any]]:
        """
        Fetches predictions for upcoming future games (start_time_utc > now_utc).
        """
        now_utc = datetime.utcnow()
        games = Game.query.filter(
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.start_time_utc > now_utc
        ).order_by(
            Game.start_time_utc.asc(),
            Game.game_id.asc()
        ).limit(limit).all()

        results = []
        for g in games:
            pred_dict = cls.get_or_create_prediction(g.game_id)
            if "error" not in pred_dict:
                results.append(pred_dict)
        return results

    @classmethod
    def get_backtest_summary(cls) -> Dict[str, Any]:
        """
        Loads cached backtest results report or returns default summary.
        """
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(project_root, "reports", "backtest_results_v1.4.0.json")

        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading backtest summary: {e}")

        return {
            "status": "Backtest report not found. Run scripts/run_backtest.py to generate."
        }
