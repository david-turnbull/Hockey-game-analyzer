from sqlalchemy import or_
from app.models import db, Shot, Event

class GoalieStatsService:
    """Service for computing goalie statistics, strength splits, and shot quality metrics."""

    @staticmethod
    def is_shot_on_goal(outcome: str) -> bool:
        """Conventional shots faced should only include goals and saved shots."""
        return outcome in ['Goal', 'Saved']

    @classmethod
    def calculate_goalie_stats(cls, game_id: int, player_id: int) -> dict:
        # Overall SOG faced (SOG only: outcome in ['Goal', 'Saved'])
        shots_faced = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        goals_against = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.goal == True,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        saves = shots_faced - goals_against
        save_pct = round((saves / shots_faced * 100), 1) if shots_faced > 0 else 0.0
        
        # Goalie 5v5 stats
        shots_faced_5v5 = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            Event.team_strength_state == '5v5',
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        goals_against_5v5 = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.goal == True,
            Event.team_strength_state == '5v5',
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        saves_5v5 = shots_faced_5v5 - goals_against_5v5
        save_pct_5v5 = round((saves_5v5 / shots_faced_5v5 * 100), 1) if shots_faced_5v5 > 0 else 0.0
        
        # Power play shots faced (Goalie playing Shorthanded / PK)
        shots_faced_pp = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            Event.manpower_state == 'PP',
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        # Goals against by strength splits
        goals_by_strength = {
            "EV": db.session.query(Shot).join(Event).filter(
                Event.game_id == game_id,
                Shot.goalie_id == player_id,
                Shot.goal == True,
                Event.manpower_state == 'EV',
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).count(),
            "PP": db.session.query(Shot).join(Event).filter(
                Event.game_id == game_id,
                Shot.goalie_id == player_id,
                Shot.goal == True,
                Event.manpower_state == 'PP',
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).count(),
            "PK": db.session.query(Shot).join(Event).filter(
                Event.game_id == game_id,
                Shot.goalie_id == player_id,
                Shot.goal == True,
                Event.manpower_state == 'PK',
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).count()
        }
        
        return {
            "shots_faced": shots_faced,
            "goals_against": goals_against,
            "saves": saves,
            "save_pct": save_pct,
            "shots_faced_5v5": shots_faced_5v5,
            "goals_against_5v5": goals_against_5v5,
            "saves_5v5": saves_5v5,
            "save_pct_5v5": save_pct_5v5,
            "shots_faced_pp": shots_faced_pp,
            "goals_by_strength": goals_by_strength
        }
