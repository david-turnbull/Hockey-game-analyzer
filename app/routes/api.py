from flask import Blueprint, jsonify, request, current_app
from app.services.game_service import GameService
from app.models import db, Shot, Event, Player, Team, Game, Shift
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

@api_bp.route('/games/<int:game_id>/shots')
@api_bp.route('/game/<int:game_id>/shots')
@api_bp.route('/shots')
def get_shots(game_id=None):
    """Returns a list of shot attempts for a given game_id as JSON."""
    if game_id is None:
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
            "norm_x": s.x_coordinate_normalized,
            "norm_y": s.y_coordinate_normalized,
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
            "manpower_state": s.event.manpower_state,
            "empty_net": s.empty_net,
            "xg": round(s.xg, 4) if (s.xg is not None and s.outcome in ['Goal', 'Saved', 'Missed']) else None,
            "model_version": s.model_version if s.outcome in ['Goal', 'Saved', 'Missed'] else None
        })
        
    return jsonify(formatted_shots)


@api_bp.route('/games/<int:game_id>/xg_timeline')
@api_bp.route('/game/<int:game_id>/xg_timeline')
def get_xg_timeline(game_id: int):
    """Returns the cumulative expected goals timeline for a game."""
    situation = request.args.get('situation', 'all').lower()
    timeline_data = GameService.get_game_xg_timeline(game_id, situation=situation)
    if not timeline_data:
        return jsonify({"error": f"Game {game_id} not found"}), 404
    return jsonify(timeline_data)


@api_bp.route('/schedule')
def get_schedule():
    """Returns the official season schedule for a team, cross-referenced with DB status."""
    team_id_raw = request.args.get('team_id')
    season = request.args.get('season')
    
    if not team_id_raw or not season:
        return jsonify({"error": "Missing team_id or season parameter"}), 400
        
    try:
        team_id = int(team_id_raw)
    except ValueError:
        return jsonify({"error": "Invalid team_id format"}), 400
        
    team = db.session.get(Team, team_id)
    if not team:
        return jsonify({"error": f"Team with ID {team_id} not found"}), 404
        
    team_abbr = team.abbreviation
    
    try:
        from data_pipeline.ingest.nhl_api import NHLApiClient
        api_client = NHLApiClient()
        schedule_data = api_client.get_season_schedule(team_abbr, season)
    except Exception as e:
        current_app.logger.exception(f"Failed to fetch schedule for {team_abbr} {season}")
        return jsonify({"error": f"Failed to retrieve schedule: {str(e)}"}), 500
        
    if not schedule_data or "games" not in schedule_data:
        return jsonify([])
        
    # Get all game IDs already ingested for this season
    existing_games = Game.query.filter(Game.season == season).all()
    existing_game_ids = {g.game_id for g in existing_games}
    
    formatted_games = []
    # Filter for regular season games (gameType == 2)
    reg_games = [g for g in schedule_data["games"] if g.get("gameType") == 2]
    
    for g in reg_games:
        game_id = g["id"]
        is_ingested = game_id in existing_game_ids
        
        home_team_abbrev = g.get("homeTeam", {}).get("abbrev", "UNK")
        away_team_abbrev = g.get("awayTeam", {}).get("abbrev", "UNK")
        is_home = (home_team_abbrev == team_abbr)
        opponent_abbrev = away_team_abbrev if is_home else home_team_abbrev
        
        home_score = g.get("homeTeam", {}).get("score", 0)
        away_score = g.get("awayTeam", {}).get("score", 0)
        
        formatted_games.append({
            "game_id": game_id,
            "date": g.get("gameDate"),
            "game_type": "Regular",
            "home_team_abbrev": home_team_abbrev,
            "away_team_abbrev": away_team_abbrev,
            "home_score": home_score,
            "away_score": away_score,
            "is_home": is_home,
            "is_ingested": is_ingested,
            "opponent_abbrev": opponent_abbrev,
            "game_status": g.get("gameState", "FUT")
        })
        
    return jsonify(formatted_games)


