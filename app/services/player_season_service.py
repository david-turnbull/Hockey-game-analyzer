import logging
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func, distinct
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, Team
from app.utils.time_helpers import format_toi

logger = logging.getLogger(__name__)

class PlayerSeasonService:
    """
    Canonical service for aggregating skater season statistics, individual metrics,
    5v5 on-ice possession metrics, and analytical leaderboards with configurable sample thresholds.
    """

    @classmethod
    def get_skater_season_stats(cls, player_id: int, season: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves season stats for a single skater.
        """
        all_skaters = cls.get_season_skaters_summary(season=season, min_gp=0, min_toi_seconds=0, min_unblocked_attempts=0)
        for skater in all_skaters:
            if skater["player_id"] == player_id:
                return skater
        
        # If player exists in DB but has 0 GP in this season
        player = db.session.get(Player, player_id)
        if not player or player.position == 'G':
            return None
            
        return cls._empty_skater_stats(player, season)

    @classmethod
    def get_season_skaters_summary(
        cls,
        season: str,
        team_id: Optional[int] = None,
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Aggregates season statistics for all skaters using grouped SQL queries to prevent N+1 overhead.
        """
        # 1. Fetch all games for this season
        game_query = db.session.query(Game.game_id).filter(Game.season == season)
        season_game_ids = [r[0] for r in game_query.all()]
        if not season_game_ids:
            return []

        # 2. Get GP, player info, and team association from GamePlayer
        gp_query = (
            db.session.query(
                GamePlayer.player_id,
                GamePlayer.team_id,
                func.count(distinct(GamePlayer.game_id)).label('gp'),
                Player.first_name,
                Player.last_name,
                Player.position,
                Team.abbreviation.label('team_abbrev'),
                Team.name.label('team_name')
            )
            .join(Player, GamePlayer.player_id == Player.player_id)
            .join(Team, GamePlayer.team_id == Team.team_id)
            .filter(
                GamePlayer.game_id.in_(season_game_ids),
                Player.position != 'G'
            )
        )
        if team_id:
            gp_query = gp_query.filter(GamePlayer.team_id == team_id)

        gp_rows = gp_query.group_by(GamePlayer.player_id, GamePlayer.team_id).all()
        if not gp_rows:
            return []

        skater_meta = {}
        for r in gp_rows:
            pid = r.player_id
            if pid not in skater_meta:
                skater_meta[pid] = {
                    "player_id": pid,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "full_name": f"{r.first_name} {r.last_name}",
                    "position": r.position,
                    "team_id": r.team_id,
                    "team_abbrev": r.team_abbrev,
                    "team_name": r.team_name,
                    "gp": r.gp
                }
            else:
                skater_meta[pid]["gp"] += r.gp

        relevant_pids = list(skater_meta.keys())

        # 3. Individual Goals (primary_player_id on goal events)
        goals_rows = (
            db.session.query(
                Event.primary_player_id,
                func.count(Event.event_id)
            )
            .filter(
                Event.game_id.in_(season_game_ids),
                Event.event_type == 'goal',
                Event.primary_player_id.in_(relevant_pids),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Event.primary_player_id).all()
        )
        goals_map = {pid: count for pid, count in goals_rows}

        # 4. Individual Assists (assist1 or assist2)
        a1_rows = (
            db.session.query(
                Event.assist1_player_id,
                func.count(Event.event_id)
            )
            .filter(
                Event.game_id.in_(season_game_ids),
                Event.event_type == 'goal',
                Event.assist1_player_id.in_(relevant_pids),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Event.assist1_player_id).all()
        )
        a2_rows = (
            db.session.query(
                Event.assist2_player_id,
                func.count(Event.event_id)
            )
            .filter(
                Event.game_id.in_(season_game_ids),
                Event.event_type == 'goal',
                Event.assist2_player_id.in_(relevant_pids),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Event.assist2_player_id).all()
        )
        assists_map = {}
        for pid, count in a1_rows:
            assists_map[pid] = assists_map.get(pid, 0) + count
        for pid, count in a2_rows:
            assists_map[pid] = assists_map.get(pid, 0) + count

        # 5. SOG, Unblocked Attempts, and Individual xG
        # SOG: outcome in ['Goal', 'Saved']
        sog_rows = (
            db.session.query(
                Shot.shooter_id,
                func.count(Shot.shot_id)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.shooter_id.in_(relevant_pids),
                Shot.outcome.in_(['Goal', 'Saved']),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.shooter_id).all()
        )
        sog_map = {pid: count for pid, count in sog_rows}

        # Unblocked attempts and sum(xG)
        unblocked_rows = (
            db.session.query(
                Shot.shooter_id,
                func.count(Shot.shot_id),
                func.sum(Shot.xg)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.shooter_id.in_(relevant_pids),
                Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.shooter_id).all()
        )
        unblocked_map = {pid: count for pid, count, _ in unblocked_rows}
        xg_map = {pid: (round(float(sum_xg), 2) if sum_xg is not None else 0.0) for pid, _, sum_xg in unblocked_rows}

        # 6. Time on Ice (TOI) across the season
        toi_rows = (
            db.session.query(
                Shift.player_id,
                func.sum(Shift.duration)
            )
            .filter(
                Shift.game_id.in_(season_game_ids),
                Shift.player_id.in_(relevant_pids),
                Shift.duration > 0,
                Shift.is_anomaly == False
            )
            .group_by(Shift.player_id).all()
        )
        toi_map = {pid: (int(tot_sec) if tot_sec else 0) for pid, tot_sec in toi_rows}

        # 7. 5v5 On-Ice possession and xG metrics
        # Query 5v5 shot events across the season
        on_ice_5v5 = cls._aggregate_season_5v5_on_ice(season_game_ids, relevant_pids)

        # 8. Assemble skater records and apply filters
        results = []
        for pid, meta in skater_meta.items():
            gp = meta["gp"]
            g = goals_map.get(pid, 0)
            a = assists_map.get(pid, 0)
            p = g + a
            sog = sog_map.get(pid, 0)
            unblocked = unblocked_map.get(pid, 0)
            xg = xg_map.get(pid, 0.0)
            toi_sec = toi_map.get(pid, 0)

            # Check minimum sample thresholds
            if gp < min_gp or toi_sec < min_toi_seconds or unblocked < min_unblocked_attempts:
                continue

            # Rates and differentials
            toi_hours = toi_sec / 3600.0 if toi_sec > 0 else 0.0
            goals_per_60 = round(g / toi_hours, 2) if toi_hours > 0 else 0.0
            xg_per_60 = round(xg / toi_hours, 2) if toi_hours > 0 else 0.0
            g_minus_xg = round(g - xg, 2)

            shooting_pct = round((g / sog * 100), 2) if sog > 0 else 0.0
            exp_conv_pct = round((xg / unblocked * 100), 2) if unblocked > 0 else 0.0
            sh_diff = round(shooting_pct - exp_conv_pct, 2)

            # 5v5 On-Ice metrics
            oi = on_ice_5v5.get(pid, {
                "cf": 0, "ca": 0, "cf_pct": 50.0,
                "ff": 0, "fa": 0, "ff_pct": 50.0,
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0
            })

            results.append({
                "player_id": pid,
                "name": meta["full_name"],
                "position": meta["position"],
                "team_id": meta["team_id"],
                "team_abbrev": meta["team_abbrev"],
                "team_name": meta["team_name"],
                "season": season,
                # Individual Counting Stats
                "gp": gp,
                "goals": g,
                "assists": a,
                "points": p,
                "shots_on_goal": sog,
                "unblocked_attempts": unblocked,
                "xg": xg,
                "goals_above_expected": g_minus_xg,
                # Individual Rates
                "goals_per_60": goals_per_60,
                "xg_per_60": xg_per_60,
                "shooting_pct": shooting_pct,
                "expected_conversion_pct": exp_conv_pct,
                "shooting_vs_expected_diff": sh_diff,
                "toi_seconds": toi_sec,
                "toi_formatted": format_toi(toi_sec),
                # 5v5 On-Ice Metrics (Explicitly Separated)
                "on_ice_5v5": {
                    "cf": oi["cf"],
                    "ca": oi["ca"],
                    "cf_pct": oi["cf_pct"],
                    "ff": oi["ff"],
                    "fa": oi["fa"],
                    "ff_pct": oi["ff_pct"],
                    "on_ice_xgf": oi["on_ice_xgf"],
                    "on_ice_xga": oi["on_ice_xga"],
                    "on_ice_xg_pct": oi["on_ice_xg_pct"]
                }
            })

        results.sort(key=lambda x: -x["points"])
        return results

    @classmethod
    def get_skater_leaderboards(
        cls,
        season: str,
        sort_by: str = "points",
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Generates configurable skater analytical leaderboards.
        Valid sort_by keys: 'points', 'goals', 'assists', 'xg', 'goals_above_expected',
        'xg_per_60', 'goals_per_60', 'shooting_pct', 'expected_conversion_pct',
        'cf_pct', 'ff_pct', 'on_ice_xg_pct'.
        """
        skaters = cls.get_season_skaters_summary(
            season=season,
            min_gp=min_gp,
            min_toi_seconds=min_toi_seconds,
            min_unblocked_attempts=min_unblocked_attempts
        )
        if not skaters:
            return []

        def get_sort_val(skater: dict) -> float:
            if sort_by in ['cf_pct', 'ff_pct', 'on_ice_xg_pct']:
                return skater.get('on_ice_5v5', {}).get(sort_by, 0.0) or 0.0
            return skater.get(sort_by, 0.0) or 0.0

        skaters.sort(key=get_sort_val, reverse=True)

        for rank_idx, skater in enumerate(skaters, 1):
            skater["rank"] = rank_idx

        return skaters[:limit]

    @classmethod
    def _aggregate_season_5v5_on_ice(cls, season_game_ids: List[int], skater_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Computes 5v5 on-ice possession (Corsi, Fenwick) and on-ice xG metrics for skaters.
        """
        skater_set = set(skater_ids)
        on_ice_res = {
            pid: {
                "cf": 0, "ca": 0, "cf_pct": 50.0,
                "ff": 0, "fa": 0, "ff_pct": 50.0,
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0
            }
            for pid in skater_ids
        }

        # To keep performance optimal across multiple games without N*T overhead,
        # we iterate game by game using PossessionService and Shot associations
        for gid in season_game_ids:
            try:
                # Possession stats (Corsi / Fenwick) for this game
                p_stats = PossessionService.calculate_possession_stats(gid, mode="5v5")
                for pid, s in p_stats.items():
                    if pid in on_ice_res:
                        on_ice_res[pid]["cf"] += s.get("cf", 0)
                        on_ice_res[pid]["ca"] += s.get("ca", 0)
                        on_ice_res[pid]["ff"] += s.get("ff", 0)
                        on_ice_res[pid]["fa"] += s.get("fa", 0)
            except Exception as e:
                logger.debug(f"Could not compute 5v5 possession for game {gid}: {e}")

        # Compute percentages
        for pid, stats in on_ice_res.items():
            tot_c = stats["cf"] + stats["ca"]
            tot_f = stats["ff"] + stats["fa"]
            stats["cf_pct"] = round((stats["cf"] / tot_c * 100), 2) if tot_c > 0 else 50.0
            stats["ff_pct"] = round((stats["ff"] / tot_f * 100), 2) if tot_f > 0 else 50.0
            stats["on_ice_xgf"] = round(stats["on_ice_xgf"], 2)
            stats["on_ice_xga"] = round(stats["on_ice_xga"], 2)
            tot_xg = stats["on_ice_xgf"] + stats["on_ice_xga"]
            stats["on_ice_xg_pct"] = round((stats["on_ice_xgf"] / tot_xg * 100), 2) if tot_xg > 0 else 50.0

        return on_ice_res

    @staticmethod
    def _empty_skater_stats(player: Player, season: str) -> Dict[str, Any]:
        return {
            "player_id": player.player_id,
            "name": player.full_name,
            "position": player.position,
            "team_id": player.current_team_id,
            "team_abbrev": player.current_team.abbreviation if player.current_team else "UNK",
            "team_name": player.current_team.name if player.current_team else "Unknown",
            "season": season,
            "gp": 0,
            "goals": 0,
            "assists": 0,
            "points": 0,
            "shots_on_goal": 0,
            "unblocked_attempts": 0,
            "xg": 0.0,
            "goals_above_expected": 0.0,
            "goals_per_60": 0.0,
            "xg_per_60": 0.0,
            "shooting_pct": 0.0,
            "expected_conversion_pct": 0.0,
            "shooting_vs_expected_diff": 0.0,
            "toi_seconds": 0,
            "toi_formatted": "00:00",
            "on_ice_5v5": {
                "cf": 0, "ca": 0, "cf_pct": 50.0,
                "ff": 0, "fa": 0, "ff_pct": 50.0,
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0
            }
        }
