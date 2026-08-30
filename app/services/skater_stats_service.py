from sqlalchemy import or_
from app.models import db, Shot, Event
from app.services.possession_service import PossessionService

class SkaterStatsService:
    """Service for computing skater counting stats, Corsi/Fenwick metrics, and expected goals."""

    @classmethod
    def calculate_skater_stats(cls, game_id: int, player_id: int) -> dict:
        goals = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'goal',
            Event.primary_player_id == player_id,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        assists = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'goal',
            or_(
                Event.assist1_player_id == player_id,
                Event.assist2_player_id == player_id
            ),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        points = goals + assists
        
        # Skater shots on goal: outcome in ['Goal', 'Saved']
        shots = db.session.query(Shot).join(Event).filter(
            Event.game_id == game_id,
            Shot.shooter_id == player_id,
            Shot.outcome.in_(['Goal', 'Saved']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        hits_delivered = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'hit',
            Event.primary_player_id == player_id
        ).count()
        
        pim = db.session.query(db.func.sum(Event.penalty_duration)).filter(
            Event.game_id == game_id,
            Event.event_type == 'penalty',
            Event.primary_player_id == player_id
        ).scalar() or 0
        
        faceoffs_won = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'faceoff',
            Event.primary_player_id == player_id
        ).count()
        
        faceoffs_lost = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'faceoff',
            Event.secondary_player_id == player_id
        ).count()
        
        total_faceoffs = faceoffs_won + faceoffs_lost
        faceoff_pct = round((faceoffs_won / total_faceoffs * 100), 1) if total_faceoffs > 0 else 0.0
        
        # Get possession metrics from PossessionService (mode="5v5")
        possession = PossessionService.calculate_possession_stats(game_id, mode="5v5")
        p_poss = possession.get(player_id, {"cf": 0, "ca": 0, "cf_pct": None, "ff": 0, "fa": 0, "ff_pct": None})
        
        # Calculate player Expected Goals (xG)
        player_xg_val = db.session.query(db.func.sum(Shot.xg)).join(Event).filter(
            Event.game_id == game_id,
            Shot.shooter_id == player_id,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).scalar()
        player_xg = round(player_xg_val, 2) if player_xg_val is not None else 0.0
        
        return {
            "goals": goals,
            "assists": assists,
            "points": points,
            "shots": shots,
            "hits": hits_delivered,
            "pim": pim,
            "faceoffs_won": faceoffs_won,
            "faceoffs_lost": faceoffs_lost,
            "faceoff_pct": faceoff_pct,
            "cf": p_poss.get("cf", 0),
            "ca": p_poss.get("ca", 0),
            "cf_pct": p_poss.get("cf_pct", None),
            "ff": p_poss.get("ff", 0),
            "fa": p_poss.get("fa", 0),
            "ff_pct": p_poss.get("ff_pct", None),
            "xg": player_xg
        }
