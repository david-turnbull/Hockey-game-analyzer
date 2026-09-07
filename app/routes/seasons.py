import logging
from typing import Optional
from flask import Blueprint, render_template, abort, request, redirect, url_for
from sqlalchemy import or_, distinct
from app.models import db, Game, Team, Player
from app.services.game_service import GameService
from app.services.team_season_service import TeamSeasonService
from app.services.player_season_service import PlayerSeasonService
from app.services.goalie_season_service import GoalieSeasonService
from app.services.rolling_service import RollingService

logger = logging.getLogger(__name__)

seasons_bp = Blueprint('seasons', __name__)

@seasons_bp.route('/season')
def season_redirect():
    """Redirects /season to the most recent or active season."""
    raw_seasons = GameService.get_available_seasons()
    seasons = [s for s in raw_seasons if s]
    if not seasons:
        # Check raw DB
        db_seasons = [r[0] for r in db.session.query(distinct(Game.season)).order_by(Game.season.desc()).all() if r[0]]
        seasons = db_seasons
    
    target_season = "20242025" if "20242025" in seasons else (seasons[0] if seasons else "20242025")
    return redirect(url_for('seasons.season_overview', season=target_season))


@seasons_bp.route('/season/<season>')
def season_overview(season: str):
    """
    League Overview Dashboard:
    - Standings table with team stats (Record, Goals, Expected Goals, Shot Attempt Shares, Finishing Diff)
    - Situation toggle (All Situations vs 5v5)
    - Team filter selector (dynamic, season-aware, preserving multi-filter state)
    - Analytical leaders preview (Top Skaters by xG, G-xG, Points; Top Goalies by GSAx, Sv%)
    """
    situation = request.args.get('situation', 'all').lower()
    if situation not in ['all', '5v5', 'pp', 'sh']:
        situation = 'all'

    team_id_raw = request.args.get('team_id')
    selected_team_id = None
    if team_id_raw:
        try:
            selected_team_id = int(team_id_raw)
        except (ValueError, TypeError):
            selected_team_id = None

    # Get available seasons for selector
    raw_seasons = GameService.get_available_seasons()
    available_seasons = [s for s in raw_seasons if s]
    if not available_seasons:
        db_seasons = [r[0] for r in db.session.query(distinct(Game.season)).order_by(Game.season.desc()).all() if r[0]]
        available_seasons = db_seasons

    # Team analytical standings
    teams = TeamSeasonService.get_season_teams_summary(season=season, situation=situation)

    # Derive available teams for selector from teams present in season
    available_teams = sorted(
        [{"team_id": t["team_id"], "team_abbrev": t["team_abbrev"], "team_name": t["team_name"]} for t in teams],
        key=lambda x: x["team_name"]
    )

    selected_team = next((t for t in teams if t["team_id"] == selected_team_id), None)
    if selected_team_id is not None and selected_team is None:
        selected_team_id = None

    # Analytical Leaders: calculate season summaries ONCE, then derive leaderboards in memory
    all_skaters = PlayerSeasonService.get_season_skaters_summary(season=season, team_id=selected_team_id, min_gp=1)
    all_goalies = GoalieSeasonService.get_season_goalies_summary(season=season, team_id=selected_team_id, min_gp=1)

    leaders = {
        "xg": PlayerSeasonService.get_skater_leaderboards(
            season=season, sort_by='xg', limit=5, team_id=selected_team_id, precomputed_skaters=all_skaters
        ),
        "finishing": PlayerSeasonService.get_skater_leaderboards(
            season=season, sort_by='goals_above_expected', limit=5, team_id=selected_team_id, precomputed_skaters=all_skaters
        ),
        "points": PlayerSeasonService.get_skater_leaderboards(
            season=season, sort_by='points', limit=5, team_id=selected_team_id, precomputed_skaters=all_skaters
        ),
        "gsax": GoalieSeasonService.get_goalie_leaderboards(
            season=season, sort_by='gsax', limit=5, team_id=selected_team_id, precomputed_goalies=all_goalies
        ),
        "save_pct": GoalieSeasonService.get_goalie_leaderboards(
            season=season, sort_by='save_pct', limit=5, team_id=selected_team_id, precomputed_goalies=all_goalies
        )
    }

    return render_template(
        'season.html',
        season=season,
        situation=situation,
        teams=teams,
        leaders=leaders,
        available_seasons=available_seasons,
        available_teams=available_teams,
        selected_team_id=selected_team_id,
        selected_team=selected_team
    )


