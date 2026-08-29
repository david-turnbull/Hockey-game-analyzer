from app.models.base import db

class Event(db.Model):
    """Event database model representing a play-by-play game event."""
    __tablename__ = 'event'

    # Primary key format: {game_id}_{event_idx}
    event_id = db.Column(db.String(100), primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), nullable=False, index=True)
    period = db.Column(db.Integer, nullable=False)
    period_time = db.Column(db.String(5), nullable=False)  # e.g., '19:59'
    elapsed_game_seconds = db.Column(db.Integer, nullable=True)  # overall game clock in seconds, nullable for invalid clocks
    event_type = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'Shot', 'Goal', 'Penalty', 'Hit'
    team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=True, index=True)
    
    primary_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True, index=True)
    secondary_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    assist1_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    assist2_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    served_by_player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    
    penalty_duration = db.Column(db.Integer, nullable=True)  # in minutes
    penalty_description = db.Column(db.String(100), nullable=True)
    penalty_type_code = db.Column(db.String(10), nullable=True)
    zone_code = db.Column(db.String(10), nullable=True)
    
    x_coordinate = db.Column(db.Float, nullable=True)
    y_coordinate = db.Column(db.Float, nullable=True)
    x_coordinate_normalized = db.Column(db.Float, nullable=True)
    y_coordinate_normalized = db.Column(db.Float, nullable=True)
    strength_state = db.Column(db.String(20), nullable=True)  # e.g., '5v5', '5v4', 'PP', 'SH'
    
    # Milestone 5.5: Data Correctness & Hardening fields
    period_type = db.Column(db.String(10), nullable=True)
    raw_situation_code = db.Column(db.String(4), nullable=True)
    home_skaters = db.Column(db.Integer, nullable=True)
    away_skaters = db.Column(db.Integer, nullable=True)
    team_strength_state = db.Column(db.String(10), nullable=True)
    manpower_state = db.Column(db.String(20), nullable=True)

    __table_args__ = (
        db.Index('idx_event_game_type', 'game_id', 'event_type'),
        db.Index('idx_event_game_team', 'game_id', 'team_id'),
    )

    # Relationships
    game = db.relationship('Game', back_populates='events')
    team = db.relationship('Team')
    
    primary_player = db.relationship('Player', foreign_keys=[primary_player_id])
    secondary_player = db.relationship('Player', foreign_keys=[secondary_player_id])
    assist1_player = db.relationship('Player', foreign_keys=[assist1_player_id])
    assist2_player = db.relationship('Player', foreign_keys=[assist2_player_id])
    served_by_player = db.relationship('Player', foreign_keys=[served_by_player_id])
    
    # One-to-one or optional one-to-one relationship with Shot
    shot = db.relationship('Shot', back_populates='event', uselist=False, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Event {self.event_id}: {self.event_type} (P{self.period} - {self.period_time})>"
