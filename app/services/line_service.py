from sqlalchemy import or_
from app.models import db, Game, Shift, Event, GamePlayer
from app.services.on_ice_service import OnIceService

class LineService:
    """Service for computing forward line combinations and defensive pairings, including TOI and on-ice stats."""

    @staticmethod
    def get_line_combinations(game_id: int) -> dict:
        """
        Groups skaters into forward lines (trios) and defensive pairings (duos),
        calculating TOI and on-ice statistics (Goals For/Against, SOG For/Against)
        for each combination.
        """
        # 1. Fetch game and teams
        game = db.session.get(Game, game_id)
        if not game:
            return {}

        home_team_id = game.home_team_id
        away_team_id = game.away_team_id

        # 2. Fetch game roster players from GamePlayer mapping (historically accurate)
        roster = GamePlayer.query.filter_by(game_id=game_id).all()
        player_meta = {}
        for rp in roster:
            player_meta[rp.player_id] = {
                "name": rp.player.full_name if rp.player else f"Player {rp.player_id}",
                "position": rp.position or (rp.player.position if rp.player else "skater")
            }

        # Helper to classify positions
        FORWARD_POSITIONS = {'C', 'L', 'R', 'LW', 'RW', 'F'}
        DEFENSE_POSITIONS = {'D', 'LD', 'RD'}

        def is_forward(player_id):
            position = player_meta.get(player_id, {}).get("position")
            return position in FORWARD_POSITIONS

        def is_defenseman(player_id):
            position = player_meta.get(player_id, {}).get("position")
            return position in DEFENSE_POSITIONS

        # 3. Fetch shifts
        shifts = Shift.query.filter(
            Shift.game_id == game_id
        ).all()

        # Determine total game length (max shift end time)
        max_time = 3600  # default to 60 minutes
        for s in shifts:
            if s.end_elapsed_seconds is not None and s.end_elapsed_seconds > max_time:
                max_time = s.end_elapsed_seconds

        # 4. Populate second-by-second active players list using OnIceService
        home_players_timeline, away_players_timeline = OnIceService.build_active_players_timeline(
            shifts, max_time, home_team_id
        )

        def get_true_5v5_combinations(t):
            """
            Return the forward line and defensive pairing for both teams
            only when both teams have a complete true-5v5 unit:

            3 forwards + 2 defensemen + 1 goalie.
            """
            if t < 0 or t >= max_time:
                return None

            h_players = home_players_timeline[t]
            a_players = away_players_timeline[t]

            h_skaters = {
                p for p in h_players
                if player_meta.get(p, {}).get("position") != "G"
            }
            a_skaters = {
                p for p in a_players
                if player_meta.get(p, {}).get("position") != "G"
            }

            h_goalies = [
                p for p in h_players
                if player_meta.get(p, {}).get("position") == "G"
            ]
            a_goalies = [
                p for p in a_players
                if player_meta.get(p, {}).get("position") == "G"
            ]

            h_fwds = tuple(sorted(p for p in h_skaters if is_forward(p)))
            h_def = tuple(sorted(p for p in h_skaters if is_defenseman(p)))
            a_fwds = tuple(sorted(p for p in a_skaters if is_forward(p)))
            a_def = tuple(sorted(p for p in a_skaters if is_defenseman(p)))

            valid_5v5 = (
                len(h_skaters) == 5
                and len(a_skaters) == 5
                and len(h_fwds) == 3
                and len(h_def) == 2
                and len(a_fwds) == 3
                and len(a_def) == 2
                and len(h_goalies) == 1
                and len(a_goalies) == 1
            )

            if not valid_5v5:
                return None

            return h_fwds, h_def, a_fwds, a_def

        # 5. Initialize aggregation dictionaries
        home_lines = {}  # tuple -> seconds
        home_pairings = {}
        away_lines = {}
        away_pairings = {}

        # Accumulate TOI second-by-second
        for t in range(max_time):
            combinations = get_true_5v5_combinations(t)

            if combinations is None:
                continue

            h_fwds, h_def, a_fwds, a_def = combinations

            home_lines[h_fwds] = home_lines.get(h_fwds, 0) + 1
            away_lines[a_fwds] = away_lines.get(a_fwds, 0) + 1

            home_pairings[h_def] = home_pairings.get(h_def, 0) + 1
            away_pairings[a_def] = away_pairings.get(a_def, 0) + 1

        # 6. Fetch shot and goal events (excluding shootouts)
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(shot_event_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None)),
            Event.elapsed_game_seconds.isnot(None)
        ).all()

        def init_stats():
            return {"goals_for": 0, "goals_against": 0, "sog_for": 0, "sog_against": 0}

        home_line_stats = {}
        home_pair_stats = {}
        away_line_stats = {}
        away_pair_stats = {}

        for event in events:
            t = event.elapsed_game_seconds
            if t is None or t < 0 or t >= max_time:
                continue

            shot_team_id = event.team_id
            is_goal = (event.event_type == 'goal')
            is_sog = event.event_type in ['shot-on-goal', 'goal']

            # Active combinations on ice at second t
            combinations = get_true_5v5_combinations(t)

            if combinations is None:
                continue

            h_fwds, h_def, a_fwds, a_def = combinations

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

        def compile_results(toi_dict, stats_dict, expected_len, min_toi_seconds=0):
            list_out = []

            for players_tup, seconds in toi_dict.items():
                if len(players_tup) != expected_len:
                    continue

                if seconds < min_toi_seconds:
                    continue

                names = [
                    player_meta.get(p_id, {}).get("name", "Unknown")
                    for p_id in players_tup
                ]

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
                    "sog_against": s["sog_against"],
                })

            list_out.sort(key=lambda x: -x["toi_seconds"])

            return list_out

        MIN_FORWARD_LINE_TOI = 60

        home_fwds_list = compile_results(
            home_lines,
            home_line_stats,
            3,
            min_toi_seconds=MIN_FORWARD_LINE_TOI
        )

        away_fwds_list = compile_results(
            away_lines,
            away_line_stats,
            3,
            min_toi_seconds=MIN_FORWARD_LINE_TOI
        )

        home_def_list = compile_results(
            home_pairings,
            home_pair_stats,
            2
        )

        away_def_list = compile_results(
            away_pairings,
            away_pair_stats,
            2
        )

        return {
            "home": {
                "lines": home_fwds_list,
                "pairings": home_def_list[:5]
            },
            "away": {
                "lines": away_fwds_list,
                "pairings": away_def_list[:5]
            }
        }

    @classmethod
    def get_unit_detail(cls, game_id: int, player_ids: list) -> dict:
        """
        Computes detailed on-ice statistics, shared shifts, timeline events,
        and shot coordinates for a specific skater combination (trio or duo)
        during complete 5v5 play.
        """
        from app.models import Player, GamePlayer, Shot, Event, Team
        from app.services.on_ice_service import OnIceService
        from sqlalchemy.orm import joinedload
        
        game = db.session.get(Game, game_id)
        if not game:
            return {}

        home_team_id = game.home_team_id
        away_team_id = game.away_team_id

        # Fetch players metadata
        players = Player.query.filter(Player.player_id.in_(player_ids)).all()
        players_map = {p.player_id: p for p in players}

        # Fetch roster GamePlayer mappings for jersey and position validation
        roster = GamePlayer.query.filter(
            GamePlayer.game_id == game_id,
            GamePlayer.player_id.in_(player_ids)
        ).all()
        roster_map = {r.player_id: r for r in roster}

        # Resolve unit team
        unit_team_id = None
        if roster:
            unit_team_id = roster[0].team_id
        else:
            # fallback to player's current team
            if players:
                unit_team_id = players[0].current_team_id

        is_home_unit = (unit_team_id == home_team_id)
        unit_team = db.session.get(Team, unit_team_id) if unit_team_id else None
        opponent_team = db.session.get(Team, away_team_id if is_home_unit else home_team_id)

        # Get general game rosters
        full_roster = GamePlayer.query.filter_by(game_id=game_id).all()
        player_meta = {}
        for rp in full_roster:
            player_meta[rp.player_id] = {
                "name": rp.player.full_name if rp.player else f"Player {rp.player_id}",
                "position": rp.position or (rp.player.position if rp.player else "skater")
            }

        FORWARD_POSITIONS = {'C', 'L', 'R', 'LW', 'RW', 'F'}
        DEFENSE_POSITIONS = {'D', 'LD', 'RD'}

        def is_forward(p_id):
            pos = player_meta.get(p_id, {}).get("position")
            return pos in FORWARD_POSITIONS

        def is_defenseman(p_id):
            pos = player_meta.get(p_id, {}).get("position")
            return pos in DEFENSE_POSITIONS

        # Fetch shifts
        shifts = Shift.query.filter(Shift.game_id == game_id).all()
        max_time = 3600
        for s in shifts:
            if s.end_elapsed_seconds is not None and s.end_elapsed_seconds > max_time:
                max_time = s.end_elapsed_seconds

        home_players_timeline, away_players_timeline = OnIceService.build_active_players_timeline(
            shifts, max_time, home_team_id
        )

        def get_true_5v5_combinations(t):
            if t < 0 or t >= max_time:
                return None
            h_players = home_players_timeline[t]
            a_players = away_players_timeline[t]

            h_skaters = {p for p in h_players if player_meta.get(p, {}).get("position") != "G"}
            a_skaters = {p for p in a_players if player_meta.get(p, {}).get("position") != "G"}
            h_goalies = [p for p in h_players if player_meta.get(p, {}).get("position") == "G"]
            a_goalies = [p for p in a_players if player_meta.get(p, {}).get("position") == "G"]

            h_fwds = tuple(sorted(p for p in h_skaters if is_forward(p)))
            h_def = tuple(sorted(p for p in h_skaters if is_defenseman(p)))
            a_fwds = tuple(sorted(p for p in a_skaters if is_forward(p)))
            a_def = tuple(sorted(p for p in a_skaters if is_defenseman(p)))

            valid_5v5 = (
                len(h_skaters) == 5
                and len(a_skaters) == 5
                and len(h_fwds) == 3
                and len(h_def) == 2
                and len(a_fwds) == 3
                and len(a_def) == 2
                and len(h_goalies) == 1
                and len(a_goalies) == 1
            )
            if not valid_5v5:
                return None
            return h_fwds, h_def, a_fwds, a_def

        # Compute seconds on ice together
        together_seconds = []
        unit_set = set(player_ids)
        for t in range(max_time):
            combos = get_true_5v5_combinations(t)
            if combos is None:
                continue
            h_fwds, h_def, a_fwds, a_def = combos
            if len(player_ids) == 3:
                if unit_set.issubset(h_fwds) or unit_set.issubset(a_fwds):
                    together_seconds.append(t)
            elif len(player_ids) == 2:
                if unit_set.issubset(h_def) or unit_set.issubset(a_def):
                    together_seconds.append(t)

        together_set = set(together_seconds)
        toi_seconds = len(together_seconds)

        # Formulate shared shift intervals
        intervals = []
        if together_seconds:
            start_sec = together_seconds[0]
            prev_sec = together_seconds[0]
            for sec in together_seconds[1:]:
                if sec == prev_sec + 1:
                    prev_sec = sec
                else:
                    intervals.append((start_sec, prev_sec))
                    start_sec = sec
                    prev_sec = sec
            intervals.append((start_sec, prev_sec))

        formatted_intervals = []
        for start, end in intervals:
            period = start // 1200 + 1
            start_in_period = start % 1200
            end_in_period = (end + 1) % 1200
            if end_in_period == 0 and end > 0:
                end_in_period = 1200
            duration = end + 1 - start
            start_str = f"{start_in_period // 60:02d}:{start_in_period % 60:02d}"
            end_str = f"{end_in_period // 60:02d}:{end_in_period % 60:02d}"
            formatted_intervals.append({
                "period": period,
                "start": start_str,
                "end": end_str,
                "duration": duration,
                "duration_str": f"{duration // 60}:{duration % 60:02d}"
            })

        # Fetch Shots during unit's together time
        shots = Shot.query.join(Event).filter(
            Event.game_id == game_id,
            Event.elapsed_game_seconds.in_(together_seconds),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).options(
            joinedload(Shot.event).joinedload(Event.team),
            joinedload(Shot.shooter),
            joinedload(Shot.goalie)
        ).all()

        cf = ca = ff = fa = sf = sa = gf = ga = 0
        formatted_shots = []

        for s in shots:
            is_for = (s.team_id == unit_team_id)
            
            # Corsi
            if is_for:
                cf += 1
            else:
                ca += 1

            # Fenwick (unblocked)
            if s.outcome != 'Blocked':
                if is_for:
                    ff += 1
                else:
                    fa += 1

            # Shots on goal
            if s.outcome in ['Goal', 'Saved']:
                if is_for:
                    sf += 1
                else:
                    sa += 1

            # Goals
            if s.goal:
                if is_for:
                    gf += 1
                else:
                    ga += 1

            # Format for client-side Plotly map reuse
            formatted_shots.append({
                "shot_id": s.shot_id,
                "raw_x": s.event.x_coordinate,
                "raw_y": s.event.y_coordinate,
                "norm_x": s.x_coordinate,
                "norm_y": s.y_coordinate,
                "distance": s.distance,
                "angle": s.angle,
                "outcome": s.outcome,
                "shot_type": s.shot_type,
                "team_abbrev": s.event.team.abbreviation if s.event.team else "UNK",
                "team_id": s.event.team_id,
                "shooter_name": s.shooter.full_name if s.shooter else "Unknown",
                "shooter_id": s.shooter_id,
                "goalie_name": s.goalie.full_name if s.goalie else "None",
                "period": s.event.period,
                "period_time": s.event.period_time,
                "strength_state": s.strength_state,
                "manpower_state": s.event.manpower_state,
                "empty_net": s.empty_net,
                "xg": round(s.xg, 4) if s.xg is not None else 0.0
            })

        cf_pct = round((cf / (cf + ca) * 100), 1) if (cf + ca) > 0 else 50.0
        ff_pct = round((ff / (ff + fa) * 100), 1) if (ff + fa) > 0 else 50.0

        # Fetch play-by-play events during together time
        events = Event.query.filter(
            Event.game_id == game_id,
            Event.elapsed_game_seconds.in_(together_seconds)
        ).order_by(Event.period.asc(), Event.elapsed_game_seconds.asc()).all()

        timeline = []
        home_team_abbr = game.home_team.abbreviation
        away_team_abbr = game.away_team.abbreviation
        
        for event in events:
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
                desc = f"Goal scored by {scorer} ({event.strength_state})"
            elif event.event_type == 'shot-on-goal':
                shooter = event.primary_player.full_name if event.primary_player else "Unknown"
                desc = f"Shot on goal by {shooter} (saved)"
            elif event.event_type == 'missed-shot':
                shooter = event.primary_player.full_name if event.primary_player else "Unknown"
                desc = f"Shot by {shooter} missed net"
            elif event.event_type == 'blocked-shot':
                shooter = event.primary_player.full_name if event.primary_player else "Unknown"
                blocker = event.secondary_player.full_name if event.secondary_player else "Unknown"
                desc = f"Shot by {shooter} blocked by {blocker}"
            elif event.event_type == 'hit':
                hitter = event.primary_player.full_name if event.primary_player else "Unknown"
                hittee = event.secondary_player.full_name if event.secondary_player else "Unknown"
                desc = f"Hit delivered by {hitter} on {hittee}"
            elif event.event_type == 'penalty':
                infraction = event.penalty_description or "Unknown infraction"
                dur = event.penalty_duration or 2
                committer = event.primary_player.full_name if event.primary_player else "Unknown"
                desc = f"Penalty to {committer} ({dur} min for {infraction})"
            elif event.event_type == 'faceoff':
                winner = event.primary_player.full_name if event.primary_player else "Unknown"
                loser = event.secondary_player.full_name if event.secondary_player else "Unknown"
                desc = f"Faceoff won by {winner} against {loser}"
                
            event_data["description"] = desc
            timeline.append(event_data)

        # Build players list details
        player_details = []
        for p_id in player_ids:
            p = players_map.get(p_id)
            r = roster_map.get(p_id)
            player_details.append({
                "player_id": p_id,
                "name": p.full_name if p else f"Player {p_id}",
                "number": r.sweater_number if r else (p.sweater_number if p else None),
                "position": r.position if r else (p.position if p else "skater"),
                "shoots_catches": p.shoots_catches if p else None,
                "headshot_url": p.headshot_url if p else None
            })

        mins = toi_seconds // 60
        secs = toi_seconds % 60
        toi_str = f"{mins:02d}:{secs:02d}"

        return {
            "game_id": game_id,
            "toi_seconds": toi_seconds,
            "toi": toi_str,
            "team": {
                "id": unit_team_id,
                "name": unit_team.name if unit_team else "Unknown Team",
                "abbrev": unit_team.abbreviation if unit_team else "UNK"
            },
            "opponent": {
                "name": opponent_team.name if opponent_team else "Unknown Opponent",
                "abbrev": opponent_team.abbreviation if opponent_team else "UNK"
            },
            "players": player_details,
            "intervals": formatted_intervals,
            "stats": {
                "gf": gf,
                "ga": ga,
                "sf": sf,
                "sa": sa,
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "ff": ff,
                "fa": fa,
                "ff_pct": ff_pct
            },
            "shots": formatted_shots,
            "timeline": timeline
        }