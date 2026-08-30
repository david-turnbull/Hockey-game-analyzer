import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

def run_migrations(db):
    """
    Checks if columns added in v1.1 exist in the SQLite database,
    and runs ALTER TABLE commands if they are missing.
    """
    try:
        connection = db.session.connection()
        
        # Check if tables exist first
        player_exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player'"
        )).first()
        gp_exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game_player'"
        )).first()
        
        # 1. Check player table
        if player_exists:
            # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
            result = connection.execute(text("PRAGMA table_info(player)")).fetchall()
            existing_player_cols = {row[1] for row in result}
            
            player_migrations = [
                ("headshot_url", "VARCHAR(500)"),
                ("sweater_number", "INTEGER"),
                ("height_in_inches", "INTEGER"),
                ("height_in_centimeters", "INTEGER"),
                ("weight_in_pounds", "INTEGER"),
                ("weight_in_kilograms", "INTEGER"),
                ("birth_date", "VARCHAR(20)"),
                ("birth_city", "VARCHAR(100)"),
                ("birth_country", "VARCHAR(100)")
            ]
            
            for col_name, col_type in player_migrations:
                if col_name not in existing_player_cols:
                    logger.info(f"Migrating: Adding column '{col_name}' to 'player' table")
                    connection.execute(text(f"ALTER TABLE player ADD COLUMN {col_name} {col_type}"))
                
        # 2. Check game_player table
        if gp_exists:
            result = connection.execute(text("PRAGMA table_info(game_player)")).fetchall()
            existing_gp_cols = {row[1] for row in result}
            
            if "sweater_number" not in existing_gp_cols:
                logger.info("Migrating: Adding column 'sweater_number' to 'game_player' table")
                connection.execute(text("ALTER TABLE game_player ADD COLUMN sweater_number INTEGER"))
                
        # 3. Check event table
        event_exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='event'"
        )).first()
        if event_exists:
            result = connection.execute(text("PRAGMA table_info(event)")).fetchall()
            existing_event_cols = {row[1] for row in result}
            
            event_migrations = [
                ("served_by_player_id", "INTEGER"),
                ("penalty_type_code", "VARCHAR(10)"),
                ("zone_code", "VARCHAR(10)"),
                ("x_coordinate_normalized", "FLOAT"),
                ("y_coordinate_normalized", "FLOAT")
            ]
            
            for col_name, col_type in event_migrations:
                if col_name not in existing_event_cols:
                    logger.info(f"Migrating: Adding column '{col_name}' to 'event' table")
                    connection.execute(text(f"ALTER TABLE event ADD COLUMN {col_name} {col_type}"))

        # 4. Check game table status column rename
        game_exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='game'"
        )).first()
        if game_exists:
            result = connection.execute(text("PRAGMA table_info(game)")).fetchall()
            existing_game_cols = {row[1] for row in result}
            if "game_status" in existing_game_cols and "nhl_game_state" not in existing_game_cols:
                logger.info("Migrating: Renaming column 'game_status' to 'nhl_game_state' in 'game' table")
                connection.execute(text("ALTER TABLE game RENAME COLUMN game_status TO nhl_game_state"))

        # 5. Check shot table coordinate column rename
        shot_exists = connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shot'"
        )).first()
        if shot_exists:
            result = connection.execute(text("PRAGMA table_info(shot)")).fetchall()
            existing_shot_cols = {row[1] for row in result}
            if "x_coordinate" in existing_shot_cols and "x_coordinate_normalized" not in existing_shot_cols:
                logger.info("Migrating: Renaming column 'x_coordinate' to 'x_coordinate_normalized' in 'shot' table")
                connection.execute(text("ALTER TABLE shot RENAME COLUMN x_coordinate TO x_coordinate_normalized"))
            if "y_coordinate" in existing_shot_cols and "y_coordinate_normalized" not in existing_shot_cols:
                logger.info("Migrating: Renaming column 'y_coordinate' to 'y_coordinate_normalized' in 'shot' table")
                connection.execute(text("ALTER TABLE shot RENAME COLUMN y_coordinate TO y_coordinate_normalized"))
            
        db.session.commit()
        logger.info("Database migration check completed successfully.")
    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to run database migrations")
