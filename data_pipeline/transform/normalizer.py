import math
import logging
from datetime import datetime
from app.models import Team, Player, Game, Event, Shot, Shift

logger = logging.getLogger(__name__)

def parse_time_to_seconds(time_str: str) -> int:
    """Converts a time string in MM:SS format to seconds."""
    if not time_str or ':' not in time_str:
        return 0
    try:
        parts = time_str.split(':')
        minutes = int(parts[0])
        seconds = int(parts[1])
        return minutes * 60 + seconds
    except (ValueError, IndexError):
        return 0

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

def parse_situation_code(situation_code: str, is_home_team: bool) -> tuple:
    """
    Parses a 4-digit situationCode to determine strength state and empty net status.
    Format: [Away Goalie Status, Away Skaters, Home Skaters, Home Goalie Status]
    
    Returns:
        strength_state (str): e.g. '5v5', '5v4', '4v5'
        empty_net (bool): True if the defending goalie is pulled.
    """
    if not situation_code or len(situation_code) != 4:
        return "5v5", False
        
    try:
        away_goalie = int(situation_code[0])
        away_skaters = int(situation_code[1])
        home_skaters = int(situation_code[2])
        home_goalie = int(situation_code[3])
        
        # Strength state is typically HomeSkatersvAwaySkaters
        strength_state = f"{home_skaters}v{away_skaters}"
        
        # Empty net is relative to the defending team (the opponent of the attacking team)
        if is_home_team:
            # Home attacks Away. Defending goalie is Away goalie.
            empty_net = (away_goalie == 0)
        else:
            # Away attacks Home. Defending goalie is Home goalie.
            empty_net = (home_goalie == 0)
            
        return strength_state, empty_net
    except ValueError:
        return "5v5", False

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
        
        period = play["periodDescriptor"]["number"]
        period_time = play["timeInPeriod"]
        seconds_in_period = parse_time_to_seconds(period_time)
        elapsed_game_seconds = (period - 1) * 1200 + seconds_in_period
        
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
            strength_state=strength_state
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
            
            shot = Shot(
                shot_id=event_id,
                shooter_id=primary_player_id,
                goalie_id=secondary_player_id if event_type in ['shot-on-goal', 'goal', 'missed-shot'] else None,
                shot_type=details.get("shotType"),
                x_coordinate=norm_x,
                y_coordinate=norm_y,
                distance=metrics["distance"],
                angle=metrics["angle"],
                outcome=outcome,
                goal=is_goal,
                strength_state=strength_state,
                empty_net=empty_net
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
        
        start_elapsed_seconds = (period - 1) * 1200 + start_in_period
        end_elapsed_seconds = (period - 1) * 1200 + end_in_period
        
        player_id = shift_raw["playerId"]
        shift_id = f"{game_id}_{player_id}_{period}_{start_elapsed_seconds}"
        
        return Shift(
            shift_id=shift_id,
            game_id=game_id,
            player_id=player_id,
            period=period,
            start_time=start_time,
            end_time=end_time,
            start_elapsed_seconds=start_elapsed_seconds,
            end_elapsed_seconds=end_elapsed_seconds,
            duration=duration
        )
