from sqlalchemy import or_
from app.models import Event

class PlayerTimelineService:
    """Service for retrieving and formatting a chronological list of events for a player."""

    @staticmethod
    def get_player_timeline(game_id: int, player_id: int, home_team_id: int, home_team_abbr: str, away_team_abbr: str) -> list:
        # Fetch player events
        player_events = Event.query.filter(
            Event.game_id == game_id,
            or_(
                Event.primary_player_id == player_id,
                Event.secondary_player_id == player_id,
                Event.assist1_player_id == player_id,
                Event.assist2_player_id == player_id
            )
        ).order_by(Event.period.asc(), Event.elapsed_game_seconds.asc()).all()
        
        timeline = []
        for event in player_events:
            is_home_event = (event.team_id == home_team_id)
            event_team_abbr = home_team_abbr if is_home_event else away_team_abbr
            
            event_data = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "period": event.period,
                "period_time": event.period_time,
                "elapsed_game_seconds": event.elapsed_game_seconds,
                "team_abbrev": event_team_abbr,
                "strength_state": event.strength_state,
                "period_type": event.period_type
            }
            
            desc = ""
            if event.event_type == 'goal':
                scorer = event.primary_player.full_name if event.primary_player else "Unknown"
                if event.primary_player_id == player_id:
                    desc = f"Scored a goal ({event.strength_state})"
                elif event.assist1_player_id == player_id or event.assist2_player_id == player_id:
                    desc = f"Assisted on scorer {scorer}'s goal ({event.strength_state})"
                else:
                    desc = f"Goal by {scorer} ({event.strength_state})"
            elif event.event_type == 'shot-on-goal':
                if event.primary_player_id == player_id:
                    desc = "Shot on goal (saved)"
                elif event.secondary_player_id == player_id:
                    desc = f"Saved shot from {event.primary_player.full_name if event.primary_player else 'Unknown'}"
            elif event.event_type == 'missed-shot':
                if event.primary_player_id == player_id:
                    desc = "Shot missed net"
                elif event.secondary_player_id == player_id:
                    desc = f"Shot from {event.primary_player.full_name if event.primary_player else 'Unknown'} missed net"
            elif event.event_type == 'blocked-shot':
                if event.primary_player_id == player_id:
                    desc = f"Shot blocked by opponent"
            elif event.event_type == 'hit':
                hitter = event.primary_player.full_name if event.primary_player else "Unknown"
                hittee = event.secondary_player.full_name if event.secondary_player else "Unknown"
                if event.primary_player_id == player_id:
                    desc = f"Delivered a hit on {hittee}"
                else:
                    desc = f"Received a hit from {hitter}"
            elif event.event_type == 'penalty':
                infraction = event.penalty_description or "Unknown infraction"
                dur = event.penalty_duration or 2
                if event.primary_player_id == player_id:
                    desc = f"Committed a {dur}-min penalty ({infraction})"
                else:
                    desc = f"Drawn a penalty committed by {event.primary_player.full_name if event.primary_player else 'Unknown'}"
            elif event.event_type == 'faceoff':
                winner = event.primary_player.full_name if event.primary_player else "Unknown"
                loser = event.secondary_player.full_name if event.secondary_player else "Unknown"
                if event.primary_player_id == player_id:
                    desc = f"Won faceoff against {loser}"
                else:
                    desc = f"Lost faceoff against {winner}"
                    
            event_data["description"] = desc
            timeline.append(event_data)
            
        return timeline
