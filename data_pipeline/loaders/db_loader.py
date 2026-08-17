import logging
from sqlalchemy import delete
from app.models import db, Team, Player, Game, Event, Shot, Shift

logger = logging.getLogger(__name__)

class DatabaseLoader:
    """Handles loading normalized NHL data models to the database with transaction safety."""
    
    def __init__(self, session=None):
        self.session = session or db.session

    def load_game_data(self, game: Game, teams: list, players: list, events: list, shots: list, shifts: list) -> bool:
        """
        Loads all structured models for a game into the database.
        Clears existing events, shots, and shifts for the game_id to maintain idempotency.
        
        Returns:
            True if loaded successfully, False otherwise.
        """
        logger.info(f"Loading game data to database for Game ID: {game.game_id}")
        try:
            # 1. Upsert Teams (avoid duplicates)
            for team in teams:
                existing_team = self.session.get(Team, team.team_id)
                if existing_team:
                    existing_team.abbreviation = team.abbreviation
                    existing_team.name = team.name
                else:
                    self.session.add(team)
            
            # Flush teams so players can reference them
            self.session.flush()

            # 2. Upsert Players (avoid duplicates)
            for player in players:
                existing_player = self.session.get(Player, player.player_id)
                if existing_player:
                    existing_player.first_name = player.first_name
                    existing_player.last_name = player.last_name
                    existing_player.position = player.position
                    existing_player.shoots_catches = player.shoots_catches
                    existing_player.current_team_id = player.current_team_id
                else:
                    self.session.add(player)
            
            # Flush players
            self.session.flush()

            # 3. Handle Idempotence: Clear previous entries for this game
            game_id = game.game_id
            
            # Delete old shifts
            self.session.execute(delete(Shift).where(Shift.game_id == game_id))
            
            # Delete old shots (linked to events of this game)
            # SQLite supports delete with where in subquery
            self.session.execute(
                delete(Shot).where(Shot.shot_id.in_(
                    self.session.query(Event.event_id).filter(Event.game_id == game_id)
                ))
            )
            
            # Delete old events
            self.session.execute(delete(Event).where(Event.game_id == game_id))
            
            # Update game record if exists, otherwise add it
            existing_game = self.session.get(Game, game_id)
            if existing_game:
                existing_game.season = game.season
                existing_game.game_date = game.game_date
                existing_game.game_type = game.game_type
                existing_game.home_team_id = game.home_team_id
                existing_game.away_team_id = game.away_team_id
                existing_game.home_score = game.home_score
                existing_game.away_score = game.away_score
                existing_game.game_status = game.game_status
            else:
                self.session.add(game)
                
            self.session.flush()

            for event in events:
                self.session.add(event)
            self.session.flush()

            for shot in shots:
                self.session.add(shot)
            self.session.flush()

            for shift in shifts:
                self.session.add(shift)

            # 5. Commit all changes
            self.session.commit()
            logger.info(f"Successfully committed data for game {game_id} to database.")
            return True
        except Exception as e:
            self.session.rollback()
            logger.exception(f"Failed to load game {game.game_id} to database. Rolled back.")
            return False
            
    def clear_all_game_data(self, game_id: int):
        """Clears all records associated with a game ID."""
        try:
            self.session.execute(delete(Shift).where(Shift.game_id == game_id))
            self.session.execute(
                delete(Shot).where(Shot.shot_id.in_(
                    self.session.query(Event.event_id).filter(Event.game_id == game_id)
                ))
            )
            self.session.execute(delete(Event).where(Event.game_id == game_id))
            game = self.session.get(Game, game_id)
            if game:
                self.session.delete(game)
            self.session.commit()
            logger.info(f"Cleared all database tables for game {game_id}")
        except Exception:
            self.session.rollback()
            logger.exception(f"Failed to clear game {game_id} data.")
            raise
