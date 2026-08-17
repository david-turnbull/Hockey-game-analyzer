from app.models import db, Game, Team
from sqlalchemy import or_

class GameService:
    """Service class encapsulating queries for games, teams, and seasons."""

    @staticmethod
    def get_available_seasons() -> list:
        """Retrieves a list of all distinct seasons present in the database."""
        seasons = db.session.query(Game.season).distinct().order_by(Game.season.desc()).all()
        return [s[0] for s in seasons]

    @staticmethod
    def get_available_teams() -> list:
        """Retrieves a list of all teams present in the database, sorted alphabetically."""
        return Team.query.order_by(Team.name).all()

    @staticmethod
    def get_games_list(team_id: int, season: str) -> list:
        """
        Retrieves a list of games for a specific team and season.
        Formats data suitable for direct JSON serialization and rendering.
        """
        games = Game.query.filter(
            Game.season == season,
            or_(Game.home_team_id == team_id, Game.away_team_id == team_id)
        ).order_by(Game.game_date.asc()).all()

        formatted_games = []
        for g in games:
            is_home = (g.home_team_id == team_id)
            opponent = g.away_team if is_home else g.home_team
            
            # Format date to string
            date_str = g.game_date.strftime("%Y-%m-%d")
            
            formatted_games.append({
                "game_id": g.game_id,
                "date": date_str,
                "game_type": g.game_type,
                "home_team_abbrev": g.home_team.abbreviation,
                "away_team_abbrev": g.away_team.abbreviation,
                "home_score": g.home_score,
                "away_score": g.away_score,
                "opponent_abbrev": opponent.abbreviation,
                "opponent_name": opponent.name,
                "is_home": is_home,
                "game_status": g.game_status
            })
            
        return formatted_games

    @staticmethod
    def get_game_overview_stats(game_id: int) -> dict:
        """
        Calculates all boxscore statistics, team comparison metrics,
        and chronological timelines (goals and penalties) for a game.
        """
        from app.models import Event, Shot, Player
        
        game = db.session.get(Game, game_id)
        if not game:
            return None
            
        home_team = game.home_team
        away_team = game.away_team
        
        # 1. Calculate Faceoff metrics
        home_faceoffs_won = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'faceoff',
            Event.team_id == game.home_team_id
        ).count()
        
        away_faceoffs_won = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.event_type == 'faceoff',
            Event.team_id == game.away_team_id
        ).count()
        
        total_faceoffs = home_faceoffs_won + away_faceoffs_won
        home_fo_pct = round((home_faceoffs_won / total_faceoffs * 100), 1) if total_faceoffs > 0 else 50.0
        away_fo_pct = round((away_faceoffs_won / total_faceoffs * 100), 1) if total_faceoffs > 0 else 50.0
        
        # 2. Calculate Shots on Goal metrics (shots + goals)
        home_sog = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.home_team_id,
            Event.event_type.in_(['shot-on-goal', 'goal'])
        ).count()
        
        away_sog = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.away_team_id,
            Event.event_type.in_(['shot-on-goal', 'goal'])
        ).count()
        
        # 3. Calculate Shooting percentages
        home_shooting_pct = round((game.home_score / home_sog * 100), 1) if home_sog > 0 else 0.0
        away_shooting_pct = round((game.away_score / away_sog * 100), 1) if away_sog > 0 else 0.0
        
        # 4. Calculate Penalty Minutes (PIM)
        home_pim_res = db.session.query(db.func.sum(Event.penalty_duration)).filter(
            Event.game_id == game_id,
            Event.team_id == game.home_team_id,
            Event.event_type == 'penalty'
        ).scalar()
        
        away_pim_res = db.session.query(db.func.sum(Event.penalty_duration)).filter(
            Event.game_id == game_id,
            Event.team_id == game.away_team_id,
            Event.event_type == 'penalty'
        ).scalar()
        
        home_pim = home_pim_res or 0
        away_pim = away_pim_res or 0
        
        # 5. Calculate Power Play Goals
        goals = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type == 'goal'
        ).all()
        
        home_ppg = 0
        away_ppg = 0
        for goal in goals:
            if goal.strength_state and 'v' in goal.strength_state:
                try:
                    h_skaters, a_skaters = map(int, goal.strength_state.split('v'))
                    if goal.team_id == game.home_team_id and h_skaters > a_skaters:
                        home_ppg += 1
                    elif goal.team_id == game.away_team_id and a_skaters > h_skaters:
                        away_ppg += 1
                except ValueError:
                    pass
                    
        # 6. Fetch Scoring and Penalty Events chronologically
        timeline_events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(['goal', 'penalty'])
        ).order_by(Event.period.asc(), Event.elapsed_game_seconds.asc()).all()
        
        # Build chronological timeline
        timeline = []
        running_home_score = 0
        running_away_score = 0
        
        for event in timeline_events:
            team = home_team if event.team_id == game.home_team_id else away_team
            is_home_event = (event.team_id == game.home_team_id)
            
            event_data = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "period": event.period,
                "period_time": event.period_time,
                "elapsed_game_seconds": event.elapsed_game_seconds,
                "team_abbrev": team.abbreviation if team else "",
                "is_home_event": is_home_event,
                "strength_state": event.strength_state
            }
            
            if event.event_type == 'goal':
                if is_home_event:
                    running_home_score += 1
                else:
                    running_away_score += 1
                    
                scorer = event.primary_player.full_name if event.primary_player else "Unknown"
                assist1 = event.assist1_player.full_name if event.assist1_player else None
                assist2 = event.assist2_player.full_name if event.assist2_player else None
                
                assists_str = ""
                if assist1 and assist2:
                    assists_str = f"Assists: {assist1}, {assist2}"
                elif assist1:
                    assists_str = f"Assist: {assist1}"
                else:
                    assists_str = "Unassisted"
                    
                event_data.update({
                    "scorer": scorer,
                    "assists": assists_str,
                    "running_score": f"{running_away_score} - {running_home_score}",
                    "shot_type": event.shot.shot_type if event.shot else "unknown"
                })
            elif event.event_type == 'penalty':
                player = event.primary_player.full_name if event.primary_player else "Unknown"
                drawn_by = event.secondary_player.full_name if event.secondary_player else None
                
                event_data.update({
                    "player": player,
                    "infraction": event.penalty_description or "Unknown infraction",
                    "duration": event.penalty_duration or 2,
                    "drawn_by": drawn_by
                })
                
            timeline.append(event_data)
            
        # Group timeline by period
        periods_timeline = {}
        for ev in timeline:
            p_num = ev["period"]
            periods_timeline.setdefault(p_num, []).append(ev)
            
        # Format periods nicely (e.g. 1 -> "1st Period")
        formatted_periods = {}
        for p_num, evs in periods_timeline.items():
            label = f"{p_num}st Period" if p_num == 1 else (f"{p_num}nd Period" if p_num == 2 else (f"{p_num}rd Period" if p_num == 3 else "Overtime"))
            formatted_periods[label] = evs
            
        return {
            "game_id": game.game_id,
            "season": game.season,
            "game_date": game.game_date,
            "game_type": game.game_type,
            "game_status": game.game_status,
            "home_team_id": game.home_team_id,
            "home_team_name": home_team.name,
            "home_team_abbrev": home_team.abbreviation,
            "home_score": game.home_score,
            "away_team_id": game.away_team_id,
            "away_team_name": away_team.name,
            "away_team_abbrev": away_team.abbreviation,
            "away_score": game.away_score,
            
            # Team stats
            "stats": {
                "home_sog": home_sog,
                "away_sog": away_sog,
                "home_shooting_pct": home_shooting_pct,
                "away_shooting_pct": away_shooting_pct,
                "home_pim": home_pim,
                "away_pim": away_pim,
                "home_fo_pct": home_fo_pct,
                "away_fo_pct": away_fo_pct,
                "home_ppg": home_ppg,
                "away_ppg": away_ppg
            },
            
            # Timeline grouped by period
            "timeline": formatted_periods
        }
