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


@games_bp.route('/<int:game_id>/line')
def line_detail(game_id):
    """View for forward line combination or defensive pairing detail."""
    players_raw = request.args.get('players')
    team_id_raw = request.args.get('team_id')
    if not players_raw:
        abort(400)
    try:
        player_ids = [int(p) for p in players_raw.split(',') if p]
    except ValueError:
        abort(400)
        
    from app.services.unit_service import UnitService
    unit_stats = UnitService.get_unit_detail(game_id, player_ids)
    if not unit_stats:
        abort(404)
        
    context_team_id = None
    if team_id_raw:
        try:
            context_team_id = int(team_id_raw)
        except ValueError:
            pass
            
    return render_template(
        'line_detail.html',
        unit=unit_stats,
        game_id=game_id,
        context_team_id=context_team_id
    )


@games_bp.route('/<int:game_id>/compare')
def player_comparison(game_id):
    """View for comparing two players in a game side-by-side."""
    player1_id_raw = request.args.get('player1')
    player2_id_raw = request.args.get('player2')
    team_id_raw = request.args.get('team_id')
    
    context_team_id = None
    if team_id_raw:
        try:
            context_team_id = int(team_id_raw)
        except ValueError:
            pass
    
    game = db.session.get(Game, game_id)
    if not game:
        abort(404)
        
    # Get all skaters and goalies on both teams for the selector dropdown
    from app.models import GamePlayer
    roster = GamePlayer.query.filter_by(game_id=game_id).all()
    
    # Group roster players by team
    home_team_abbr = game.home_team.abbreviation
    away_team_abbr = game.away_team.abbreviation
    
    home_players = []
    away_players = []
    for gp in roster:
        player_info = {
            "player_id": gp.player_id,
            "name": gp.player.full_name if gp.player else f"Player {gp.player_id}",
            "position": gp.position or (gp.player.position if gp.player else "skater"),
            "sweater_number": gp.sweater_number
        }
        if gp.team_id == game.home_team_id:
            home_players.append(player_info)
        else:
            away_players.append(player_info)
            
    sort_key = lambda x: (x["sweater_number"] if x["sweater_number"] is not None else 999, x["name"])
    home_players.sort(key=sort_key)
    away_players.sort(key=sort_key)
    
    player1_stats = None
    player2_stats = None
    
    if player1_id_raw and player2_id_raw:
        try:
            p1_id = int(player1_id_raw)
            p2_id = int(player2_id_raw)
            player1_stats = PlayerGameService.get_player_game_stats(game_id, p1_id)
            player2_stats = PlayerGameService.get_player_game_stats(game_id, p2_id)
        except ValueError:
            pass
            
    return render_template(
        'player_compare.html',
        game=game,
        home_team_abbr=home_team_abbr,
        away_team_abbr=away_team_abbr,
        home_players=home_players,
        away_players=away_players,
        player1=player1_stats,
        player2=player2_stats,
        context_team_id=context_team_id
    )
