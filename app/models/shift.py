from app.models.base import db

class Shift(db.Model):
    """Shift database model representing a player's shift on the ice."""
    __tablename__ = 'shift'

    # Primary key format: {game_id}_{player_id}_{period}_{start_elapsed_seconds}
    shift_id = db.Column(db.String(100), primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=False)
    period = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)  # e.g., '00:00'
    end_time = db.Column(db.String(5), nullable=False)    # e.g., '00:45'
    start_elapsed_seconds = db.Column(db.Integer, nullable=False)
    end_elapsed_seconds = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # shift duration in seconds

    # Relationships
    game = db.relationship('Game', back_populates='shifts')
    player = db.relationship('Player', back_populates='shifts')

    def __repr__(self):
        return f"<Shift {self.shift_id}: P{self.period} Player={self.player_id} ({self.duration}s)>"
