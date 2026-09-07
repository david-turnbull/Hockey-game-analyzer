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

        # Expected Goals Against (xGA) and Goals Saved Above Expected (GSAx)
        # Excludes empty-net situations and shootouts; requires shots on goal actually faced
        xga_val = db.session.query(db.func.sum(Shot.xg)).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            Shot.empty_net == False,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).scalar()
        xga = round(xga_val, 2) if xga_val is not None else 0.0

        # Goals against on qualifying shots faced by the goalie
        ga_faced = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.goalie_id == player_id,
            Shot.goal == True,
            Shot.empty_net == False,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()

        gsax = round(xga - ga_faced, 2)

        # TOI for rates per 60
        from app.models import Shift
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.player_id == player_id,
            Shift.duration > 0,
            Shift.is_anomaly == False
        ).all()
        toi_sec = sum(s.duration for s in shifts)
        gsax_per_60 = round(gsax / (toi_sec / 3600.0), 2) if toi_sec > 0 else 0.0
        xga_per_60 = round(xga / (toi_sec / 3600.0), 2) if toi_sec > 0 else 0.0
        
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
            "goals_by_strength": goals_by_strength,
            "xga": xga,
            "gsax": gsax,
            "gsax_per_game": gsax,
            "gsax_per_60": gsax_per_60,
            "xga_per_60": xga_per_60
        }
