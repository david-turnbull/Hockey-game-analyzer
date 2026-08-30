from app.models import db, Game, Team
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from app.utils.game_status import (
    get_game_status_label,
    get_game_status_class,
)
class GameService:
    """Service class encapsulating queries for games, teams, schedules, and boxscore aggregations."""

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
                "game_status": g.game_status,
                "game_status_display": get_game_status_label(g.game_status),
                "game_status_class": get_game_status_class(g.game_status),
            })
            
        return formatted_games

    @staticmethod
    def get_game_overview_stats(game_id: int) -> dict:
        """
        Calculates all boxscore statistics, team comparison metrics,
        and chronological timelines (goals and penalties) for a game.
        """
        from app.models import Event, Shot, Player, GamePlayer, Shift
        from app.services.possession_service import PossessionService
        from app.services.line_service import LineService
        
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
        
        # 2. Calculate Shots on Goal metrics (shots + goals, excluding shootouts)
        home_sog = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.home_team_id,
            Event.event_type.in_(['shot-on-goal', 'goal']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        away_sog = db.session.query(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.away_team_id,
            Event.event_type.in_(['shot-on-goal', 'goal']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).count()
        
        # Calculate Expected Goals (xG) metrics (sum of shot xG, excluding shootouts)
        home_xg_val = db.session.query(db.func.sum(Shot.xg)).join(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.home_team_id,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).scalar()
        
        away_xg_val = db.session.query(db.func.sum(Shot.xg)).join(Event).filter(
            Event.game_id == game_id,
            Event.team_id == game.away_team_id,
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).scalar()
        
        home_xg = round(home_xg_val, 2) if home_xg_val is not None else 0.0
        away_xg = round(away_xg_val, 2) if away_xg_val is not None else 0.0
        
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
        
        # 5. Calculate Power Play Goals (excluding shootouts)
        goals = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type == 'goal',
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
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
                    
        # 6. Fetch Scoring, Penalty, Hit, Faceoff, and Blocked Shot Events chronologically
        timeline_events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(['goal', 'penalty', 'hit', 'faceoff', 'blocked-shot', 'missed-shot'])
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
                "period_type": event.period_type,
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
                served_by = event.served_by_player.full_name if event.served_by_player else None
                
                event_data.update({
                    "player": player,
                    "infraction": event.penalty_description or "Unknown infraction",
                    "duration": event.penalty_duration or 2,
                    "drawn_by": drawn_by,
                    "served_by": served_by,
                    "penalty_type": event.penalty_type_code
                })
            elif event.event_type == 'hit':
                hitter = event.primary_player.full_name if event.primary_player else "Unknown"
                hittee = event.secondary_player.full_name if event.secondary_player else "Unknown"
                event_data.update({
                    "hitter": hitter,
                    "hittee": hittee,
                    "description": f"{hitter} hit {hittee}"
                })
            elif event.event_type == 'faceoff':
                winner = event.primary_player.full_name if event.primary_player else "Unknown"
                loser = event.secondary_player.full_name if event.secondary_player else "Unknown"
                event_data.update({
                    "winner": winner,
                    "loser": loser,
                    "zone": event.zone_code,
                    "description": f"{winner} won faceoff vs {loser}"
                })
            elif event.event_type == 'blocked-shot':
                shooter = event.primary_player.full_name if event.primary_player else "Unknown"
                blocker = event.secondary_player.full_name if event.secondary_player else "Unknown"
                event_data.update({
                    "shooter": shooter,
                    "blocker": blocker,
                    "description": f"{shooter}'s shot blocked by {blocker}"
                })
            elif event.event_type == 'missed-shot':
                shooter = event.primary_player.full_name if event.primary_player else "Unknown"
                event_data.update({
                    "shooter": shooter,
                    "description": f"{shooter}'s shot missed net"
                })
                
            timeline.append(event_data)
            
        # Group timeline by period
        periods_timeline = {}
        for ev in timeline:
            p_num = ev["period"]
            periods_timeline.setdefault(p_num, []).append(ev)
            
        # Format periods nicely
        formatted_periods = {}
        for p_num, evs in periods_timeline.items():
            p_type = evs[0]["period_type"] if evs else "REG"
            if p_type == "SO":
                label = "Shootout"
            elif p_type == "OT":
                label = "Overtime"
            else:
                label = f"{p_num}st Period" if p_num == 1 else (f"{p_num}nd Period" if p_num == 2 else (f"{p_num}rd Period" if p_num == 3 else f"{p_num}th Period"))
            formatted_periods[label] = evs
            
        # Roster stats aggregation for both teams via GamePlayer (historically accurate)
        roster = GamePlayer.query.filter_by(game_id=game_id).options(joinedload(GamePlayer.player)).all()
        
        game_events = Event.query.filter(Event.game_id == game_id).all()
        game_shots = Shot.query.join(Event).filter(Event.game_id == game_id).all()
        game_shifts = Shift.query.filter(Shift.game_id == game_id).all()
        
        player_stats = {}
        for rp in roster:
            player_stats[rp.player_id] = {
                "player_id": rp.player_id,
                "name": rp.player.full_name if rp.player else f"Player {rp.player_id}",
                "position": rp.position or (rp.player.position if rp.player else "skater"),
                "team_id": rp.team_id,
                "goals": 0,
                "assists": 0,
                "points": 0,
                "shots": 0,
                "hits": 0,
                "pim": 0,
                "toi_seconds": 0,
                "shifts_count": 0,
                "shots_faced": 0,
                "goals_against": 0,
                "saves": 0,
            }
            
        # Aggregate shifts
        for s in game_shifts:
            p_id = s.player_id
            if p_id in player_stats:
                if s.duration is not None and not s.is_anomaly:
                    player_stats[p_id]["toi_seconds"] += s.duration
                player_stats[p_id]["shifts_count"] += 1
                
        # Aggregate events
        for e in game_events:
            if e.event_type == 'goal' and e.period_type != 'SO':
                if e.primary_player_id in player_stats:
                    player_stats[e.primary_player_id]["goals"] += 1
                if e.assist1_player_id in player_stats:
                    player_stats[e.assist1_player_id]["assists"] += 1
                if e.assist2_player_id in player_stats:
                    player_stats[e.assist2_player_id]["assists"] += 1
                    
            if e.event_type == 'hit':
                if e.primary_player_id in player_stats:
                    player_stats[e.primary_player_id]["hits"] += 1
                    
            if e.event_type == 'penalty':
                if e.primary_player_id in player_stats:
                    player_stats[e.primary_player_id]["pim"] += (e.penalty_duration or 2)
                    
        # Aggregate shots
        for s in game_shots:
            if s.event.period_type != 'SO':
                if s.outcome in ['Goal', 'Saved']:
                    if s.shooter_id in player_stats:
                        player_stats[s.shooter_id]["shots"] += 1
                    if s.goalie_id in player_stats:
                        player_stats[s.goalie_id]["shots_faced"] += 1
                        if s.goal:
                            player_stats[s.goalie_id]["goals_against"] += 1
                        
        # Get possession stats (Corsi / Fenwick) for skaters from PossessionService (mode="5v5")
        possession = PossessionService.calculate_possession_stats(game_id, mode="5v5")
        
        # Finalize and split rosters
        home_skaters_list = []
        home_goalies_list = []
        away_skaters_list = []
        away_goalies_list = []
        
        def format_toi(total_seconds):
            mins = total_seconds // 60
            secs = total_seconds % 60
            return f"{mins:02d}:{secs:02d}"
            
        for p_id, stats in player_stats.items():
            stats["points"] = stats["goals"] + stats["assists"]
            stats["toi"] = format_toi(stats["toi_seconds"])
            
            if stats["position"] == 'G':
                stats["saves"] = stats["shots_faced"] - stats["goals_against"]
                if stats["shots_faced"] > 0:
                    stats["save_pct"] = round((stats["saves"] / stats["shots_faced"] * 100), 1)
                else:
                    stats["save_pct"] = 0.0
                    
                if stats["team_id"] == game.home_team_id:
                    home_goalies_list.append(stats)
                else:
                    away_goalies_list.append(stats)
            else:
                p_poss = possession.get(p_id, {})
                stats["cf_pct"] = p_poss.get("cf_pct", None)
                stats["ff_pct"] = p_poss.get("ff_pct", None)
                if stats["team_id"] == game.home_team_id:
                    home_skaters_list.append(stats)
                else:
                    away_skaters_list.append(stats)
                    
        # Sort
        sort_key_skater = lambda x: (-x["points"], -x["goals"], x["name"])
        home_skaters_list.sort(key=sort_key_skater)
        away_skaters_list.sort(key=sort_key_skater)
        
        sort_key_goalie = lambda x: (-x["toi_seconds"], x["name"])
        home_goalies_list.sort(key=sort_key_goalie)
        away_goalies_list.sort(key=sort_key_goalie)
            
        return {
            "game_id": game.game_id,
            "season": game.season,
            "game_date": game.game_date,
            "game_type": game.game_type,
            "game_status": game.game_status,
            "game_status_display": get_game_status_label(game.game_status),
            "game_status_class": get_game_status_class(game.game_status),
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
                "away_ppg": away_ppg,
                "home_xg": home_xg,
                "away_xg": away_xg
            },
            
            # Timeline grouped by period
            "timeline": formatted_periods,
            
            # Rosters
            "rosters": {
                "home_skaters": home_skaters_list,
                "home_goalies": home_goalies_list,
                "away_skaters": away_skaters_list,
                "away_goalies": away_goalies_list
            },
            # Line Combinations
            "line_combinations": LineService.get_line_combinations(game_id)
        }
