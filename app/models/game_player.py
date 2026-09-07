from app.models.base import db

class GamePlayer(db.Model):
    """GamePlayer database model representing roster membership of a player in a specific game."""
    __tablename__ = 'game_player'

    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), primary_key=True, nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), primary_key=True, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=False, index=True)
    position = db.Column(db.String(10), nullable=True)
    sweater_number = db.Column(db.Integer, nullable=True)

    # Relationships
    game = db.relationship('Game', back_populates='roster_entries')
    player = db.relationship('Player', back_populates='game_rosters')
    team = db.relationship('Team', back_populates='game_rosters')

    def __repr__(self):
        return f"<GamePlayer Game={self.game_id} Player={self.player_id} Team={self.team_id} Pos={self.position}>"
