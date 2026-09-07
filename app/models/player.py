from app.models.base import db

class Player(db.Model):
    """Player database model representing an NHL player."""
    __tablename__ = 'player'

    player_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(10))  # C, LW, RW, D, G
    shoots_catches = db.Column(db.String(1))  # L or R
    current_team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), nullable=True)
    
    # Extended metadata fields
    headshot_url = db.Column(db.String(500), nullable=True)
    sweater_number = db.Column(db.Integer, nullable=True)
    height_in_inches = db.Column(db.Integer, nullable=True)
    height_in_centimeters = db.Column(db.Integer, nullable=True)
    weight_in_pounds = db.Column(db.Integer, nullable=True)
    weight_in_kilograms = db.Column(db.Integer, nullable=True)
    birth_date = db.Column(db.String(20), nullable=True)
    birth_city = db.Column(db.String(100), nullable=True)
    birth_country = db.Column(db.String(100), nullable=True)


    # Relationships
    current_team = db.relationship('Team', back_populates='players')
    game_rosters = db.relationship('GamePlayer', back_populates='player', lazy='dynamic')
    
    # Explicitly specify foreign_keys in Shot relationships to distinguish shooter/goalie
    shots_taken = db.relationship('Shot', foreign_keys='Shot.shooter_id', back_populates='shooter', lazy='dynamic')
    shots_faced = db.relationship('Shot', foreign_keys='Shot.goalie_id', back_populates='goalie', lazy='dynamic')
    
    shifts = db.relationship('Shift', back_populates='player', lazy='dynamic')

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def position_code(self):
        return self.position

    @position_code.setter
    def position_code(self, value):
        self.position = value

    def __repr__(self):
        return f"<Player {self.full_name} ({self.position})>"
