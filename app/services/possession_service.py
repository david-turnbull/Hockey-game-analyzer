from sqlalchemy import or_
from app.models import db, Shift, Event, Game, Player
from app.services.on_ice_service import OnIceService
from data_pipeline.transform.normalizer import parse_situation_code_raw

class PossessionService:
    """Service for calculating possession metrics (Corsi and Fenwick) under various strength states."""

    @staticmethod
    def matches_strength(event: Event, mode: str, home_team_id: int) -> bool:
        """
        Determines if an event matches a specific strength/manpower mode.
        """
        # Shootouts are always excluded from possession calculations
        if event.period_type == 'SO':
            return False

        # Parse situation code
        situation = parse_situation_code_raw(event.raw_situation_code)
        home_skaters = event.home_skaters if event.home_skaters is not None else situation.get("home_skaters")
        away_skaters = event.away_skaters if event.away_skaters is not None else situation.get("away_skaters")
        home_goalie = situation.get("home_goalie")
        away_goalie = situation.get("away_goalie")

        # Fallbacks to database event classifications if situation code parsed values are missing
        if home_skaters is None or away_skaters is None:
            # If situation code is completely missing or failed to parse, use DB manpower state
            if mode == "5v5":
                return event.manpower_state == "EV" and event.team_strength_state == "5v5"
            elif mode in ["EV", "All Even Strength"]:
                return event.manpower_state == "EV"
            elif mode in ["PP", "Power Play"]:
                return event.manpower_state == "PP"
            elif mode in ["PK", "Penalty Kill"]:
                return event.manpower_state == "PK"
            elif mode in ["All", "All Situations"]:
                return True
            return False

        is_home_event_owner = (event.team_id == home_team_id)

        if mode == "5v5":
            # True 5v5: Exactly 5 skaters on both sides, and both goalies in net
            return (home_skaters == 5 and 
                    away_skaters == 5 and 
                    home_goalie == 1 and 
                    away_goalie == 1)

        elif mode in ["EV", "All Even Strength"]:
            # Even strength: equal skaters (e.g. 5v5, 4v4, 3v3)
            return home_skaters == away_skaters

        elif mode in ["PP", "Power Play"]:
            # Power play: the attacking team has more skaters than the defending team
            if is_home_event_owner:
                return home_skaters > away_skaters
            else:
                return away_skaters > home_skaters

        elif mode in ["PK", "Penalty Kill"]:
            # Penalty kill: the attacking team has fewer skaters than the defending team
            if is_home_event_owner:
                return home_skaters < away_skaters
            else:
                return away_skaters < home_skaters

        elif mode in ["All", "All Situations"]:
            return True

        return False

    @staticmethod
    def calculate_possession_stats(game_id: int, mode: str = "5v5") -> dict:
        """
        Calculates Corsi and Fenwick statistics (CF, CA, CF%, FF, FA, FF%)
        for all active skaters in a game under a specific strength mode.
        """
        # Fetch game details
        game = db.session.get(Game, game_id)
        if not game:
            return {}

        home_team_id = game.home_team_id

        # 1. Fetch all shifts for the game (excluding anomalies, duration must be > 0)
        shifts = Shift.query.filter(
            Shift.game_id == game_id,
            Shift.is_anomaly == False,
            Shift.duration > 0,
            Shift.start_elapsed_seconds.isnot(None),
            Shift.end_elapsed_seconds.isnot(None)
        ).all()

        # 2. Fetch all shot events (excluding shootout period type)
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events = Event.query.filter(
            Event.game_id == game_id,
            Event.event_type.in_(shot_event_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None)),
            Event.elapsed_game_seconds.isnot(None)
        ).all()

        # Build player rosters metadata mapping
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

        # Calculate Corsi & Fenwick for each matching event
        for event in events:
            # Check if this event matches the selected strength mode
            if not PossessionService.matches_strength(event, mode, home_team_id):
                continue

            shot_team_id = event.team_id
            is_blocked = (event.event_type == 'blocked-shot')

            # Get active shifts at this event time using OnIceService
            active_shifts = OnIceService.filter_active_shifts(shifts, event.elapsed_game_seconds)

            # Extract active skater IDs
            on_ice_player_ids = [
                s.player_id for s in active_shifts
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

        # Calculate percentages
        player_percentages = {}
        for p_id, stats in player_possession.items():
            cf = stats["cf"]
            ca = stats["ca"]
            ff = stats["ff"]
            fa = stats["fa"]

            cf_pct = round((cf / (cf + ca) * 100), 1) if (cf + ca) > 0 else None
            ff_pct = round((ff / (ff + fa) * 100), 1) if (ff + fa) > 0 else None

            player_percentages[p_id] = {
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "ff": ff,
                "fa": fa,
                "ff_pct": ff_pct
            }
        return player_percentages
