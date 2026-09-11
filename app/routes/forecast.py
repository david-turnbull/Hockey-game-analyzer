import logging
from flask import Blueprint, jsonify, render_template, request
from app.services.forecast_service import ForecastService

logger = logging.getLogger(__name__)

forecast_bp = Blueprint('forecast', __name__)

# --- API Endpoints ---

@forecast_bp.route('/api/v1/forecast/game/<int:game_id>', methods=['GET'])
def get_game_forecast_api(game_id: int):
    """
    Returns official prediction snapshot for a specific game.
    """
    pred_dict = ForecastService.get_or_create_prediction(game_id)
    if "error" in pred_dict:
        return jsonify(pred_dict), 404
    return jsonify(pred_dict), 200

@forecast_bp.route('/api/v1/forecast/upcoming', methods=['GET'])
def get_upcoming_forecasts_api():
    """
    Returns predictions for upcoming or recent games.
    """
    limit = request.args.get('limit', 12, type=int)
    forecasts = ForecastService.get_upcoming_forecasts(limit=limit)
    return jsonify({"count": len(forecasts), "forecasts": forecasts}), 200

@forecast_bp.route('/api/v1/forecast/backtest/summary', methods=['GET'])
def get_backtest_summary_api():
    """
    Returns out-of-time historical backtest results summary.
    """
    summary = ForecastService.get_backtest_summary()
    return jsonify(summary), 200

# --- UI Page Routes ---

@forecast_bp.route('/forecast', methods=['GET'])
def forecast_dashboard_page():
    """
    Renders main Forecast Dashboard.
    """
    forecasts = ForecastService.get_upcoming_forecasts(limit=12)
    backtest = ForecastService.get_backtest_summary()
    return render_template('forecast.html', forecasts=forecasts, backtest=backtest)

@forecast_bp.route('/forecast/game/<int:game_id>', methods=['GET'])
def forecast_game_page(game_id: int):
    """
    Renders detailed match forecast page for a specific game.
    """
    pred_dict = ForecastService.get_or_create_prediction(game_id)
    if "error" in pred_dict:
        return render_template('404.html', message=pred_dict["error"]), 404
    return render_template('forecast_game.html', forecast=pred_dict)