@seasons_bp.route('/team/<int:team_id>/season/<season>')
def team_season_dashboard(team_id: int, season: str):
    """
    Team Season Dashboard:
    - KPI Cards (All vs 5v5 xG%, xGF/60, xGA/60, CF%, FF%, Finishing Diff, Goaltending Diff)
    - Rolling Form (5, 10, 20 game rolling xGF%, CF%, xG diff)
    - Skaters Season Table
    - Goalies Season Table
    - Recent Games list
    """
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)

    # Team Stats (All situations and 5v5)
    all_stats = TeamSeasonService.get_team_season_stats(team_id=team_id, season=season, situation='all')
    five_on_five_stats = TeamSeasonService.get_team_season_stats(team_id=team_id, season=season, situation='5v5')

    if not all_stats:
        abort(404)

    # Skaters and Goalies
    skaters = PlayerSeasonService.get_season_skaters_summary(season=season, team_id=team_id, min_gp=1)
    goalies = GoalieSeasonService.get_season_goalies_summary(season=season, team_id=team_id, min_gp=1)

    # Rolling Trends
    rolling_trends = RollingService.get_team_rolling_trends(team_id=team_id, season=season, window_sizes=[5, 10, 20])

    # Recent Games
    recent_games = Game.query.filter(
        Game.season == season,
        or_(Game.home_team_id == team_id, Game.away_team_id == team_id)
    ).order_by(Game.game_date.desc()).limit(10).all()

    # Available seasons for team
    team_seasons = [
        r[0] for r in db.session.query(distinct(Game.season))
        .filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id))
        .order_by(Game.season.desc()).all() if r[0]
    ]

    return render_template(
        'team_season.html',
        team=team,
        season=season,
        stats=all_stats,
        stats_5v5=five_on_five_stats,
        skaters=skaters,
        goalies=goalies,
        rolling_trends=rolling_trends,
        recent_games=recent_games,
        team_seasons=team_seasons
    )


@seasons_bp.route('/player/<int:player_id>/season/<season>')
def player_season_dashboard(player_id: int, season: str):
    """
    Skater Season Dashboard:
    - Season Totals (GP, TOI, G, A, P, SOG, xG, G-xG, xG/60, G/60, Sh%, Exp Conv%)
    - 5v5 On-Ice possession metrics
    - Rolling Form (5-game rolling xG, G-xG, shot volume)
    """
    player = db.session.get(Player, player_id)
    if not player:
        abort(404)

    if player.position == 'G':
        return redirect(url_for('seasons.goalie_season_dashboard', goalie_id=player_id, season=season))

    stats = PlayerSeasonService.get_skater_season_stats(player_id=player_id, season=season)
    if not stats:
        abort(404)

    rolling = RollingService.get_player_rolling_trends(player_id=player_id, season=season, window_size=5)

    return render_template(
        'player_season.html',
        player=player,
        stats=stats,
        season=season,
        rolling=rolling
    )


@seasons_bp.route('/goalie/<int:goalie_id>/season/<season>')
def goalie_season_dashboard(goalie_id: int, season: str):
    """
    Goalie Season Dashboard:
    - Season Totals (GP, TOI, Shots Faced, GA, Sv%, xGA, GSAx, GSAx/60, Exp Sv%, Sv% Diff)
    - Rolling Form (5-game rolling GSAx, Sv% vs Expected)
    """
    player = db.session.get(Player, goalie_id)
    if not player:
        abort(404)

    if player.position != 'G':
        return redirect(url_for('seasons.player_season_dashboard', player_id=goalie_id, season=season))

    stats = GoalieSeasonService.get_goalie_season_stats(goalie_id=goalie_id, season=season)
    if not stats:
        abort(404)

    rolling = RollingService.get_goalie_rolling_trends(goalie_id=goalie_id, season=season, window_size=5)

    return render_template(
        'goalie_season.html',
        player=player,
        stats=stats,
        season=season,
        rolling=rolling
    )
