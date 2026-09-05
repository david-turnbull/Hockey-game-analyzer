from app.models.base import db

class Shot(db.Model):
    """Shot database model representing details of a shot event."""
    __tablename__ = 'shot'

    shot_id = db.Column(db.String(100), db.ForeignKey('event.event_id'), primary_key=True)
    shooter_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=False, index=True)
    goalie_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    shot_type = db.Column(db.String(50))  # e.g., Slap, Wrist, Snap, Backhand, Tip-In
    
    # Coordinates (already normalized to positive/negative values or standardized direction)
    x_coordinate_normalized = db.Column(db.Float, nullable=False)
    y_coordinate_normalized = db.Column(db.Float, nullable=False)

    @property
    def x_coordinate(self):
        return self.x_coordinate_normalized

    @x_coordinate.setter
    def x_coordinate(self, value):
        self.x_coordinate_normalized = value

    @property
    def y_coordinate(self):
        return self.y_coordinate_normalized

    @y_coordinate.setter
    def y_coordinate(self, value):
        self.y_coordinate_normalized = value
    
    distance = db.Column(db.Float)  # Distance in feet to the center of net
    angle = db.Column(db.Float)     # Angle in degrees relative to the center of net
    outcome = db.Column(db.String(50), nullable=False)  # e.g., Saved, Goal, Missed, Blocked
    goal = db.Column(db.Boolean, default=False, nullable=False)
    strength_state = db.Column(db.String(20))
    empty_net = db.Column(db.Boolean, default=False)
    xg = db.Column(db.Float, nullable=True)  # Expected goals prediction
    model_version = db.Column(db.String(50), nullable=True)  # Name/version of generating model
    
    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), nullable=True, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=True, index=True)

    __table_args__ = (
        db.Index('idx_shot_game_team', 'game_id', 'team_id'),
        db.Index('idx_shot_game_shooter', 'game_id', 'shooter_id'),
    )

    # Relationships
    event = db.relationship('Event', back_populates='shot')
    shooter = db.relationship('Player', foreign_keys=[shooter_id], back_populates='shots_taken')
    goalie = db.relationship('Player', foreign_keys=[goalie_id], back_populates='shots_faced')

    def __repr__(self):
        return f"<Shot {self.shot_id}: Goal={self.goal} by {self.shooter_id}>"
