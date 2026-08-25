from flask import Blueprint, render_template, abort
from app.services.game_service import GameService
from app.services.player_game_service import PlayerGameService

games_bp = Blueprint('games', __name__, url_prefix='/game')

@games_bp.route('/<int:game_id>')
def game_dashboard(game_id):
    """View for the detailed game overview dashboard."""
    overview_stats = GameService.get_game_overview_stats(game_id)
    if not overview_stats:
        abort(404)
    return render_template('game.html', stats=overview_stats)

@games_bp.route('/<int:game_id>/player/<int:player_id>')
def player_game_dashboard(game_id, player_id):
    """View for the detailed player individual game dashboard."""
    player_stats = PlayerGameService.get_player_game_stats(game_id, player_id)
    if not player_stats:
        abort(404)
    return render_template('player_game.html', stats=player_stats)
