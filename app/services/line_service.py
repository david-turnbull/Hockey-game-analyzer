from sqlalchemy import or_
from app.models import db, Game, Shift, Event, GamePlayer

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
        is_forward = lambda p_id: player_meta.get(p_id, {}).get("position") in ['C', 'LW', 'RW', 'F']
        is_defenseman = lambda p_id: player_meta.get(p_id, {}).get("position") in ['D', 'LD', 'RD']

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
        from app.services.on_ice_service import OnIceService
        home_players_timeline, away_players_timeline = OnIceService.build_active_players_timeline(
            shifts, max_time, home_team_id
        )

        home_skaters_on_ice = []
        for players in home_players_timeline:
            home_skaters_on_ice.append({p for p in players if player_meta.get(p, {}).get("position") != 'G'})

        away_skaters_on_ice = []
        for players in away_players_timeline:
            away_skaters_on_ice.append({p for p in players if player_meta.get(p, {}).get("position") != 'G'})

        # 5. Initialize aggregation dictionaries
        home_lines = {}  # tuple -> seconds
        home_pairings = {}
        away_lines = {}
        away_pairings = {}

        # Accumulate TOI second-by-second
        for t in range(0, max_time):
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
