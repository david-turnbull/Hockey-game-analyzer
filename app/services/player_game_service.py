from sqlalchemy import or_
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer
from app.services.possession_service import PossessionService

class PlayerGameService:
    """Service handling detailed statistics, timelines, and shift charts for players per game."""

    @staticmethod
    def get_player_game_stats(game_id: int, player_id: int) -> dict:
        """
        Retrieves detailed statistics, visual chart data, and timeline
        events for a specific player in a specific game.
        Resolves player team and position historically via the GamePlayer model.
        """
        game = db.session.get(Game, game_id)
        player = db.session.get(Player, player_id)
        
        if not game or not player:
            return None
            
        home_team = game.home_team
        away_team = game.away_team
        
        # Resolve historical game-player team and position assignment authoritatively
        gp = GamePlayer.query.filter_by(game_id=game_id, player_id=player_id).first()
        if gp:
            player_team = gp.team
            is_home_player = (gp.team_id == game.home_team_id)
            position = gp.position or player.position
        else:
            player_team = home_team if player.current_team_id == game.home_team_id else away_team
            is_home_player = (player.current_team_id == game.home_team_id)
            position = player.position
            
        # Fetch shifts
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.player_id == player_id
        ).order_by(Shift.period.asc(), Shift.start_elapsed_seconds.asc()).all()
        
        # Calculate TOI and Shift metrics
        shift_count = len(shifts)
        toi_seconds = sum(s.duration for s in shifts if s.duration is not None and not s.is_anomaly)
        
        # Average shift length
        avg_shift_seconds = int(toi_seconds / shift_count) if shift_count > 0 else 0
        
        # Format TOI helper
        def format_toi(total_seconds):
            mins = total_seconds // 60
            secs = total_seconds % 60
            return f"{mins:02d}:{secs:02d}"
            
        toi_str = format_toi(toi_seconds)
        avg_shift_str = format_toi(avg_shift_seconds)
        
        # Fetch player events for timeline (only events involving this player)
        player_events = Event.query.filter(
            Event.game_id == game_id,
            or_(
                Event.primary_player_id == player_id,
                Event.secondary_player_id == player_id,
                Event.assist1_player_id == player_id,
                Event.assist2_player_id == player_id
            )
        ).order_by(Event.period.asc(), Event.elapsed_game_seconds.asc()).all()
        
        # Format events timeline
        timeline = []
        for event in player_events:
            is_home_event = (event.team_id == game.home_team_id)
            event_team_abbr = home_team.abbreviation if is_home_event else away_team.abbreviation
            
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
            
            # Describe event
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
            
        # Skater vs. Goalie metrics
        stats = {
            "player_id": player.player_id,
            "name": player.full_name,
            "position": position,
            "shoots_catches": player.shoots_catches,
            "team_name": player_team.name if player_team else "",
            "team_abbrev": player_team.abbreviation if player_team else "",
            "team_id": player_team.team_id if player_team else None,
            "is_home": is_home_player,
            "game_id": game.game_id,
            "game_date": game.game_date,
            "game_status": game.game_status,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "home_team_abbrev": home_team.abbreviation,
            "away_team_abbrev": away_team.abbreviation,
            "toi": toi_str,
            "shifts_count": shift_count,
            "avg_shift": avg_shift_str,
            "timeline": timeline,
            # Shift chart data
            "shifts_chart": [
                {
                    "period": s.period,
                    "period_type": s.period_type,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "start_seconds": s.start_elapsed_seconds - (s.period - 1) * 1200 if s.start_elapsed_seconds is not None else 0,
                    "end_seconds": s.end_elapsed_seconds - (s.period - 1) * 1200 if s.end_elapsed_seconds is not None else 0,
                    "duration": s.duration,
                    "is_anomaly": s.is_anomaly
                } for s in shifts
            ]
        }
        
        # Calculate aggregates
        if position == 'G':
            # Goalie stats
            shots_faced = db.session.query(Shot).join(Event).filter(
                Event.game_id == game_id,
                Shot.goalie_id == player_id,
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
            
            stats.update({
                "shots_faced": shots_faced,
                "goals_against": goals_against,
                "saves": saves,
                "save_pct": save_pct
            })
        else:
            # Skater stats
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
            p_poss = possession.get(player_id, {"cf": 0, "ca": 0, "cf_pct": 50.0, "ff": 0, "fa": 0, "ff_pct": 50.0})
            
            # Calculate player Expected Goals (xG)
            player_xg_val = db.session.query(db.func.sum(Shot.xg)).join(Event).filter(
                Event.game_id == game_id,
                Shot.shooter_id == player_id,
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).scalar()
            player_xg = round(player_xg_val, 2) if player_xg_val is not None else 0.0
            
            stats.update({
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
                "cf_pct": p_poss.get("cf_pct", 50.0),
                "ff": p_poss.get("ff", 0),
                "fa": p_poss.get("fa", 0),
                "ff_pct": p_poss.get("ff_pct", 50.0),
                "xg": player_xg
            })
            
        return stats
