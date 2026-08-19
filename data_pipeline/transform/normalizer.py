import math
import logging
from datetime import datetime
from app.models import Team, Player, Game, Event, Shot, Shift, GamePlayer

logger = logging.getLogger(__name__)

def parse_time_to_seconds(time_str: str) -> int:
    """Converts a time string in MM:SS format to seconds. Returns None if invalid."""
    if not time_str or not isinstance(time_str, str) or ':' not in time_str:
        return None
    try:
        parts = time_str.split(':')
        if len(parts) != 2:
            return None
        minutes = int(parts[0])
        seconds = int(parts[1])
        if minutes < 0 or seconds < 0 or seconds >= 60:
            return None
        return minutes * 60 + seconds
    except (ValueError, IndexError):
        return None

def normalize_coordinates(x: float, y: float, period: int, home_defending_side: str, is_home_team: bool) -> tuple:
    """
    Normalizes coordinates so that the attacking direction is always from left to right.
    The target net is positioned at (89, 0).
    
    Arguments:
        x: Raw X coordinate.
        y: Raw Y coordinate.
        period: Period number.
        home_defending_side: Side defended by home team ('left' or 'right').
        is_home_team: True if the attacking team is the Home team, False if Away.
    """
    if x is None or y is None:
        return None, None
        
    if not home_defending_side:
        # Default fallback: do not modify
        return x, y
        
    home_defending_side = home_defending_side.lower()
    
    # We want coordinates to face right (attacking net at x = +89)
    # Let's determine if the attacking team is attacking the left side (x < 0).
    # If they are attacking the left side, we flip their coordinates.
    flip = False
    
    if home_defending_side == 'left':
        # Home defends left (x < 0), attacks right (x > 0). No flip for Home.
        # Away defends right (x > 0), attacks left (x < 0). Flip for Away.
        if not is_home_team:
            flip = True
    elif home_defending_side == 'right':
        # Home defends right (x > 0), attacks left (x < 0). Flip for Home.
        # Away defends left (x < 0), attacks right (x > 0). No flip for Away.
        if is_home_team:
            flip = True
            
    if flip:
        return -x, -y
    return x, y

def calculate_shot_metrics(normalized_x: float, normalized_y: float) -> dict:
    """
    Calculates shot distance and angle relative to the center of the net at (89, 0).
    """
    if normalized_x is None or normalized_y is None:
        return {"distance": None, "angle": None}
        
    # Net is at (89, 0)
    dx = 89.0 - normalized_x
    dy = normalized_y
    
    distance = math.sqrt(dx**2 + dy**2)
    
    # Calculate angle in degrees
    # If shooter is directly in front (dy=0), angle is 0.
    # If shooter is on the goal line (dx=0), angle is 90.
    angle = math.degrees(math.atan2(abs(dy), dx))
    
    return {
        "distance": round(distance, 2),
        "angle": round(angle, 2)
    }

def parse_situation_code_raw(situation_code: str) -> dict:
    """
    Parses a 4-digit situationCode.
    Format: [Away Goalie Status, Away Skaters, Home Skaters, Home Goalie Status]
    Returns a dict with raw integer values, or None values if parsing fails.
    """
    if not situation_code or len(situation_code) != 4 or not situation_code.isdigit():
        return {
            "away_goalie": None,
            "away_skaters": None,
            "home_skaters": None,
            "home_goalie": None
        }
    
    return {
        "away_goalie": int(situation_code[0]),
        "away_skaters": int(situation_code[1]),
        "home_skaters": int(situation_code[2]),
        "home_goalie": int(situation_code[3])
    }

def derive_event_manpower(period_type: str, raw_situation: dict, is_home_team: bool) -> tuple:
    """
    Derives team_strength_state and manpower_state from the event team's perspective.
    
    Returns:
        team_strength_state (str): e.g. '5v4', '4v5', '1v0', '5v5'
        manpower_state (str): 'EV', 'PP', 'PK', 'EMPTY_NET_FOR', 'EMPTY_NET_AGAINST', 'SO', 'UNKNOWN'
    """
    if period_type == 'SO':
        return '1v0', 'SO'
        
    away_goalie = raw_situation.get("away_goalie")
    away_skaters = raw_situation.get("away_skaters")
    home_skaters = raw_situation.get("home_skaters")
    home_goalie = raw_situation.get("home_goalie")
    
    if (away_goalie is None or away_skaters is None or 
        home_skaters is None or home_goalie is None):
        return '5v5', 'UNKNOWN'
        
    # Determine skaters for attacking and defending teams
    if is_home_team:
        # Home team is attacking
        atk_skaters = home_skaters
        atk_goalie = home_goalie
        def_skaters = away_skaters
        def_goalie = away_goalie
    else:
        # Away team is attacking
        atk_skaters = away_skaters
        atk_goalie = away_goalie
        def_skaters = home_skaters
        def_goalie = home_goalie
        
    # Derive team-strength state from the event team's perspective
    team_strength_state = f"{atk_skaters}v{def_skaters}"
    
    # Classify manpower state
    if def_goalie == 0:
        manpower_state = 'EMPTY_NET_AGAINST'
    elif atk_goalie == 0:
        manpower_state = 'EMPTY_NET_FOR'
    else:
        if atk_skaters > def_skaters:
            manpower_state = 'PP'
        elif atk_skaters < def_skaters:
            manpower_state = 'PK'
        else:
            manpower_state = 'EV'
            
    return team_strength_state, manpower_state

