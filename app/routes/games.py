from flask import Blueprint, render_template, abort, request
from app.models import db, Game
from sqlalchemy import or_
from app.services.game_service import GameService
from app.services.player_game_service import PlayerGameService

games_bp = Blueprint('games', __name__, url_prefix='/game')

@games_bp.route('/<int:game_id>')
def game_dashboard(game_id):
    """View for the detailed game overview dashboard."""
    overview_stats = GameService.get_game_overview_stats(game_id)
    if not overview_stats:
        abort(404)
        
    team_id_raw = request.args.get('team_id')
    
    # 1. Resolve context team
    context_team_id = None
    if team_id_raw:
        try:
            context_team_id = int(team_id_raw)
        except ValueError:
            pass
            
    if not context_team_id:
        context_team_id = overview_stats.get("home_team_id")
        
    # 2. Get previous and next games in schedule
    prev_game = None
    next_game = None
    
    game = db.session.get(Game, game_id)
    if game:
        # Query ingested games for this team and season
        all_games = Game.query.filter(
            Game.season == game.season,
            or_(Game.home_team_id == context_team_id, Game.away_team_id == context_team_id)
        ).order_by(Game.game_date.asc(), Game.game_id.asc()).all()
        
        # Find position of current game
        current_idx = -1
        for i, g in enumerate(all_games):
            if g.game_id == game_id:
                current_idx = i
                break
                
        if current_idx != -1:
            if current_idx > 0:
                prev_game = all_games[current_idx - 1]
            if current_idx < len(all_games) - 1:
                next_game = all_games[current_idx + 1]
                
    return render_template(
        'game.html', 
        stats=overview_stats,
        prev_game=prev_game,
        next_game=next_game,
        context_team_id=context_team_id
    )

@games_bp.route('/<int:game_id>/player/<int:player_id>')
def player_game_dashboard(game_id, player_id):
    """View for the detailed player individual game dashboard."""
    player_stats = PlayerGameService.get_player_game_stats(game_id, player_id)
    if not player_stats:
        abort(404)
    return render_template('player_game.html', stats=player_stats)
