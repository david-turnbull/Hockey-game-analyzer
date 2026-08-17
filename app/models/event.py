from app.models.base import db

class Event(db.Model):
    """Event database model representing a play-by-play game event."""
    __tablename__ = 'event'

    # Primary key format: {game_id}_{event_idx}
    event_id = db.Column(db.String(100), primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    period_time = db.Column(db.String(5), nullable=False)  # e.g., '19:59'
    elapsed_game_seconds = db.Column(db.Integer, nullable=False)  # overall game clock in seconds
    event_type = db.Column(db.String(50), nullable=False)  # e.g., 'Shot', 'Goal', 'Penalty', 'Hit'
    team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=True)
    
    primary_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    secondary_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    assist1_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    assist2_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    
    penalty_duration = db.Column(db.Integer, nullable=True)  # in minutes
    penalty_description = db.Column(db.String(100), nullable=True)
    
    x_coordinate = db.Column(db.Float, nullable=True)
    y_coordinate = db.Column(db.Float, nullable=True)
    strength_state = db.Column(db.String(20), nullable=True)  # e.g., '5v5', '5v4', 'PP', 'SH'

    # Relationships
    game = db.relationship('Game', back_populates='events')
    team = db.relationship('Team')
    
    primary_player = db.relationship('Player', foreign_keys=[primary_player_id])
    secondary_player = db.relationship('Player', foreign_keys=[secondary_player_id])
    assist1_player = db.relationship('Player', foreign_keys=[assist1_player_id])
    assist2_player = db.relationship('Player', foreign_keys=[assist2_player_id])
    
    # One-to-one or optional one-to-one relationship with Shot
    shot = db.relationship('Shot', back_populates='event', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Event {self.event_id}: {self.event_type} (P{self.period} - {self.period_time})>"
