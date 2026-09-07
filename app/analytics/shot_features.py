import math
import logging
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

NET_X = 89.0
NET_Y = 0.0

VALID_SHOT_TYPES = [
    'wrist', 'slap', 'snap', 'backhand', 'tip-in', 'deflected', 'wrap-around', 'other', 'UNKNOWN'
]

FEATURE_COLUMNS = [
    'distance',
    'angle',
    'shot_type',
    'period',
    'period_seconds',
    'strength_state',
    'score_differential',
    'is_home',
    'empty_net',
    'prev_event_type',
    'time_since_prev_event',
    'distance_from_prev_event',
    'angle_change',
    'is_rebound',
    'is_rush',
    'is_turnover',
    'is_after_faceoff',
    'is_lateral_movement',
    'is_power_play',
    'is_shorthanded',
    'coordinates_missing'
]

NUMERIC_FEATURES = [
    'distance',
    'angle',
    'period',
    'period_seconds',
    'score_differential',
    'is_home',
    'empty_net',
    'time_since_prev_event',
    'distance_from_prev_event',
    'angle_change',
    'is_rebound',
    'is_rush',
    'is_turnover',
    'is_after_faceoff',
    'is_lateral_movement',
    'is_power_play',
    'is_shorthanded',
    'coordinates_missing'
]

CATEGORICAL_FEATURES = [
    'shot_type',
    'strength_state',
    'prev_event_type'
]


def parse_clock_to_seconds(clock_str: Optional[str]) -> int:
    """Parses 'MM:SS' time string to elapsed period seconds."""
    if not clock_str or not isinstance(clock_str, str) or ':' not in clock_str:
        return 0
    try:
        parts = clock_str.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def get_attacking_coordinate_transform(shot_raw_x: Optional[float], shot_raw_y: Optional[float],
                                       home_defending_side: Optional[str] = None,
                                       is_home_team: bool = True) -> bool:
    """
    Determines whether coordinates should be flipped (-x, -y) to orient the attacking net at (+89, 0).
    Returns True if coordinates should be flipped, False otherwise.
    """
    if home_defending_side:
        side = str(home_defending_side).strip().lower()
        if is_home_team:
            # Home defends left (negative x) -> home attacks right (positive x). No flip needed.
            # Home defends right (positive x) -> home attacks left (negative x). Flip needed.
            return side == 'right'
        else:
            # Away team defends opposite side.
            # If home defends left, away defends right and attacks left. Flip needed.
            # If home defends right, away defends left and attacks right. No flip needed.
            return side == 'left'

    # Fallback when defending side not provided:
    # Attacking shots are directed toward the opposing net.
    # If shot_raw_x < 0, the attacking team is shooting towards the negative-x net, so coordinates must be flipped.
    if shot_raw_x is not None and shot_raw_x < 0:
        return True
    return False


def apply_coordinate_transform(x: Optional[float], y: Optional[float], should_flip: bool) -> Tuple[Optional[float], Optional[float]]:
    """Applies coordinate flip transform if should_flip is True."""
    if x is None or y is None:
        return None, None
    if should_flip:
        return -x, -y
    return x, y


def normalize_coordinates(x: Optional[float], y: Optional[float], 
                          home_defending_side: Optional[str] = None, 
                          is_home_team: bool = True) -> Tuple[Optional[float], Optional[float]]:
    """
    Normalizes coordinates so that attacking direction is consistently towards the net at (89, 0).
    Uses get_attacking_coordinate_transform and apply_coordinate_transform.
    """
    if x is None or y is None:
        return None, None
    should_flip = get_attacking_coordinate_transform(x, y, home_defending_side=home_defending_side, is_home_team=is_home_team)
    return apply_coordinate_transform(x, y, should_flip)


def calculate_distance_and_angle(x_norm: Optional[float], y_norm: Optional[float]) -> Tuple[float, float]:
    """
    Calculates Euclidean distance and absolute angle (in degrees) to net center (89, 0).
    Directly centered shots have angle = 0.
    Goal line shots have angle = 90.
    Behind the net shots have angle > 90.
    """
    if x_norm is None or y_norm is None:
        return 45.0, 0.0

    dx = NET_X - x_norm
    dy = y_norm - NET_Y

    distance = math.sqrt(dx**2 + dy**2)
    # Angle relative to line of sight directly in front of the goal
    angle = math.degrees(math.atan2(abs(dy), dx))

    return round(distance, 2), round(angle, 2)


