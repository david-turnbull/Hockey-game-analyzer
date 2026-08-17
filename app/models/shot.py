from app.models.base import db

class Shot(db.Model):
    """Shot database model representing details of a shot event."""
    __tablename__ = 'shot'

    shot_id = db.Column(db.String(100), db.ForeignKey('event.event_id'), primary_key=True)
    shooter_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=False)
    goalie_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), nullable=True)
    shot_type = db.Column(db.String(50))  # e.g., Slap, Wrist, Snap, Backhand, Tip-In
    
    # Coordinates (already normalized to positive/negative values or standardized direction)
    x_coordinate = db.Column(db.Float, nullable=False)
    y_coordinate = db.Column(db.Float, nullable=False)
    
    distance = db.Column(db.Float)  # Distance in feet to the center of net
    angle = db.Column(db.Float)     # Angle in degrees relative to the center of net
    outcome = db.Column(db.String(50), nullable=False)  # e.g., Saved, Goal, Missed, Blocked
    goal = db.Column(db.Boolean, default=False, nullable=False)
    strength_state = db.Column(db.String(20))
    empty_net = db.Column(db.Boolean, default=False)
    xg = db.Column(db.Float, nullable=True)  # Expected goals prediction (when model is built)

    # Relationships
    event = db.relationship('Event', back_populates='shot')
    shooter = db.relationship('Player', foreign_keys=[shooter_id], back_populates='shots_taken')
    goalie = db.relationship('Player', foreign_keys=[goalie_id], back_populates='shots_faced')

    def __repr__(self):
        return f"<Shot {self.shot_id}: Goal={self.goal} by {self.shooter_id}>"
