import logging
from bisect import bisect_right
from collections import defaultdict
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, PlayerGameAnalytics
from app.services.possession_service import PossessionService
from app.services.on_ice_service import OnIceService

logger = logging.getLogger(__name__)

class PlayerGameAnalyticsBuilder:
    """
    Deterministic service for deriving per-game player analytical records (PlayerGameAnalytics).
    Stores individual counting stats and additive 5v5 on-ice primitives.
    Enforces idempotency and incremental regeneration when games are re-ingested.
    """

    @classmethod
    def build_game_analytics(cls, game_id: int) -> List[PlayerGameAnalytics]:
        """
        Derives and persists PlayerGameAnalytics records for a single game.
        Idempotent & Atomic: Replaces any existing analytics rows for the specified game_id
        in a single transaction. If rebuilding fails or raises an exception, the transaction is
        rolled back so pre-existing analytics rows remain intact.
        """
        try:
            game = db.session.get(Game, game_id)
            if not game:
                logger.warning(f"Cannot build game analytics: Game {game_id} not found.")
                return []

            home_team_id = game.home_team_id
            away_team_id = game.away_team_id
            season = game.season

            # 1. Fetch skaters appearing in GamePlayer (excluding goalies)
            gp_rows = (
                db.session.query(
                    GamePlayer.player_id,
                    GamePlayer.team_id,
                    Player.position
                )
                .join(Player, GamePlayer.player_id == Player.player_id)
                .filter(
                    GamePlayer.game_id == game_id,
                    Player.position != 'G'
                )
                .all()
            )

            if not gp_rows:
                # Delete pre-existing records for game_id to guarantee idempotency
                db.session.query(PlayerGameAnalytics).filter_by(game_id=game_id).delete(synchronize_session='fetch')
                db.session.flush()
                db.session.commit()
                return []

            skater_meta = {}
            for r in gp_rows:
                skater_meta[r.player_id] = {
                    "team_id": r.team_id,
                    "position": r.position
                }
            skater_pids = set(skater_meta.keys())

            # 2. Individual Goals, Primary Assists, Secondary Assists
            events_goals = (
                Event.query.filter(
                    Event.game_id == game_id,
                    Event.event_type == 'goal',
                    (Event.period_type != 'SO') | (Event.period_type.is_(None))
                ).all()
            )

            goals_map = defaultdict(int)
            a1_map = defaultdict(int)
            a2_map = defaultdict(int)

            for ev in events_goals:
                if ev.primary_player_id in skater_pids:
                    goals_map[ev.primary_player_id] += 1
                if ev.assist1_player_id in skater_pids:
                    a1_map[ev.assist1_player_id] += 1
                if ev.assist2_player_id in skater_pids:
                    a2_map[ev.assist2_player_id] += 1

            # 3. Shots on Goal, Unblocked Attempts, and Individual xG from Shot table
            shots_rows = (
                db.session.query(
                    Shot.shooter_id,
                    Shot.outcome,
                    Shot.xg
                )
                .join(Event, Shot.shot_id == Event.event_id)
                .filter(
                    Event.game_id == game_id,
                    Shot.shooter_id.in_(skater_pids),
                    (Event.period_type != 'SO') | (Event.period_type.is_(None))
                )
                .all()
            )

            sog_map = defaultdict(int)
            unblocked_map = defaultdict(int)
            xg_map = defaultdict(float)

            for shooter_id, outcome, xg_val in shots_rows:
                if outcome in ['Goal', 'Saved']:
                    sog_map[shooter_id] += 1
                if outcome in ['Goal', 'Saved', 'Missed']:
                    unblocked_map[shooter_id] += 1
                    if xg_val is not None:
                        xg_map[shooter_id] += float(xg_val)

            # 4. Total Time on Ice (all situations) from Shift table
            shifts = (
                Shift.query.filter(
                    Shift.game_id == game_id,
                    Shift.is_anomaly == False,
                    Shift.duration > 0,
                    Shift.start_elapsed_seconds.isnot(None),
                    Shift.end_elapsed_seconds.isnot(None)
                ).all()
            )

            toi_all_map = defaultdict(int)
            for s in shifts:
                if s.player_id in skater_pids:
                    toi_all_map[s.player_id] += s.duration

            # 5. 5v5 On-Ice metrics and 5v5 TOI
            on_ice_5v5 = cls._compute_game_5v5_on_ice(
                game_id=game_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                shifts=shifts,
                skater_pids=skater_pids
            )

            # 6. Delete pre-existing records for game_id to guarantee idempotency in single transaction
            db.session.query(PlayerGameAnalytics).filter_by(game_id=game_id).delete(synchronize_session='fetch')
            db.session.flush()

            # 7. Construct new PlayerGameAnalytics records
            now = datetime.now(timezone.utc)
            new_records = []

            for pid, meta in skater_meta.items():
                g = goals_map[pid]
                a1 = a1_map[pid]
                a2 = a2_map[pid]
                a = a1 + a2
                pts = g + a
                sog = sog_map[pid]
                unblocked = unblocked_map[pid]
                ind_xg = round(xg_map[pid], 4)
                toi_sec = toi_all_map[pid]

                oi5v5 = on_ice_5v5.get(pid, {
                    "cf": 0, "ca": 0, "ff": 0, "fa": 0,
                    "xgf": 0.0, "xga": 0.0, "toi_5v5_seconds": 0
                })

                rec = PlayerGameAnalytics(
                    game_id=game_id,
                    player_id=pid,
                    team_id=meta["team_id"],
                    season=season,
                    position=meta["position"],
                    toi_seconds=toi_sec,
                    toi_5v5_seconds=oi5v5["toi_5v5_seconds"],
                    goals=g,
                    assists=a,
                    primary_assists=a1,
                    secondary_assists=a2,
                    points=pts,
                    shots_on_goal=sog,
                    unblocked_attempts=unblocked,
                    individual_xg=ind_xg,
                    cf_5v5=oi5v5["cf"],
                    ca_5v5=oi5v5["ca"],
                    ff_5v5=oi5v5["ff"],
                    fa_5v5=oi5v5["fa"],
                    xgf_5v5=round(oi5v5["xgf"], 4),
                    xga_5v5=round(oi5v5["xga"], 4),
                    created_at=now,
                    updated_at=now
                )
                new_records.append(rec)

            db.session.add_all(new_records)
            db.session.commit()
            return new_records
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to build analytics for game {game_id}: {e}")
            raise

    @classmethod
    def _compute_game_5v5_on_ice(
        cls,
        game_id: int,
        home_team_id: int,
        away_team_id: int,
        shifts: List[Shift],
        skater_pids: set
    ) -> Dict[int, Dict[str, Any]]:
        """
        Computes 5v5 on-ice possession (CF, CA, FF, FA), xGF, xGA, and 5v5 TOI
        for skaters in a single game.

        Preserves historical 5v5 attribution contract (matching PlayerSeasonService):
        - 5v5 TOI requires reconstructed true 5v5 lineups (exactly 5 skaters and 1 goalie on both sides).
        - 5v5 event attribution uses the authoritative event strength flag plus active shifts,
          even if the reconstructed lineup is incomplete.
        """
        res = {
            pid: {
                "cf": 0, "ca": 0, "ff": 0, "fa": 0,
                "xgf": 0.0, "xga": 0.0, "toi_5v5_seconds": 0
            }
            for pid in skater_pids
        }

        if not shifts:
            return res

        # Map all player positions for shift players
        shift_pids = list(set(s.player_id for s in shifts))
        players_pos = dict(
            db.session.query(Player.player_id, Player.position)
            .filter(Player.player_id.in_(shift_pids))
            .all()
        )

        max_time = max(3600, max((s.end_elapsed_seconds or 0) for s in shifts))
        intervals = OnIceService.build_active_player_intervals(shifts, max_time, home_team_id)
        if not intervals:
            return res

        # 5v5 TOI calculation: requires true reconstructed 5v5 lineup (5 skaters + 1 goalie on each side)
        valid_5v5_intervals = []
        for interval in intervals:
            hp = interval["home_players"]
            ap = interval["away_players"]
            h_goalies = sum(1 for p in hp if players_pos.get(p) == "G")
            a_goalies = sum(1 for p in ap if players_pos.get(p) == "G")
            h_skaters = sum(1 for p in hp if players_pos.get(p) != "G")
            a_skaters = sum(1 for p in ap if players_pos.get(p) != "G")

            if h_skaters != 5 or a_skaters != 5 or h_goalies != 1 or a_goalies != 1:
                continue

            valid_5v5_intervals.append(interval)
            duration = interval["duration"]

            for p in hp:
                if p in skater_pids:
                    res[p]["toi_5v5_seconds"] += duration
            for p in ap:
                if p in skater_pids:
                    res[p]["toi_5v5_seconds"] += duration

        # 5v5 Event attribution: uses event's authoritative 5v5 strength flag plus player's active shift
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events_with_shots = (
            db.session.query(Event, Shot.xg)
            .outerjoin(Shot, Event.event_id == Shot.shot_id)
            .filter(
                Event.game_id == game_id,
                Event.event_type.in_(shot_event_types),
                (Event.period_type != 'SO') | (Event.period_type.is_(None)),
                Event.elapsed_game_seconds.isnot(None)
            )
            .order_by(Event.elapsed_game_seconds.asc())
            .all()
        )

        starts = [interval["start"] for interval in intervals]

        for event, xg in events_with_shots:
            if not PossessionService.matches_strength(event, "5v5", home_team_id):
                continue

            t = event.elapsed_game_seconds
            if t is None:
                continue

            idx = bisect_right(starts, t) - 1
            if idx < 0:
                continue
            interval = intervals[idx]
            if not (interval["start"] <= t < interval["end"]):
                continue

            shot_team_id = event.team_id
            is_blocked = (event.event_type == "blocked-shot")
            shot_xg = float(xg) if xg is not None else 0.0

            for side_team_id, active_players in (
                (home_team_id, interval["home_players"]),
                (away_team_id, interval["away_players"]),
            ):
                is_for = (side_team_id == shot_team_id)
                for pid in active_players:
                    if pid not in skater_pids or players_pos.get(pid) == "G":
                        continue

                    if is_for:
                        res[pid]["cf"] += 1
                        if not is_blocked:
                            res[pid]["ff"] += 1
                            res[pid]["xgf"] += shot_xg
                    else:
                        res[pid]["ca"] += 1
                        if not is_blocked:
                            res[pid]["fa"] += 1
                            res[pid]["xga"] += shot_xg

        return res