def standardize_shot_type(raw_type: Optional[str]) -> str:
    """Standardizes NHL API shot type strings into consistent categories."""
    if not raw_type:
        return 'UNKNOWN'
    t = str(raw_type).strip().lower()
    if not t or t in ['unknown', 'none', 'null', 'nan']:
        return 'UNKNOWN'
    if 'wrist' in t:
        return 'wrist'
    elif 'slap' in t:
        return 'slap'
    elif 'snap' in t:
        return 'snap'
    elif 'backhand' in t:
        return 'backhand'
    elif 'tip' in t or 'deflect' in t:
        return 'tip-in'
    elif 'wrap' in t:
        return 'wrap-around'
    return 'other'


def standardize_strength_state(state: Optional[str]) -> str:
    """Standardizes strength state strings into 'EV', 'PP', 'SH', or 'UNKNOWN'."""
    if not state:
        return 'UNKNOWN'
    s = str(state).strip().upper()
    if not s or s in ['UNKNOWN', 'NONE', 'NULL', 'NAN']:
        return 'UNKNOWN'
    if s in ['5V5', 'EVEN', 'EV', '4V4', '3V3']:
        return 'EV'
    elif 'PP' in s or '5V4' in s or '5V3' in s or '4V3' in s:
        return 'PP'
    elif 'SH' in s or '4V5' in s or '3V5' in s or '3V4' in s or 'PK' in s:
        return 'SH'
    return 'UNKNOWN'


