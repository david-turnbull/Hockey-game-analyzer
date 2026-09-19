import hmac
import logging
from flask import Blueprint, jsonify, render_template, request, abort, current_app
from app.services.forecast_service import ForecastService

logger = logging.getLogger(__name__)

forecast_bp = Blueprint('forecast', __name__)

# --- API Endpoints ---

@forecast_bp.route('/api/v1/forecast/game/<int:game_id>', methods=['GET'])
def get_game_forecast_api(game_id: int):
    """
    Returns official prediction snapshot for a specific game (Strictly READ-ONLY).
    """
    pred_dict = ForecastService.get_official_prediction(game_id)
    if "error" in pred_dict:
        status_code = pred_dict.get("status_code", 404)
        return jsonify(pred_dict), status_code
    return jsonify(pred_dict), 200

@forecast_bp.route('/api/v1/forecast/game/<int:game_id>/generate', methods=['POST'])
def generate_game_forecast_api(game_id: int):
    """
    Explicit POST route to generate a prediction for a game.
    Fails closed: requires BOTH ALLOW_PREDICTION_GENERATION=True AND valid admin generation token.
    """
    if not current_app.config.get('ALLOW_PREDICTION_GENERATION', False):
        return jsonify({
            "error": "GENERATION_DISABLED",
            "message": "Prediction generation via HTTP POST is disabled.",
            "status_code": 403
        }), 403

    expected_token = current_app.config.get('PREDICTION_GENERATION_TOKEN')
    provided_token = request.headers.get('X-Generation-Token') or request.headers.get('Authorization', '').replace('Bearer ', '')

    if not expected_token or not provided_token or not hmac.compare_digest(provided_token.strip(), expected_token.strip()):
        return jsonify({
            "error": "UNAUTHORIZED",
            "message": "Invalid or missing prediction generation authorization token.",
            "status_code": 401
        }), 401

    prediction_type = request.json.get('prediction_type', 'official_pregame') if request.is_json else 'official_pregame'
    run_id = request.json.get('run_id') if request.is_json else None

    res = ForecastService.create_prediction(game_id, prediction_type=prediction_type, run_id=run_id)
    if "error" in res:
        return jsonify(res), res.get("status_code", 400)
    return jsonify(res), 201

@forecast_bp.route('/api/v1/forecast/upcoming', methods=['GET'])
def get_upcoming_forecasts_api():
    """
    Returns upcoming future games within lookahead horizon with prediction status ('available' or 'missing') (Strictly READ-ONLY).
    """
    lookahead_hours = request.args.get('lookahead_hours', type=int)
    limit = request.args.get('limit', type=int)
    res = ForecastService.get_upcoming_forecasts(lookahead_hours=lookahead_hours, limit=limit)
    return jsonify(res), 200

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
    Renders main Forecast Dashboard for the configured default lookahead horizon (48 hours).
    """
    res = ForecastService.get_upcoming_forecasts()
    backtest = ForecastService.get_backtest_summary()
    return render_template('forecast.html', forecasts=res["forecasts"], meta=res, backtest=backtest)

@forecast_bp.route('/forecast/game/<int:game_id>', methods=['GET'])
def forecast_game_page(game_id: int):
    """
    Renders detailed match forecast page for a specific game (Strictly READ-ONLY).
    """
    pred_dict = ForecastService.get_official_prediction(game_id)
    if "error" in pred_dict:
        status_code = pred_dict.get("status_code", 404)
        abort(status_code, description=pred_dict.get("message", pred_dict["error"]))
    return render_template('forecast_game.html', forecast=pred_dict)


