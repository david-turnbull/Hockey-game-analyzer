from flask import Blueprint, render_template, abort
from app.services.game_service import GameService

games_bp = Blueprint('games', __name__, url_prefix='/game')

@games_bp.route('/<int:game_id>')
def game_dashboard(game_id):
    """View for the detailed game overview dashboard."""
    overview_stats = GameService.get_game_overview_stats(game_id)
    if not overview_stats:
        abort(404)
    return render_template('game.html', stats=overview_stats)
