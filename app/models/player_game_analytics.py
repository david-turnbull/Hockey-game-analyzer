from datetime import datetime, timezone
from app.models.base import db

class PlayerGameAnalytics(db.Model):
    """
    Canonical derived analytical data layer storing per-game player statistics
    and additive 5v5 primitives.

    Primary Key Rationale:
    The primary key is defined as (game_id, player_id, team_id).
    Retaining team_id in the primary key:
    1. Cleanly mirrors GamePlayer schema conventions where roster entries are scoped by game, player, and team.
    2. Enables fast, index-backed team-level filtering and direct SQL aggregations (e.g., GROUP BY team_id) without requiring additional joins.
    3. Explicitly ties each analytics row to the player's recorded team for that game.
    Note: The current PlayerGameAnalyticsBuilder assumes one team record per player per game (skater_meta is keyed by player_id).
    """
    __tablename__ = 'player_game_analytics'

    game_id = db.Column(db.Integer, db.ForeignKey('game.game_id'), primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.player_id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('team.team_id'), primary_key=True)

    season = db.Column(db.String(10), nullable=False, index=True)
    position = db.Column(db.String(10), nullable=True)

    # Individual Counting Statistics
    toi_seconds = db.Column(db.Integer, default=0, nullable=False)
    toi_5v5_seconds = db.Column(db.Integer, default=0, nullable=False)
    goals = db.Column(db.Integer, default=0, nullable=False)
    assists = db.Column(db.Integer, default=0, nullable=False)
    primary_assists = db.Column(db.Integer, default=0, nullable=False)
    secondary_assists = db.Column(db.Integer, default=0, nullable=False)
    points = db.Column(db.Integer, default=0, nullable=False)
    shots_on_goal = db.Column(db.Integer, default=0, nullable=False)
    unblocked_attempts = db.Column(db.Integer, default=0, nullable=False)
    individual_xg = db.Column(db.Float, default=0.0, nullable=False)

    # 5v5 On-Ice Additive Primitives
    cf_5v5 = db.Column(db.Integer, default=0, nullable=False)
    ca_5v5 = db.Column(db.Integer, default=0, nullable=False)
    ff_5v5 = db.Column(db.Integer, default=0, nullable=False)
    fa_5v5 = db.Column(db.Integer, default=0, nullable=False)
    xgf_5v5 = db.Column(db.Float, default=0.0, nullable=False)
    xga_5v5 = db.Column(db.Float, default=0.0, nullable=False)

    # Metadata & Auditing
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.Index('idx_pga_season_player', 'season', 'player_id'),
        db.Index('idx_pga_season_team', 'season', 'team_id'),
        db.Index('idx_pga_game_id', 'game_id'),
    )

    # Relationships
    game = db.relationship('Game')
    player = db.relationship('Player')
    team = db.relationship('Team')

    def __repr__(self):
        return (
            f"<PlayerGameAnalytics Game={self.game_id} Player={self.player_id} Team={self.team_id} "
            f"G={self.goals} A={self.assists} P={self.points} 5v5_TOI={self.toi_5v5_seconds}s>"
        )
