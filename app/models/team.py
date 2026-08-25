from app.models.base import db

class Team(db.Model):
    """Team database model representing an NHL team."""
    __tablename__ = 'team'

    team_id = db.Column(db.Integer, primary_key=True)
    abbreviation = db.Column(db.String(3), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)

    # Relationships
    players = db.relationship('Player', back_populates='current_team', lazy='select')
    game_rosters = db.relationship('GamePlayer', back_populates='team', lazy='dynamic')
    
    # We specify foreign_keys explicitly in Game relationships to distinguish home/away
    home_games = db.relationship('Game', foreign_keys='Game.home_team_id', back_populates='home_team', lazy='dynamic')
    away_games = db.relationship('Game', foreign_keys='Game.away_team_id', back_populates='away_team', lazy='dynamic')

    def __repr__(self):
        return f"<Team {self.abbreviation} - {self.name}>"
