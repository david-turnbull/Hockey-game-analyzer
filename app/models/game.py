from datetime import datetime
from typing import Optional
from app.models.base import db

class Game(db.Model):
    """Game database model representing an NHL game."""
    __tablename__ = 'game'

    game_id = db.Column(db.Integer, primary_key=True)  # NHL API game id (e.g. 2023020001)
    season = db.Column(db.String(8), nullable=False)   # e.g., '20232024'
    game_date = db.Column(db.Date, nullable=False)
    start_time_utc = db.Column(db.DateTime, nullable=True)
    game_type = db.Column(db.String(2))                # 'R' (regular) or 'P' (playoff)
    home_team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=False)
    away_team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=False)
    home_score = db.Column(db.Integer, default=0, nullable=False)
    away_score = db.Column(db.Integer, default=0, nullable=False)
    nhl_game_state = db.Column(db.String(20))             # Raw NHL game state code (e.g. OFF, LIVE, FUT)
    data_source = db.Column(db.String(50), default='nhl_api', nullable=False) # 'nhl_api' or 'synthetic_test'

    @property
    def start_time(self):
        if self.start_time_utc:
            return self.start_time_utc
        from datetime import datetime, time
        return datetime.combine(self.game_date, time.min)

    @property
    def game_status(self):
        return self.nhl_game_state

    @game_status.setter
    def game_status(self, value):
        self.nhl_game_state = value

    # Relationships
    home_team = db.relationship('Team', foreign_keys=[home_team_id], back_populates='home_games')
    away_team = db.relationship('Team', foreign_keys=[away_team_id], back_populates='away_games')
    
    events = db.relationship('Event', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    shifts = db.relationship('Shift', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    roster_entries = db.relationship('GamePlayer', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')
    predictions = db.relationship('GamePrediction', back_populates='game', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Game {self.game_id}: {self.away_team_id} @ {self.home_team_id} ({self.season})>"


class GamePrediction(db.Model):
    """Immutable prediction snapshot for a game prior to puck drop."""
    __tablename__ = 'game_prediction'

    prediction_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    home_win_probability = db.Column(db.Float, nullable=False)
    away_win_probability = db.Column(db.Float, nullable=False)
    expected_home_goals = db.Column(db.Float, nullable=False)
    expected_away_goals = db.Column(db.Float, nullable=False)
    
    score_matrix_json = db.Column(db.Text, nullable=True)
    feature_importance_json = db.Column(db.Text, nullable=True)
    model_version = db.Column(db.String(50), default='v1.4.0', nullable=False)
    is_official = db.Column(db.Boolean, default=True, nullable=False)

    # Immutable dynamic resolution of outcome via relationship (never stored/mutated on prediction)
    game = db.relationship('Game', back_populates='predictions')

    @property
    def is_outcome_resolved(self) -> bool:
        return self.game.nhl_game_state in ['OFF', 'FINAL', 'OVER'] if self.game else False

    @property
    def actual_winner(self) -> Optional[str]:
        if not self.is_outcome_resolved or not self.game:
            return None
        if self.game.home_score > self.game.away_score:
            return 'home'
        elif self.game.away_score > self.game.home_score:
            return 'away'
        return 'tie'

    def __repr__(self):
        return f"<GamePrediction {self.prediction_id} for Game {self.game_id}: P(Home)={self.home_win_probability}>"

