import logging
from app.models import Game, Team, Player, Event, Shot, Shift

logger = logging.getLogger(__name__)

class DataQualityChecker:
    """Validates hockey game data records and outputs structured quality reports."""

    def __init__(self):
        self.warnings = []
        self.rejected_records_count = 0
        self.ingested_records_count = 0
        self.seen_event_ids = set()
        self.seen_shift_ids = set()

    def add_warning(self, category: str, message: str, record_id: str = None):
        warn_msg = f"[{category}] Record {record_id}: {message}" if record_id else f"[{category}] {message}"
        logger.warning(warn_msg)
        self.warnings.append({"category": category, "message": message, "record_id": record_id})

    def validate_game(self, game: Game) -> bool:
        """Validates game level details. Returns True if valid, False if rejected."""
        if not game.game_id:
            self.add_warning("GAME_REJECT", "Missing Game ID")
            self.rejected_records_count += 1
            return False
            
        if not game.season or len(game.season) != 8:
            self.add_warning("GAME_WARN", f"Invalid season format: {game.season}", str(game.game_id))
            
        if not game.home_team_id or not game.away_team_id:
            self.add_warning("GAME_REJECT", "Missing home/away team reference", str(game.game_id))
            self.rejected_records_count += 1
            return False
            
        self.ingested_records_count += 1
        return True

    def validate_team(self, team: Team) -> bool:
        """Validates team details."""
        if not team.team_id:
            self.add_warning("TEAM_REJECT", "Missing Team ID")
            self.rejected_records_count += 1
            return False
        if not team.abbreviation or len(team.abbreviation) > 3:
            self.add_warning("TEAM_WARN", f"Suspicious team abbreviation: {team.abbreviation}", str(team.team_id))
        self.ingested_records_count += 1
        return True

    def validate_player(self, player: Player) -> bool:
        """Validates player roster details."""
        if not player.player_id:
            self.add_warning("PLAYER_REJECT", "Missing Player ID")
            self.rejected_records_count += 1
            return False
        if not player.first_name or not player.last_name:
            self.add_warning("PLAYER_WARN", "Player missing first/last name", str(player.player_id))
        self.ingested_records_count += 1
        return True

    def validate_event(self, event: Event, known_player_ids: set, known_team_ids: set) -> bool:
        """Validates event level records."""
        if not event.event_id or not event.game_id:
            self.add_warning("EVENT_REJECT", "Missing Event ID or Game ID")
            self.rejected_records_count += 1
            return False
            
        if event.event_id in self.seen_event_ids:
            self.add_warning("EVENT_WARN", f"Duplicate Event ID skipped: {event.event_id}", event.event_id)
            return False
            
        self.seen_event_ids.add(event.event_id)
            
        # Bounds check for period
        if event.period < 1 or event.period > 10:
            self.add_warning("EVENT_WARN", f"Suspicious period number: {event.period}", event.event_id)
            
        # Clock validation
        if event.elapsed_game_seconds is None:
            self.add_warning("EVENT_WARN", f"Malformed or missing clock value: {event.period_time}", event.event_id)

        # Coordinates check
        if event.x_coordinate is not None:
            if abs(event.x_coordinate) > 100.1:
                self.add_warning("EVENT_WARN", f"X Coordinate out of bounds: {event.x_coordinate}", event.event_id)
        if event.y_coordinate is not None:
            if abs(event.y_coordinate) > 42.6:
                self.add_warning("EVENT_WARN", f"Y Coordinate out of bounds: {event.y_coordinate}", event.event_id)
                
        # Foreign key integrity
        if event.team_id and event.team_id not in known_team_ids:
            self.add_warning("EVENT_INTEGRITY", f"Event team ID {event.team_id} not in loaded team list", event.event_id)
        if event.primary_player_id and event.primary_player_id not in known_player_ids:
            self.add_warning("EVENT_INTEGRITY", f"Primary player {event.primary_player_id} not in roster", event.event_id)
        if event.secondary_player_id and event.secondary_player_id not in known_player_ids:
            self.add_warning("EVENT_INTEGRITY", f"Secondary player {event.secondary_player_id} not in roster", event.event_id)
        if event.served_by_player_id and event.served_by_player_id not in known_player_ids:
            self.add_warning("EVENT_INTEGRITY", f"Serving player {event.served_by_player_id} not in roster", event.event_id)
            
        # Shot event shooter validation (fatal error)
        if event.event_type in ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']:
            if not event.primary_player_id or event.primary_player_id not in known_player_ids:
                self.add_warning("EVENT_REJECT", f"Shot event missing valid shooter ID", event.event_id)
                self.rejected_records_count += 1
                return False

        self.ingested_records_count += 1
        return True

    def validate_shot(self, shot: Shot, known_player_ids: set) -> bool:
        """Validates shot details."""
        if not shot.shot_id:
            self.add_warning("SHOT_REJECT", "Missing Shot ID")
            self.rejected_records_count += 1
            return False
            
        if shot.distance is not None and (shot.distance < 0 or shot.distance > 200):
            self.add_warning("SHOT_WARN", f"Calculated distance physically suspicious: {shot.distance} ft", shot.shot_id)
            
        if shot.angle is not None and (shot.angle < -90 or shot.angle > 180):
            self.add_warning("SHOT_WARN", f"Calculated angle suspicious: {shot.angle} deg", shot.shot_id)
            
        # Shooter validation - missing shooter is fatal
        if not shot.shooter_id:
            self.add_warning("SHOT_REJECT", "Missing shooter ID for shot attempt", shot.shot_id)
            self.rejected_records_count += 1
            return False
            
        if shot.shooter_id not in known_player_ids:
            self.add_warning("SHOT_REJECT", f"Shooter {shot.shooter_id} not in roster", shot.shot_id)
            self.rejected_records_count += 1
            return False
            
        self.ingested_records_count += 1
        return True

    def validate_shifts(self, shifts: list, player_positions: dict = None) -> list:
        """
        Validates shift records, checks for negative durations,
        impossible shift lengths, and overlapping shifts per player.
        Returns a list of validated shifts (retaining only valid ones).
        """
        if player_positions is None:
            player_positions = {}
            
        player_shifts = {}
        valid_shifts = []
        
        for shift in shifts:
            if not shift.shift_id:
                self.add_warning("SHIFT_REJECT", "Missing Shift ID")
                self.rejected_records_count += 1
                continue
                
            if shift.shift_id in self.seen_shift_ids:
                self.add_warning("SHIFT_WARN", f"Duplicate Shift ID skipped: {shift.shift_id}", shift.shift_id)
                continue
                
            self.seen_shift_ids.add(shift.shift_id)
            
            # Duration check
            if shift.duration is None:
                self.add_warning("SHIFT_WARN", "Missing or invalid shift duration", shift.shift_id)
                
            # Negative duration check (fatal)
            if shift.duration is not None and shift.duration < 0:
                self.add_warning("SHIFT_REJECT", f"Negative shift duration: {shift.duration}s", shift.shift_id)
                self.rejected_records_count += 1
                continue
                
            # Zero-duration shifts check
            if shift.duration == 0 or (shift.start_time == shift.end_time and shift.start_time is not None):
                self.add_warning("SHIFT_ANOMALY", "Zero-duration shift detected", shift.shift_id)
                shift.is_anomaly = True
                shift.anomaly_description = "Zero-duration shift"
                valid_shifts.append(shift)
                continue
                
            # Position-aware shift length validation
            pos = player_positions.get(shift.player_id, "")
            if pos == "G":
                # Goalie-specific validation (only warn if goalie shift > 80 mins)
                if shift.duration is not None and shift.duration > 4800:
                    self.add_warning("SHIFT_WARN", f"Excessive goalie shift duration: {shift.duration}s", shift.shift_id)
            else:
                # Skater validation (warn if skater shift > 5 mins)
                if shift.duration is not None and shift.duration > 300:
                    self.add_warning("SHIFT_WARN", f"Excessive shift duration: {shift.duration}s", shift.shift_id)
                
            valid_shifts.append(shift)
            
            # Save for overlap checks (only if not an anomaly)
            player_shifts.setdefault(shift.player_id, []).append(shift)
            
        # Overlap checks per player
        for player_id, p_shifts in player_shifts.items():
            # Sort player shifts by start time
            p_shifts.sort(key=lambda s: s.start_elapsed_seconds if s.start_elapsed_seconds is not None else -1)
            
            for i in range(len(p_shifts) - 1):
                curr_shift = p_shifts[i]
                next_shift = p_shifts[i + 1]
                
                if curr_shift.start_elapsed_seconds is None or next_shift.start_elapsed_seconds is None:
                    continue
                
                # Check if current shift overlaps with next shift (within same period)
                if curr_shift.period == next_shift.period:
                    if curr_shift.end_elapsed_seconds > next_shift.start_elapsed_seconds:
                        self.add_warning(
                            "SHIFT_OVERLAP",
                            f"Overlapping shifts found. Shift 1 end ({curr_shift.end_time}) > Shift 2 start ({next_shift.start_time})",
                            curr_shift.shift_id
                        )
                        
        self.ingested_records_count += len(valid_shifts)
        return valid_shifts

    def get_summary(self) -> dict:
        """Returns the run summary statistics."""
        return {
            "records_ingested": self.ingested_records_count,
            "records_rejected": self.rejected_records_count,
            "warnings_count": len(self.warnings),
            "warnings": self.warnings
        }
