import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from sqlalchemy import func
from app.models import db, Game, GamePrediction, Team
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.score_projection import PoissonScoreModel

logger = logging.getLogger(__name__)

# Global singleton instance for trained model
_win_model_instance: Optional[WinProbabilityModel] = None
MODEL_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "analytics", "forecasting", "win_model_v1.4.0.pkl"
)

def get_trained_win_model() -> WinProbabilityModel:
    global _win_model_instance
    if _win_model_instance is not None and _win_model_instance.model is not None:
        return _win_model_instance

    # Attempt to load pre-trained model from disk
    if os.path.exists(MODEL_FILE_PATH):
        try:
            _win_model_instance = WinProbabilityModel.load_model(MODEL_FILE_PATH)
            return _win_model_instance
        except Exception as e:
            logger.warning(f"Could not load saved model from {MODEL_FILE_PATH}: {e}")

    # Fallback to train and save model to disk
    _win_model_instance = WinProbabilityModel()
    try:
        PregameFeatureService.preload_all_stats()
        _win_model_instance.train_and_select()
        _win_model_instance.save_model(MODEL_FILE_PATH)
    except Exception as e:
        logger.warning(f"Could not auto-train WinProbabilityModel on init: {e}")
    return _win_model_instance


class ForecastService:
    """
    Service layer providing unified access to game forecasts, immutable prediction persistence,
    and historical backtesting summaries.
    """

    @classmethod
    def get_or_create_prediction(cls, game_id: int) -> Dict[str, Any]:
        """
        Retrieves existing official GamePrediction snapshot or generates and persists a new immutable prediction snapshot.
        """
        game = db.session.get(Game, game_id)
        if not game:
            return {"error": f"Game {game_id} not found."}

        # Check existing official prediction snapshot
        existing_pred = GamePrediction.query.filter_by(game_id=game_id, is_official=True).first()
        if existing_pred:
            return cls.format_prediction_dict(existing_pred)

        # Generate new prediction
        win_model = get_trained_win_model()
        pregame_feats = PregameFeatureService.get_pregame_features(game)

        win_res = win_model.predict_game_probability(pregame_feats)
        score_res = PoissonScoreModel.project_score_distribution(pregame_feats)

        # Save immutable snapshot
        prediction = GamePrediction(
            game_id=game_id,
            created_at=datetime.now(timezone.utc),
            home_win_probability=win_res["home_win_probability"],
            away_win_probability=win_res["away_win_probability"],
            expected_home_goals=score_res["expected_home_goals"],
            expected_away_goals=score_res["expected_away_goals"],
            score_matrix_json=json.dumps(score_res),
            feature_importance_json=json.dumps(win_res["explanations"]),
            model_version="v1.4.0",
            is_official=True
        )

        db.session.add(prediction)
        db.session.commit()

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
            "model_version": pred.model_version,
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
        Fetches predictions for upcoming or recent games.
        """
        games = Game.query.filter(
            Game.game_type == 'R'
        ).order_by(
            Game.start_time_utc.desc(),
            Game.game_date.desc(),
            Game.game_id.desc()
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