@api_bp.route('/game/<int:game_id>/ingest', methods=['POST'])
def ingest_single_game(game_id):
    """Ingests a single game on demand."""
    if not current_app.config.get('ALLOW_PUBLIC_INGESTION', True):
        return jsonify({"success": False, "error": "Public ingestion is disabled. Administration credentials required."}), 403

    from data_pipeline.orchestrator import PipelineOrchestrator
    try:
        current_app.logger.info(f"On-demand ingestion triggered for game_id={game_id}")
        orchestrator = PipelineOrchestrator(session=db.session)
        success, summary = orchestrator.ingest_game(game_id)
        if success:
            db.session.commit()
            return jsonify({"success": True, "summary": summary})
        else:
            return jsonify({"success": False, "error": summary.get("error", "Unknown ingestion error")}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception(f"Failed to ingest game {game_id}")
        return jsonify({"success": False, "error": str(e)}), 500


@api_bp.route('/game/<int:game_id>/on-ice')
def get_on_ice_players(game_id):
    """Returns the players on the ice for both teams at a specific period and game-clock time."""
    from app.models import Shift
    from app.services.on_ice_service import OnIceService
    period_raw = request.args.get('period')
    time_str = request.args.get('time')
    
    if not period_raw or not time_str:
        return jsonify({"error": "Missing period or time parameter"}), 400
        
    try:
        period = int(period_raw)
    except ValueError:
        return jsonify({"error": "Invalid period format"}), 400
        
    # Parse time_str (MM:SS) to game-elapsed seconds (accounting for period offsets)
    if not time_str or ':' not in time_str:
        return jsonify({"error": "Invalid time format (must be MM:SS)"}), 400
        
    try:
        elapsed_seconds = OnIceService.period_time_to_game_elapsed(period, time_str)
    except ValueError:
        return jsonify({"error": "Invalid time format (must be MM:SS)"}), 400
        
    # Query overlapping shifts that are not anomalies
    shifts = db.session.query(Shift).join(Player).filter(
        Shift.game_id == game_id,
        Shift.period == period,
        Shift.start_elapsed_seconds <= elapsed_seconds,
        Shift.end_elapsed_seconds > elapsed_seconds,
        Shift.is_anomaly == False
    ).options(joinedload(Shift.player)).all()
    
    # Resolve the game to identify home and away teams
    game = db.session.get(Game, game_id)
    if not game:
        return jsonify({"error": "Game not found"}), 404
        
    home_players = []
    away_players = []
    
    # Keep track of unique player IDs to prevent duplicates if shift data overlaps
    seen_player_ids = set()
    
    for s in shifts:
        p = s.player
        if not p or p.player_id in seen_player_ids:
            continue
        seen_player_ids.add(p.player_id)
        
        # Determine player team for the game
        is_home_player = (s.team_id == game.home_team_id)
        
        player_info = {
            "player_id": p.player_id,
            "name": p.full_name,
            "number": p.sweater_number,
            "position": p.position
        }
        
        if is_home_player:
            home_players.append(player_info)
        else:
            away_players.append(player_info)
            
    # Sort players by number (or name if number is None)
    sort_key = lambda x: (x["number"] if x["number"] is not None else 999, x["name"])
    home_players.sort(key=sort_key)
    away_players.sort(key=sort_key)
    
    return jsonify({
        "home": home_players,
        "away": away_players
    })

@api_bp.route('/game/<int:game_id>/player/<int:player_id>/shots')
def get_player_shots(game_id, player_id):
    """Returns a list of shot attempts taken (or faced, if goalie) by a player as JSON."""
    current_app.logger.info(f"API query for shots of game_id={game_id}, player_id={player_id}")
    
    player = db.session.get(Player, player_id)
    if not player:
        return jsonify({"error": "Player not found"}), 404
        
    if player.position == 'G':
        # Goalie: return shots faced
        shots = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id
        ).options(
            joinedload(Shot.event).joinedload(Event.team),
            joinedload(Shot.shooter),
            joinedload(Shot.goalie)
        ).all()
    else:
        # Skater: return shots taken
        shots = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.shooter_id == player_id
        ).options(
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
            "norm_x": s.x_coordinate_normalized,
            "norm_y": s.y_coordinate_normalized,
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
            "manpower_state": s.event.manpower_state,
            "empty_net": s.empty_net,
            "xg": round(s.xg, 4) if (s.xg is not None and s.outcome in ['Goal', 'Saved', 'Missed']) else None
        })
        
    return jsonify(formatted_shots)
