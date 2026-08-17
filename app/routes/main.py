from flask import Blueprint, render_template, current_app
from sqlalchemy import text
from app.models.base import db
from app.services.game_service import GameService
import logging

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

@main_bp.route('/')
def index():
    """Main landing page displaying the Game Selector UI."""
    seasons = GameService.get_available_seasons()
    teams = GameService.get_available_teams()
    logger.info(f"Loaded game selector homepage. Available seasons: {len(seasons)}, Teams: {len(teams)}")
    return render_template(
        'index.html', 
        seasons=seasons, 
        teams=teams
    )

@main_bp.route('/diagnostics')
def diagnostics():
    """Diagnostic page to verify environment, DB connection, and setup."""
    db_status = "Unknown"
    db_error = None
    tables = []
    
    try:
        # Check SQLite tables using raw sql
        result = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        tables = [row[0] for row in result.fetchall() if not row[0].startswith('sqlite_')]
        db_status = "Connected"
    except Exception as e:
        db_status = "Failed"
        db_error = str(e)
        logger.exception("Database diagnostics query failed.")
        
    return render_template(
        'diagnostics.html', 
        db_status=db_status, 
        db_error=db_error, 
        tables=tables
    )
