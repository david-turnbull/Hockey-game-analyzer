from app.models import db, Game, Team
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

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
            p_type = evs[0]["period_type"] if evs else "REG"
            if p_type == "SO":
                label = "Shootout"
            elif p_type == "OT":
                label = "Overtime"
            else:
                label = f"{p_num}st Period" if p_num == 1 else (f"{p_num}nd Period" if p_num == 2 else (f"{p_num}rd Period" if p_num == 3 else f"{p_num}th Period"))
            formatted_periods[label] = evs
            
        # Roster stats aggregation for both teams
        from app.models import Shift, Player, Event, Shot
        
        active_players = Player.query.join(Shift).filter(
            Shift.game_id == game_id
        ).distinct().options(joinedload(Player.current_team)).all()
        
        game_events = Event.query.filter(Event.game_id == game_id).all()
        game_shots = Shot.query.join(Event).filter(Event.game_id == game_id).all()
        game_shifts = Shift.query.filter(Shift.game_id == game_id).all()
        
        player_stats = {}
        for p in active_players:
            player_stats[p.player_id] = {
                "player_id": p.player_id,
                "name": p.full_name,
                "position": p.position,
                "team_id": p.current_team_id,
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
                        
        # Get possession stats (Corsi / Fenwick) for skaters
        possession = GameService.calculate_possession_stats(game_id)
        
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
                stats["cf_pct"] = p_poss.get("cf_pct", 50.0)
                stats["ff_pct"] = p_poss.get("ff_pct", 50.0)
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
            "line_combinations": GameService.get_line_combinations(game_id)
        }

    @staticmethod
    def calculate_possession_stats(game_id: int) -> dict:
        """
        Calculates even strength Corsi and Fenwick statistics (CF, CA, CF%, FF, FA, FF%)
        for all active players in a game.
        """
        from app.models import Shift, Event, Shot, Player, Game
        
        # 1. Fetch all shifts for the game (excluding anomalies)
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.is_anomaly == False
        ).all()
        
        # 2. Fetch all even-strength shot events (shot-on-goal, goal, missed-shot, blocked-shot)
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(shot_event_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None)),
            Event.manpower_state == 'EV'
        ).all()
        
        game = db.session.get(Game, game_id)
        if not game:
            return {}
            
        player_teams = {}
        player_positions = {}
        
        for s in shifts:
            player_teams[s.player_id] = s.team_id
            if s.player_id not in player_positions:
                player_positions[s.player_id] = s.player.position if s.player else "skater"
                
        player_possession = {}
        for p_id, pos in player_positions.items():
            if pos != 'G':
                player_possession[p_id] = {
                    "cf": 0,
                    "ca": 0,
                    "ff": 0,
                    "fa": 0
                }
                
        # For each even-strength shot event, determine who was on the ice
        for event in events:
            shot_team_id = event.team_id
            is_blocked = (event.event_type == 'blocked-shot')
            
            # Find active shifts covering event elapsed seconds
            on_ice_shifts = [
                s for s in shifts 
                if s.period == event.period 
                and s.start_elapsed_seconds is not None 
                and s.end_elapsed_seconds is not None
                and s.start_elapsed_seconds <= event.elapsed_game_seconds <= s.end_elapsed_seconds
            ]
            
            # Skater IDs currently on ice
            on_ice_player_ids = [
                s.player_id for s in on_ice_shifts 
                if player_positions.get(s.player_id) != 'G'
            ]
            
            for p_id in on_ice_player_ids:
                p_team_id = player_teams.get(p_id)
                if not p_team_id:
                    continue
                    
                is_for = (p_team_id == shot_team_id)
                
                if is_for:
                    player_possession[p_id]["cf"] += 1
                    if not is_blocked:
                        player_possession[p_id]["ff"] += 1
                else:
                    player_possession[p_id]["ca"] += 1
                    if not is_blocked:
                        player_possession[p_id]["fa"] += 1
                        
        player_percentages = {}
        for p_id, stats in player_possession.items():
            cf = stats["cf"]
            ca = stats["ca"]
            ff = stats["ff"]
            fa = stats["fa"]
            
            cf_pct = round((cf / (cf + ca) * 100), 1) if (cf + ca) > 0 else 50.0
            ff_pct = round((ff / (ff + fa) * 100), 1) if (ff + fa) > 0 else 50.0
            
            player_percentages[p_id] = {
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "ff": ff,
                "fa": fa,
                "ff_pct": ff_pct
            }
        return player_percentages

    @staticmethod
    def get_line_combinations(game_id: int) -> dict:
        """
        Groups skaters into forward lines (trios) and defensive pairings (duos),
        calculating TOI and on-ice statistics (Goals For/Against, SOG For/Against)
        for each combination.
        """
        from app.models import Shift, Event, Shot, Player, Game
        
        # 1. Fetch game and teams
        game = db.session.get(Game, game_id)
        if not game:
            return {}
            
        home_team_id = game.home_team_id
        away_team_id = game.away_team_id
        
        # 2. Fetch all active player details
        active_players = Player.query.join(Shift).filter(
            Shift.game_id == game_id
        ).distinct().all()
        
        player_meta = {}
        for p in active_players:
            player_meta[p.player_id] = {
                "name": p.full_name,
                "position": p.position
            }
            
        # Helper to classify positions
        is_forward = lambda p_id: player_meta.get(p_id, {}).get("position") in ['C', 'LW', 'RW', 'F']
        is_defenseman = lambda p_id: player_meta.get(p_id, {}).get("position") in ['D', 'LD', 'RD']
        
        # 3. Fetch shifts (excluding anomalies)
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.is_anomaly == False
        ).all()
        
        # Determine total game length (max shift end time)
        max_time = 3600 # default to 60 minutes
        for s in shifts:
            if s.end_elapsed_seconds is not None and s.end_elapsed_seconds > max_time:
                max_time = s.end_elapsed_seconds
                
        # 4. Populate second-by-second active players list
        home_skaters_on_ice = [set() for _ in range(max_time + 2)]
        away_skaters_on_ice = [set() for _ in range(max_time + 2)]
        
        # Map shifts to team timelines
        for s in shifts:
            p_pos = player_meta.get(s.player_id, {}).get("position")
            if p_pos == 'G':
                continue
                
            start = s.start_elapsed_seconds
            end = s.end_elapsed_seconds
            if start is None or end is None:
                continue
                
            start = max(0, start)
            end = min(max_time, end)
            
            for t in range(start, end + 1):
                if s.team_id == home_team_id:
                    home_skaters_on_ice[t].add(s.player_id)
                else:
                    away_skaters_on_ice[t].add(s.player_id)
                    
        # 5. Initialize aggregation dictionaries
        home_lines = {}  # tuple -> seconds
        home_pairings = {}
        away_lines = {}
        away_pairings = {}
        
        # Accumulate TOI second-by-second
        for t in range(1, max_time + 1):
            # Home
            h_skaters = home_skaters_on_ice[t]
            h_fwds = sorted([p for p in h_skaters if is_forward(p)])
            h_def = sorted([p for p in h_skaters if is_defenseman(p)])
            
            if len(h_fwds) == 3:
                line_tup = tuple(h_fwds)
                home_lines[line_tup] = home_lines.get(line_tup, 0) + 1
            if len(h_def) == 2:
                pair_tup = tuple(h_def)
                home_pairings[pair_tup] = home_pairings.get(pair_tup, 0) + 1
                
            # Away
            a_skaters = away_skaters_on_ice[t]
            a_fwds = sorted([p for p in a_skaters if is_forward(p)])
            a_def = sorted([p for p in a_skaters if is_defenseman(p)])
            
            if len(a_fwds) == 3:
                line_tup = tuple(a_fwds)
                away_lines[line_tup] = away_lines.get(line_tup, 0) + 1
            if len(a_def) == 2:
                pair_tup = tuple(a_def)
                away_pairings[pair_tup] = away_pairings.get(pair_tup, 0) + 1
                
        # 6. Fetch shot and goal events (excluding shootouts)
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(shot_event_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).all()
        
        # Dicts for on-ice shot/goal stats
        def init_stats():
            return {"goals_for": 0, "goals_against": 0, "sog_for": 0, "sog_against": 0}
            
        home_line_stats = {}
        home_pair_stats = {}
        away_line_stats = {}
        away_pair_stats = {}
        
        for event in events:
            t = event.elapsed_game_seconds
            if t is None or t < 0 or t > max_time:
                continue
                
            shot_team_id = event.team_id
            is_goal = (event.event_type == 'goal')
            is_sog = event.event_type in ['shot-on-goal', 'goal']
            
            # Active combinations on ice at second t
            h_skaters = home_skaters_on_ice[t]
            h_fwds = tuple(sorted([p for p in h_skaters if is_forward(p)]))
            h_def = tuple(sorted([p for p in h_skaters if is_defenseman(p)]))
            
            a_skaters = away_skaters_on_ice[t]
            a_fwds = tuple(sorted([p for p in a_skaters if is_forward(p)]))
            a_def = tuple(sorted([p for p in a_skaters if is_defenseman(p)]))
            
            # Allocate stats
            def add_event_stats(stats_dict, key, is_for):
                if len(key) not in [2, 3]:
                    return
                if key not in stats_dict:
                    stats_dict[key] = init_stats()
                if is_for:
                    if is_goal:
                        stats_dict[key]["goals_for"] += 1
                    if is_sog:
                        stats_dict[key]["sog_for"] += 1
                else:
                    if is_goal:
                        stats_dict[key]["goals_against"] += 1
                    if is_sog:
                        stats_dict[key]["sog_against"] += 1
                        
            is_home_shot = (shot_team_id == home_team_id)
            add_event_stats(home_line_stats, h_fwds, is_home_shot)
            add_event_stats(home_pair_stats, h_def, is_home_shot)
            
            is_away_shot = (shot_team_id == away_team_id)
            add_event_stats(away_line_stats, a_fwds, is_away_shot)
            add_event_stats(away_pair_stats, a_def, is_away_shot)
            
        def compile_results(toi_dict, stats_dict, expected_len):
            list_out = []
            for players_tup, seconds in toi_dict.items():
                if len(players_tup) != expected_len:
                    continue
                names = [player_meta.get(p_id, {}).get("name", "Unknown") for p_id in players_tup]
                mins = seconds // 60
                secs = seconds % 60
                toi_str = f"{mins:02d}:{secs:02d}"
                
                s = stats_dict.get(players_tup, init_stats())
                list_out.append({
                    "player_ids": list(players_tup),
                    "players": ", ".join(names),
                    "toi_seconds": seconds,
                    "toi": toi_str,
                    "goals_for": s["goals_for"],
                    "goals_against": s["goals_against"],
                    "sog_for": s["sog_for"],
                    "sog_against": s["sog_against"]
                })
            list_out.sort(key=lambda x: -x["toi_seconds"])
            return list_out
            
        home_fwds_list = compile_results(home_lines, home_line_stats, 3)
        home_def_list = compile_results(home_pairings, home_pair_stats, 2)
        away_fwds_list = compile_results(away_lines, away_line_stats, 3)
        away_def_list = compile_results(away_pairings, away_pair_stats, 2)
        
        return {
            "home": {
                "lines": home_fwds_list[:4],
                "pairings": home_def_list[:3]
            },
            "away": {
                "lines": away_fwds_list[:4],
                "pairings": away_def_list[:3]
            }
        }

    @staticmethod
    def get_player_game_stats(game_id: int, player_id: int) -> dict:
        """
        Retrieves detailed statistics, visual chart data, and timeline
        events for a specific player in a specific game.
        """
        from app.models import Game, Player, Event, Shot, Shift
        
        game = db.session.get(Game, game_id)
        player = db.session.get(Player, player_id)
        
        if not game or not player:
            return None
            
        home_team = game.home_team
        away_team = game.away_team
        player_team = home_team if player.current_team_id == game.home_team_id else away_team
        is_home_player = (player.current_team_id == game.home_team_id)
        
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
            "position": player.position,
            "shoots_catches": player.shoots_catches,
            "team_name": player_team.name if player_team else "",
            "team_abbrev": player_team.abbreviation if player_team else "",
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
        if player.position == 'G':
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
            
            # Get possession metrics
            possession = GameService.calculate_possession_stats(game_id)
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
