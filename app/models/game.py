from app.models.base import db

class Game(db.Model):
    """Game database model representing an NHL game."""
    __tablename__ = 'game'

    game_id = db.Column(db.Integer, primary_key=True)  # NHL API game id (e.g. 2023020001)
    season = db.Column(db.String(8), nullable=False)   # e.g., '20232024'
    game_date = db.Column(db.Date, nullable=False)
    game_type = db.Column(db.String(2))                # 'R' (regular) or 'P' (playoff)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=False)
    home_score = db.Column(db.Integer, default=0, nullable=False)
    away_score = db.Column(db.Integer, default=0, nullable=False)
    game_status = db.Column(db.String(20))             # Final, Live, Preview, etc.

    # Relationships
    home_team = db.relationship('Team', foreign_keys=[home_team_id], back_populates='home_games')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], back_populates='away_games')
    
    events = db.relationship('Event', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    shifts = db.relationship('Shift', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Game {self.game_id}: {self.away_team_id} @ {self.home_team_id} ({self.season})>"