class ShotFeatureExtractor:
    """
    Extracts and standardizes features for individual shots and raw play-by-play events.
    Guarantees no data leakage and ensures consistent feature representation between training and inference.
    """

    @classmethod
    def extract_features_from_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a normalized feature dictionary from input values, suitable for model input.
        Missing values are assigned clean, defensible defaults with explicit missingness indicators.
        """
        raw_x = data.get('x_coordinate') if data.get('x_coordinate') is not None else data.get('x_coordinate_normalized')
        raw_y = data.get('y_coordinate') if data.get('y_coordinate') is not None else data.get('y_coordinate_normalized')
        
        distance = data.get('distance')
        angle = data.get('angle')
        coordinates_missing = 1 if data.get('coordinates_missing') else 0

        if distance is None or angle is None:
            if raw_x is None or raw_y is None:
                coordinates_missing = 1
                distance = 45.0  # Controlled neutral imputation
                angle = 0.0
            else:
                norm_x, norm_y = normalize_coordinates(
                    raw_x, raw_y,
                    home_defending_side=data.get('home_defending_side'),
                    is_home_team=bool(data.get('is_home', True))
                )
                calc_dist, calc_ang = calculate_distance_and_angle(norm_x, norm_y)
                distance = calc_dist
                angle = calc_ang
        else:
            if raw_x is None and raw_y is None and data.get('coordinates_missing'):
                coordinates_missing = 1

        shot_type = standardize_shot_type(data.get('shot_type'))
        strength = standardize_strength_state(data.get('strength_state'))
        empty_net = 1 if data.get('empty_net') else 0
        is_home = 1 if data.get('is_home') else 0

        period = int(data.get('period', 1))
        period_seconds = int(data.get('period_seconds', 0))
        score_diff = int(data.get('score_differential', 0))

        prev_type = str(data.get('prev_event_type', 'none')).lower()
        delta_t = max(0.0, float(data.get('time_since_prev_event', 10.0)))
        delta_d = max(0.0, float(data.get('distance_from_prev_event', 0.0)))
        angle_change = max(0.0, float(data.get('angle_change', 0.0)))

        is_rebound = 1 if data.get('is_rebound') or (
            delta_t <= 3.0 and prev_type in ['shot-on-goal', 'saved', 'missed-shot', 'blocked-shot', 'shot']
        ) else 0

        is_rush = 1 if data.get('is_rush') or (
            delta_t <= 4.0 and delta_d >= 40.0
        ) else 0

        is_turnover = 1 if data.get('is_turnover') or (
            delta_t <= 4.0 and prev_type in ['giveaway', 'takeaway']
        ) else 0

        is_faceoff = 1 if data.get('is_after_faceoff') or (
            delta_t <= 4.0 and prev_type == 'faceoff'
        ) else 0

        is_lateral = 1 if data.get('is_lateral_movement') or (
            delta_t <= 3.0 and (angle_change >= 25.0 or delta_d >= 15.0)
        ) else 0

        is_pp = 1 if strength == 'PP' else 0
        is_sh = 1 if strength == 'SH' else 0

        return {
            'distance': float(distance),
            'angle': float(angle),
            'shot_type': shot_type,
            'period': period,
            'period_seconds': period_seconds,
            'strength_state': strength,
            'score_differential': score_diff,
            'is_home': is_home,
            'empty_net': empty_net,
            'prev_event_type': prev_type,
            'time_since_prev_event': delta_t,
            'distance_from_prev_event': delta_d,
            'angle_change': angle_change,
            'is_rebound': is_rebound,
            'is_rush': is_rush,
            'is_turnover': is_turnover,
            'is_after_faceoff': is_faceoff,
            'is_lateral_movement': is_lateral,
            'is_power_play': is_pp,
            'is_shorthanded': is_sh,
            'coordinates_missing': coordinates_missing
        }

    @classmethod
    def extract_shots_from_pbp_json(cls, pbp_data: Dict[str, Any], unblocked_only: bool = True) -> List[Dict[str, Any]]:
        """
        Extracts all shot attempt records and their engineered features chronologically from raw NHL play-by-play JSON.
        Maintains prior-event context dynamically without look-ahead bias.
        """
        game_id = pbp_data.get('id')
        season = str(pbp_data.get('season', ''))
        game_date = pbp_data.get('gameDate', '')
        home_team_id = pbp_data.get('homeTeam', {}).get('id')
        away_team_id = pbp_data.get('awayTeam', {}).get('id')

        raw_plays = pbp_data.get('plays', [])
        shots = []
        seen_event_ids = set()

        # Track previous event details within each period
        current_period = 0
        prev_event: Optional[Dict[str, Any]] = None
        home_score = 0
        away_score = 0

        target_event_types = {'shot-on-goal', 'goal', 'missed-shot'}
        if not unblocked_only:
            target_event_types.add('blocked-shot')

        for play in raw_plays:
            period = play.get('periodDescriptor', {}).get('number', 1)
            period_type = play.get('periodDescriptor', {}).get('periodType', 'REG')
            # Shootout shots are excluded from regular xG models
            if period_type == 'SO':
                continue

            # Reset previous event when entering new period
            if period != current_period:
                current_period = period
                prev_event = None

            type_desc = play.get('typeDescKey', '').lower()
            time_str = play.get('timeInPeriod', '00:00')
            period_seconds = parse_clock_to_seconds(time_str)

            raw_x = play.get('details', {}).get('xCoord')
            raw_y = play.get('details', {}).get('yCoord')

            event_owner_team_id = play.get('details', {}).get('eventOwnerTeamId')
            is_home_event = (event_owner_team_id == home_team_id)

            # Check if this play is a shot attempt
            if type_desc in target_event_types:
                raw_event_id = play.get("eventId")
                if raw_event_id is None:
                    logger.warning(
                        "Skipping xG feature extraction for game %s: eligible shot missing eventId",
                        game_id,
                    )
                elif raw_event_id in seen_event_ids:
                    logger.warning(
                        "Duplicate eventId %s detected in game %s; excluding duplicate feature record",
                        raw_event_id,
                        game_id,
                    )
                else:
                    seen_event_ids.add(raw_event_id)
                    # Determine shooter and goalie
                    shooter_id = play.get('details', {}).get('scoringPlayerId') or play.get('details', {}).get('shootingPlayerId')
                    goalie_id = play.get('details', {}).get('goalieInNetId')
                    is_goal = (type_desc == 'goal')
                    shot_type = play.get('details', {}).get('shotType')

                    # Calculate score differential at the instant of the shot
                    shooter_score = home_score if is_home_event else away_score
                    defending_score = away_score if is_home_event else home_score
                    score_diff = shooter_score - defending_score

                    # Determine situation / strength state
                    situation_code = play.get('situationCode')
                    empty_net = False
                    strength_state = 'UNKNOWN'
                    if situation_code and len(str(situation_code)) == 4 and str(situation_code).isdigit():
                        away_g, away_s, home_s, home_g = [int(c) for c in str(situation_code)]
                        if is_home_event:
                            empty_net = (away_g == 0)
                            if home_s > away_s:
                                strength_state = 'PP'
                            elif home_s < away_s:
                                strength_state = 'SH'
                            else:
                                strength_state = 'EV'
                        else:
                            empty_net = (home_g == 0)
                            if away_s > home_s:
                                strength_state = 'PP'
                            elif away_s < home_s:
                                strength_state = 'SH'
                            else:
                                strength_state = 'EV'

                    # Coordinates and normalization
                    coords_missing = (raw_x is None or raw_y is None)
                    if not coords_missing:
                        should_flip = get_attacking_coordinate_transform(raw_x, raw_y, is_home_team=is_home_event)
                        norm_x, norm_y = apply_coordinate_transform(raw_x, raw_y, should_flip)
                        dist, ang = calculate_distance_and_angle(norm_x, norm_y)
                    else:
                        should_flip = False
                        norm_x, norm_y = None, None
                        dist, ang = 45.0, 0.0

                    # Previous event context
                    prev_type = 'none'
                    delta_t = 15.0
                    delta_d = 0.0
                    angle_change = 0.0

                    if prev_event is not None:
                        prev_type = prev_event.get('type', 'none')
                        prev_sec = prev_event.get('seconds', period_seconds)
                        delta_t = max(0.0, float(period_seconds - prev_sec))
                        prev_raw_x = prev_event.get('raw_x')
                        prev_raw_y = prev_event.get('raw_y')
                        
                        if not coords_missing and prev_raw_x is not None and prev_raw_y is not None:
                            # 1. Physical Euclidean distance remains raw Euclidean distance (unflipped)
                            delta_d = math.sqrt((raw_x - prev_raw_x)**2 + (raw_y - prev_raw_y)**2)
                            
                            # 2. Sequential angle change applies one unified attacking frame transform
                            prev_nx_shooter, prev_ny_shooter = apply_coordinate_transform(
                                prev_raw_x, prev_raw_y, should_flip
                            )
                            prev_dist, prev_ang = calculate_distance_and_angle(prev_nx_shooter, prev_ny_shooter)
                            angle_change = abs(ang - prev_ang)

                    feature_input = {
                        'distance': dist,
                        'angle': ang,
                        'coordinates_missing': 1 if coords_missing else 0,
                        'shot_type': shot_type,
                        'period': period,
                        'period_seconds': period_seconds,
                        'strength_state': strength_state,
                        'score_differential': score_diff,
                        'is_home': is_home_event,
                        'empty_net': empty_net,
                        'prev_event_type': prev_type,
                        'time_since_prev_event': delta_t,
                        'distance_from_prev_event': delta_d,
                        'angle_change': angle_change
                    }

                    features = cls.extract_features_from_dict(feature_input)
                    
                    # Attach metadata identifiers
                    record = {
                        'game_id': game_id,
                        'event_id': f"{game_id}_{raw_event_id}",
                        'season': season,
                        'game_date': game_date,
                        'period': period,
                        'period_time': time_str,
                        'period_seconds': period_seconds,
                        'shooter_id': shooter_id,
                        'shooter_team_id': event_owner_team_id,
                        'defending_team_id': away_team_id if is_home_event else home_team_id,
                        'goalie_id': goalie_id,
                        'event_type': type_desc,
                        'goal': 1 if is_goal else 0,
                        'raw_x': raw_x,
                        'raw_y': raw_y,
                        'norm_x': norm_x,
                        'norm_y': norm_y,
                        **features
                    }
                    shots.append(record)

            # Update score if goal scored
            if type_desc == 'goal':
                if is_home_event:
                    home_score += 1
                else:
                    away_score += 1

            # Update prev_event record using raw coordinates
            prev_event = {
                'type': type_desc,
                'seconds': period_seconds,
                'team_id': event_owner_team_id,
                'raw_x': raw_x,
                'raw_y': raw_y
            }

        return shots
