import os
import logging
from flask import Flask
from app.config import config_by_name
from app.models.base import db
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.startswith('sqlite3'):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

def configure_logging(app):
    """Configures the logging format and handlers."""
    log_level = logging.INFO
    if app.config.get('DEBUG'):
        log_level = logging.DEBUG
        
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )
    
    # Idempotent logging: check if a FileHandler targeting app.log is already configured
    log_file_path = os.path.join(app.config.get('BASE_DIR', ''), 'logs', 'app.log')
    already_has_handler = False
    norm_log_path = os.path.normpath(log_file_path).lower()
    
    for h in app.logger.handlers:
        if isinstance(h, logging.FileHandler):
            h_path = os.path.normpath(h.baseFilename).lower()
            if h_path == norm_log_path:
                already_has_handler = True
                break
                
    if not already_has_handler:
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        file_handler = logging.FileHandler(log_file_path)
        file_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d]: %(message)s'
        ))
        file_handler.setLevel(log_level)
        app.logger.addHandler(file_handler)
        
    app.logger.setLevel(log_level)
    app.logger.info("Logging initialized for NHL Hockey Analytics Platform")

def create_app(config_name=None):
    """Application factory method to create and configure the Flask app."""
    app = Flask(__name__)
    
    # Determine configuration type
    if not config_name:
        config_name = os.environ.get('FLASK_ENV', 'development')
        
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))
    
    # Configure logging
    configure_logging(app)
    
    # Initialize DB extension
    db.init_app(app)
    
    # Run automatic database migrations
    with app.app_context():
        from app.utils.db_migrator import run_migrations
        run_migrations(db)

    
    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    from app.routes.games import games_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(games_bp)
    
    # Global error handlers
    @app.errorhandler(404)
    def page_not_found(error):
        app.logger.warning(f"404 error encountered: {error}")
        return "404 - Resource Not Found", 404

    @app.errorhandler(500)
    def internal_server_error(error):
        app.logger.error(f"500 error encountered: {error}")
        return "500 - Internal Server Error", 500
        
    return app