def parse_situation_code(situation_code: str, is_home_team: bool) -> tuple:
    """
    Backwards compatible parser for situationCode.
    Returns:
        strength_state (str): HomeSkatersvAwaySkaters (always Home vs Away)
        empty_net (bool): True if defending goalie is pulled.
    """
    raw = parse_situation_code_raw(situation_code)
    if raw["away_goalie"] is None:
        return "5v5", False
    
    strength_state = f"{raw['home_skaters']}v{raw['away_skaters']}"
    if is_home_team:
        empty_net = (raw["away_goalie"] == 0)
    else:
        empty_net = (raw["home_goalie"] == 0)
        
    return strength_state, empty_net

class DataNormalizer:
    """Orchestrates transformation of raw JSON API data to database model collections."""
    
    def __init__(self):
        # A simple registry mapping team abbrev to team full name as fallback
        self.team_names_fallback = {
            'CGY': 'Calgary Flames',
            'WPG': 'Winnipeg Jets',
            'EDM': 'Edmonton Oilers',
            'VAN': 'Vancouver Canucks',
            'TOR': 'Toronto Maple Leafs',
            'MTL': 'Montréal Canadiens',
            'OTT': 'Ottawa Senators',
        }

    def transform_team(self, team_id: int, team_abbrev: str, team_name: str = None) -> Team:
        """Constructs a Team model instance."""
        if not team_name:
            team_name = self.team_names_fallback.get(team_abbrev, f"{team_abbrev} Team")
        return Team(team_id=team_id, abbreviation=team_abbrev, name=team_name)

    def transform_player(self, spot: dict) -> Player:
        """Constructs a Player model instance from a roster spot record."""
        return Player(
            player_id=spot["playerId"],
            first_name=spot.get("firstName", {}).get("default", ""),
            last_name=spot.get("lastName", {}).get("default", ""),
            position=spot.get("positionCode"),
            shoots_catches=spot.get("shootsCatches"),
            current_team_id=spot.get("teamId")
        )

    def transform_game(self, pbp_raw: dict) -> Game:
        """Constructs a Game model instance."""
        game_id = pbp_raw["id"]
        season = str(pbp_raw["season"])
        game_date = datetime.strptime(pbp_raw["gameDate"], "%Y-%m-%d").date()
        
        raw_type = pbp_raw.get("gameType")
        game_type = 'R' if raw_type == 2 else ('P' if raw_type == 3 else str(raw_type))
        
        home_team_id = pbp_raw["homeTeam"]["id"]
        away_team_id = pbp_raw["awayTeam"]["id"]
        home_score = pbp_raw["homeTeam"].get("score", 0)
        away_score = pbp_raw["awayTeam"].get("score", 0)
        game_status = pbp_raw.get("gameState")
        
        return Game(
            game_id=game_id,
            season=season,
            game_date=game_date,
            game_type=game_type,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            game_status=game_status
        )

    def transform_event(self, play: dict, game_id: int, home_team_id: int) -> tuple:
        """
        Transforms a play dict into an Event model, and if it's a shot attempt,
        also constructs a Shot model.
        """
        event_idx = play.get("eventId")
        event_id = f"{game_id}_{event_idx}"
        
        period_desc = play.get("periodDescriptor", {})
        period = period_desc.get("number", 1)
        period_type = period_desc.get("periodType")
        if not period_type:
            if period <= 3:
                period_type = "REG"
            elif period == 4:
                period_type = "OT"
            else:
                period_type = "SO"
                
        period_time = play["timeInPeriod"]
        seconds_in_period = parse_time_to_seconds(period_time)
        if seconds_in_period is not None:
            elapsed_game_seconds = (period - 1) * 1200 + seconds_in_period
        else:
            elapsed_game_seconds = None
        
        event_type = play["typeDescKey"]
        
        details = play.get("details", {})
        team_id = details.get("eventOwnerTeamId")
        is_home_team = (team_id == home_team_id)
        
        # Identify primary, secondary, assist, and penalty details
        primary_player_id = None
        secondary_player_id = None
        assist1_player_id = None
        assist2_player_id = None
        penalty_duration = None
        penalty_description = None
        
        if event_type in ['shot-on-goal', 'missed-shot', 'blocked-shot']:
            primary_player_id = details.get("shootingPlayerId")
            secondary_player_id = details.get("goalieInNetId")
        elif event_type == 'goal':
            primary_player_id = details.get("scoringPlayerId")
            secondary_player_id = details.get("goalieInNetId")
            assist1_player_id = details.get("assist1PlayerId")
            assist2_player_id = details.get("assist2PlayerId")
        elif event_type == 'hit':
            primary_player_id = details.get("hittingPlayerId")
            secondary_player_id = details.get("hitteePlayerId")
        elif event_type == 'penalty':
            primary_player_id = details.get("committedByPlayerId")
            secondary_player_id = details.get("drawnByPlayerId")
            penalty_duration = details.get("duration")
            
            raw_desc = details.get("descKey", "")
            if raw_desc:
                penalty_description = raw_desc.replace('-', ' ').title()
        elif event_type == 'faceoff':
            primary_player_id = details.get("winningPlayerId")
            secondary_player_id = details.get("losingPlayerId")
            
        raw_x = details.get("xCoord")
        raw_y = details.get("yCoord")
        
        home_defending_side = play.get("homeTeamDefendingSide", "")
        
        # Normalize coordinates
        norm_x, norm_y = normalize_coordinates(
            raw_x, raw_y, period, home_defending_side, is_home_team
        )
        
        situation_code = play.get("situationCode")
        raw_situation = parse_situation_code_raw(situation_code)
        
        # Calculate team-relative strength state and manpower state
        team_strength_state, manpower_state = derive_event_manpower(period_type, raw_situation, is_home_team)
        
        # Calculate backward compatible strength_state
        strength_state, empty_net = parse_situation_code(situation_code, is_home_team)
        
        event = Event(
            event_id=event_id,
            game_id=game_id,
            period=period,
            period_time=period_time,
            elapsed_game_seconds=elapsed_game_seconds,
            event_type=event_type,
            team_id=team_id,
            primary_player_id=primary_player_id,
            secondary_player_id=secondary_player_id,
            assist1_player_id=assist1_player_id,
            assist2_player_id=assist2_player_id,
            penalty_duration=penalty_duration,
            penalty_description=penalty_description,
            x_coordinate=raw_x,
            y_coordinate=raw_y,
            strength_state=strength_state,
            period_type=period_type,
            raw_situation_code=situation_code,
            home_skaters=raw_situation.get("home_skaters"),
            away_skaters=raw_situation.get("away_skaters"),
            team_strength_state=team_strength_state,
            manpower_state=manpower_state
        )
        
        shot = None
        # Let's map shot types
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        if event_type in shot_event_types and norm_x is not None and norm_y is not None:
            metrics = calculate_shot_metrics(norm_x, norm_y)
            
            # Map outcome description
            outcome_mapping = {
                'goal': 'Goal',
                'shot-on-goal': 'Saved',
                'missed-shot': 'Missed',
                'blocked-shot': 'Blocked'
            }
            outcome = outcome_mapping.get(event_type, 'Unknown')
            is_goal = (event_type == 'goal')
            
            from app.services.xg_service import XGService
            xg_val = XGService.calculate_shot_xg(
                metrics["distance"],
                metrics["angle"],
                details.get("shotType"),
                team_strength_state,
                empty_net
            )
            
            shot = Shot(
                shot_id=event_id,
                game_id=game_id,
                team_id=team_id,
                shooter_id=primary_player_id,
                goalie_id=secondary_player_id if event_type in ['shot-on-goal', 'goal', 'missed-shot'] else None,
                shot_type=details.get("shotType"),
                x_coordinate=norm_x,
                y_coordinate=norm_y,
                distance=metrics["distance"],
                angle=metrics["angle"],
                outcome=outcome,
                goal=is_goal,
                strength_state=team_strength_state,
                empty_net=empty_net,
                xg=xg_val
            )
            
        return event, shot

    def transform_shift(self, shift_raw: dict, game_id: int) -> Shift:
        """Constructs a Shift model instance from raw shift record."""
        # Clean data durations
        raw_dur = shift_raw.get("duration")
        duration = parse_time_to_seconds(raw_dur)
        
        period = shift_raw["period"]
        start_time = shift_raw["startTime"]
        end_time = shift_raw["endTime"]
        
        start_in_period = parse_time_to_seconds(start_time)
        end_in_period = parse_time_to_seconds(end_time)
        
        if start_in_period is not None:
            start_elapsed_seconds = (period - 1) * 1200 + start_in_period
        else:
            start_elapsed_seconds = None
            
        if end_in_period is not None:
            end_elapsed_seconds = (period - 1) * 1200 + end_in_period
        else:
            end_elapsed_seconds = None
            
        player_id = shift_raw["playerId"]
        start_seconds_id = start_elapsed_seconds if start_elapsed_seconds is not None else "invalid"
        shift_id = f"{game_id}_{player_id}_{period}_{start_seconds_id}"
        
        period_type = "REG" if period <= 3 else "OT"
        team_id = shift_raw.get("teamId")
        
        return Shift(
            shift_id=shift_id,
            game_id=game_id,
            player_id=player_id,
            period=period,
            start_time=start_time,
            end_time=end_time,
            start_elapsed_seconds=start_elapsed_seconds,
            end_elapsed_seconds=end_elapsed_seconds,
            duration=duration,
            period_type=period_type,
            team_id=team_id
        )

    def transform_game_player(self, game_id: int, player_id: int, team_id: int, position: str = None) -> GamePlayer:
        """Constructs a GamePlayer model instance representing a player's roster assignment for a game."""
        return GamePlayer(
            game_id=game_id,
            player_id=player_id,
            team_id=team_id,
            position=position
        )
