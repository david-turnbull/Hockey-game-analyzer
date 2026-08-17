from flask import Blueprint, jsonify, request, current_app
from app.services.game_service import GameService
from app.models import db, Shot, Event
from sqlalchemy.orm import joinedload

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/games')
def get_games():
    """Returns a list of games for a given team_id and season as JSON."""
    team_id_raw = request.args.get('team_id')
    season = request.args.get('season')
    
    if not team_id_raw or not season:
        return jsonify({"error": "Missing team_id or season parameter"}), 400
        
    try:
        team_id = int(team_id_raw)
    except ValueError:
        return jsonify({"error": "Invalid team_id format"}), 400
        
    current_app.logger.info(f"API query for team_id={team_id}, season={season}")
    games = GameService.get_games_list(team_id, season)
    return jsonify(games)

@api_bp.route('/shots')
def get_shots():
    """Returns a list of shot attempts for a given game_id as JSON."""
    game_id_raw = request.args.get('game_id')
    if not game_id_raw:
        return jsonify({"error": "Missing game_id parameter"}), 400
        
    try:
        game_id = int(game_id_raw)
    except ValueError:
        return jsonify({"error": "Invalid game_id format"}), 400
        
    current_app.logger.info(f"API query for shots of game_id={game_id}")
    
    # Execute optimized join query to avoid N+1 issues
    shots = db.session.query(Shot).join(Event).filter(Event.game_id == game_id).options(
        joinedload(Shot.event).joinedload(Event.team),
        joinedload(Shot.shooter),
        joinedload(Shot.goalie)
    ).all()
    
    formatted_shots = []
    for s in shots:
        formatted_shots.append({
            "shot_id": s.shot_id,
            "raw_x": s.event.x_coordinate,
            "raw_y": s.event.y_coordinate,
            "norm_x": s.x_coordinate,
            "norm_y": s.y_coordinate,
            "distance": s.distance,
            "angle": s.angle,
            "outcome": s.outcome,
            "shot_type": s.shot_type,
            "team_abbrev": s.event.team.abbreviation if s.event.team else "UNK",
            "team_id": s.event.team_id,
            "shooter_name": s.shooter.full_name if s.shooter else "Unknown",
            "shooter_id": s.shooter_id,
            "goalie_name": s.goalie.full_name if s.goalie else "None",
            "period": s.event.period,
            "period_time": s.event.period_time,
            "strength_state": s.strength_state,
            "empty_net": s.empty_net
        })
        
    return jsonify(formatted_shots)
