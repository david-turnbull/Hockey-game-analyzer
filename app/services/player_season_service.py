import logging
from bisect import bisect_right
from collections import defaultdict
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func, distinct
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, Team, PlayerGameAnalytics
from app.utils.time_helpers import format_toi
from app.services.possession_service import PossessionService
from app.services.on_ice_service import OnIceService
from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService

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
        If derived coverage is complete, executes a direct single-player SQL aggregation
        without querying or computing full-season league-wide skater stats.
        """
        if PlayerGameAnalyticsAuditService.is_derived_coverage_complete(season):
            return cls._get_skater_season_stats_derived(player_id, season)

        all_skaters = cls._get_season_skaters_summary_legacy(season=season, min_gp=0, min_toi_seconds=0, min_unblocked_attempts=0)
        for skater in all_skaters:
            if skater["player_id"] == player_id:
                return skater

        # If player exists in DB but has 0 GP in this season
        player = db.session.get(Player, player_id)
        if not player or player.position == 'G':
            return None

        return cls._empty_skater_stats(player, season)

    @classmethod
    def _get_skater_season_stats_derived(cls, player_id: int, season: str) -> Optional[Dict[str, Any]]:
        """
        Direct single-player SQL aggregation path over PlayerGameAnalytics.
        Queries ONLY the specified player_id, preserving exact response schema,
        stint representations, and zero-GP fallback behavior.
        """
        player = db.session.get(Player, player_id)
        if not player or player.position == 'G':
            return None

        # Fetch player's team stints in game order
        stint_rows = (
            db.session.query(
                PlayerGameAnalytics.team_id,
                Team.abbreviation,
                Team.name
            )
            .join(Team, PlayerGameAnalytics.team_id == Team.team_id)
            .filter(
                PlayerGameAnalytics.player_id == player_id,
                PlayerGameAnalytics.season == season
            )
            .order_by(PlayerGameAnalytics.game_id.asc())
            .all()
        )

        if not stint_rows:
            return cls._empty_skater_stats(player, season)

        stints = []
        for tid, abbrev, name in stint_rows:
            if not stints or stints[-1]["team_id"] != tid:
                stints.append({"team_id": tid, "abbrev": abbrev, "name": name})

        rep_team_abbrev = "/".join(s["abbrev"] for s in stints)
        rep_team_name = " / ".join(s["name"] for s in stints) if len(stints) > 1 else stints[0]["name"]
        rep_team_id = stints[-1]["team_id"]
        stints_list = [s["abbrev"] for s in stints]

        # Aggregate player's statistics directly in SQL
        r = (
            db.session.query(
                func.count(PlayerGameAnalytics.game_id).label("gp"),
                func.sum(PlayerGameAnalytics.goals).label("goals"),
                func.sum(PlayerGameAnalytics.assists).label("assists"),
                func.sum(PlayerGameAnalytics.points).label("points"),
                func.sum(PlayerGameAnalytics.shots_on_goal).label("shots"),
                func.sum(PlayerGameAnalytics.unblocked_attempts).label("unblocked"),
                func.sum(PlayerGameAnalytics.individual_xg).label("xg"),
                func.sum(PlayerGameAnalytics.toi_seconds).label("toi_seconds"),
                func.sum(PlayerGameAnalytics.toi_5v5_seconds).label("toi_5v5_seconds"),
                func.sum(PlayerGameAnalytics.cf_5v5).label("cf"),
                func.sum(PlayerGameAnalytics.ca_5v5).label("ca"),
                func.sum(PlayerGameAnalytics.ff_5v5).label("ff"),
                func.sum(PlayerGameAnalytics.fa_5v5).label("fa"),
                func.sum(PlayerGameAnalytics.xgf_5v5).label("xgf"),
                func.sum(PlayerGameAnalytics.xga_5v5).label("xga")
            )
            .filter(
                PlayerGameAnalytics.player_id == player_id,
                PlayerGameAnalytics.season == season
            )
            .first()
        )

        if not r or not r.gp:
            return cls._empty_skater_stats(player, season)

        gp = r.gp
        g = r.goals or 0
        a = r.assists or 0
        p = g + a
        sog = r.shots or 0
        unblocked = r.unblocked or 0
        xg = round(float(r.xg or 0.0), 2)
        toi_sec = r.toi_seconds or 0

        toi_hours = toi_sec / 3600.0 if toi_sec > 0 else 0.0
        goals_per_60 = round(g / toi_hours, 2) if toi_hours > 0 else 0.0
        xg_per_60 = round(xg / toi_hours, 2) if toi_hours > 0 else 0.0
        g_minus_xg = round(g - xg, 2)

        shooting_pct = round((g / sog * 100), 2) if sog > 0 else 0.0
        exp_conv_pct = round((xg / unblocked * 100), 2) if unblocked > 0 else 0.0
        sh_diff = round(shooting_pct - exp_conv_pct, 2)

        cf = r.cf or 0
        ca = r.ca or 0
        ff = r.ff or 0
        fa = r.fa or 0
        xgf = round(float(r.xgf or 0.0), 2)
        xga = round(float(r.xga or 0.0), 2)
        toi_5v5 = r.toi_5v5_seconds or 0

        tot_c = cf + ca
        cf_pct = round((cf / tot_c * 100), 2) if tot_c > 0 else 50.0

        tot_f = ff + fa
        ff_pct = round((ff / tot_f * 100), 2) if tot_f > 0 else 50.0

        tot_xg = xgf + xga
        on_ice_xg_pct = round((xgf / tot_xg * 100), 2) if tot_xg > 0 else 50.0

        full_name = f"{player.first_name} {player.last_name}"

        return {
            "player_id": player_id,
            "name": full_name,
            "position": player.position,
            "team_id": rep_team_id,
            "team_abbrev": rep_team_abbrev,
            "team": rep_team_abbrev,
            "team_name": rep_team_name,
            "teams": rep_team_abbrev,
            "stints": stints_list,
            "season": season,
            "gp": gp,
            "goals": g,
            "assists": a,
            "points": p,
            "shots": sog,
            "shots_on_goal": sog,
            "unblocked_attempts": unblocked,
            "xg": xg,
            "goals_above_expected": g_minus_xg,
            "goals_minus_xg": g_minus_xg,
            "g_minus_xg": g_minus_xg,
            "goals_per_60": goals_per_60,
            "xg_per_60": xg_per_60,
            "shooting_pct": shooting_pct,
            "expected_conversion_pct": exp_conv_pct,
            "shooting_vs_expected_diff": sh_diff,
            "toi_seconds": toi_sec,
            "toi_formatted": format_toi(toi_sec),
            "on_ice_5v5": {
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "ff": ff,
                "fa": fa,
                "ff_pct": ff_pct,
                "on_ice_xgf": xgf,
                "on_ice_xga": xga,
                "on_ice_xg_pct": on_ice_xg_pct,
                "xgf": xgf,
                "xga": xga,
                "xg_pct": on_ice_xg_pct,
                "toi_seconds": toi_5v5,
                "toi_formatted": format_toi(toi_5v5)
            }
        }

    @classmethod
    def get_season_skaters_summary(
        cls,
        season: str,
        team_id: Optional[int] = None,
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0,
        include_on_ice_5v5: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Aggregates season statistics for all skaters.
        Uses high-performance derived table (PlayerGameAnalytics) ONLY when the target season
        is fully backfilled and complete according to PlayerGameAnalyticsAuditService.
        Otherwise, falls back to legacy multi-table join calculation.
        """
        if PlayerGameAnalyticsAuditService.is_season_complete(season):
            return cls._get_season_skaters_summary_derived(
                season=season,
                team_id=team_id,
                min_gp=min_gp,
                min_toi_seconds=min_toi_seconds,
                min_unblocked_attempts=min_unblocked_attempts,
                include_on_ice_5v5=include_on_ice_5v5
            )
        else:
            return cls._get_season_skaters_summary_legacy(
                season=season,
                team_id=team_id,
                min_gp=min_gp,
                min_toi_seconds=min_toi_seconds,
                min_unblocked_attempts=min_unblocked_attempts,
                include_on_ice_5v5=include_on_ice_5v5
            )

    @classmethod
    def _get_season_skaters_summary_derived(
        cls,
        season: str,
        team_id: Optional[int] = None,
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0,
        include_on_ice_5v5: bool = True
    ) -> List[Dict[str, Any]]:

        # Fast Derived SQL Aggregation Path
        teams_map = {
            t.team_id: {"abbrev": t.abbreviation, "name": t.name}
            for t in db.session.query(Team.team_id, Team.abbreviation, Team.name).all()
        }

        stint_query = (
            db.session.query(
                PlayerGameAnalytics.player_id,
                PlayerGameAnalytics.team_id
            )
            .filter(PlayerGameAnalytics.season == season)
            .order_by(PlayerGameAnalytics.game_id.asc())
        )
        if team_id is not None:
            stint_query = stint_query.filter(PlayerGameAnalytics.team_id == team_id)

        stint_rows = stint_query.all()
        if not stint_rows:
            return []

        player_stints = defaultdict(list)
        for pid, tid in stint_rows:
            stints = player_stints[pid]
            t_info = teams_map.get(tid, {"abbrev": str(tid), "name": str(tid)})
            if not stints or stints[-1]["team_id"] != tid:
                stints.append({"team_id": tid, "abbrev": t_info["abbrev"], "name": t_info["name"]})

        agg_query = (
            db.session.query(
                PlayerGameAnalytics.player_id,
                func.count(PlayerGameAnalytics.game_id).label("gp"),
                func.sum(PlayerGameAnalytics.goals).label("goals"),
                func.sum(PlayerGameAnalytics.assists).label("assists"),
                func.sum(PlayerGameAnalytics.points).label("points"),
                func.sum(PlayerGameAnalytics.shots_on_goal).label("shots"),
                func.sum(PlayerGameAnalytics.unblocked_attempts).label("unblocked"),
                func.sum(PlayerGameAnalytics.individual_xg).label("xg"),
                func.sum(PlayerGameAnalytics.toi_seconds).label("toi_seconds"),
                func.sum(PlayerGameAnalytics.toi_5v5_seconds).label("toi_5v5_seconds"),
                func.sum(PlayerGameAnalytics.cf_5v5).label("cf"),
                func.sum(PlayerGameAnalytics.ca_5v5).label("ca"),
                func.sum(PlayerGameAnalytics.ff_5v5).label("ff"),
                func.sum(PlayerGameAnalytics.fa_5v5).label("fa"),
                func.sum(PlayerGameAnalytics.xgf_5v5).label("xgf"),
                func.sum(PlayerGameAnalytics.xga_5v5).label("xga")
            )
            .filter(PlayerGameAnalytics.season == season)
        )
        if team_id is not None:
            agg_query = agg_query.filter(PlayerGameAnalytics.team_id == team_id)

        agg_rows = agg_query.group_by(PlayerGameAnalytics.player_id).all()
        if not agg_rows:
            return []

        pids = [r.player_id for r in agg_rows]
        players_map = {
            p.player_id: p
            for p in db.session.query(Player.player_id, Player.first_name, Player.last_name, Player.position)
            .filter(Player.player_id.in_(pids))
            .all()
        }

        results = []
        for r in agg_rows:
            pid = r.player_id
            player = players_map.get(pid)
            if not player or player.position == 'G':
                continue

            stints = player_stints.get(pid, [])
            if not stints:
                continue

            if team_id is not None:
                rep_team_id = team_id
                rep_team_abbrev = stints[0]["abbrev"]
                rep_team_name = stints[0]["name"]
                stints_list = [rep_team_abbrev]
            else:
                rep_team_abbrev = "/".join(s["abbrev"] for s in stints)
                rep_team_name = " / ".join(s["name"] for s in stints) if len(stints) > 1 else stints[0]["name"]
                rep_team_id = stints[-1]["team_id"]
                stints_list = [s["abbrev"] for s in stints]

            gp = r.gp
            g = r.goals or 0
            a = r.assists or 0
            p = g + a
            sog = r.shots or 0
            unblocked = r.unblocked or 0
            xg = round(float(r.xg or 0.0), 2)
            toi_sec = r.toi_seconds or 0

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

            if include_on_ice_5v5:
                cf = r.cf or 0
                ca = r.ca or 0
                ff = r.ff or 0
                fa = r.fa or 0
                xgf = round(float(r.xgf or 0.0), 2)
                xga = round(float(r.xga or 0.0), 2)
                toi_5v5 = r.toi_5v5_seconds or 0

                tot_c = cf + ca
                cf_pct = round((cf / tot_c * 100), 2) if tot_c > 0 else 50.0

                tot_f = ff + fa
                ff_pct = round((ff / tot_f * 100), 2) if tot_f > 0 else 50.0

                tot_xg = xgf + xga
                on_ice_xg_pct = round((xgf / tot_xg * 100), 2) if tot_xg > 0 else 50.0

                on_ice_5v5_dict = {
                    "cf": cf,
                    "ca": ca,
                    "cf_pct": cf_pct,
                    "ff": ff,
                    "fa": fa,
                    "ff_pct": ff_pct,
                    "on_ice_xgf": xgf,
                    "on_ice_xga": xga,
                    "on_ice_xg_pct": on_ice_xg_pct,
                    "xgf": xgf,
                    "xga": xga,
                    "xg_pct": on_ice_xg_pct,
                    "toi_seconds": toi_5v5,
                    "toi_formatted": format_toi(toi_5v5)
                }
            else:
                on_ice_5v5_dict = {
                    "cf": 0, "ca": 0, "cf_pct": 50.0,
                    "ff": 0, "fa": 0, "ff_pct": 50.0,
                    "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0,
                    "xgf": 0.0, "xga": 0.0, "xg_pct": 50.0,
                    "toi_seconds": 0, "toi_formatted": "00:00"
                }

            full_name = f"{player.first_name} {player.last_name}"

            results.append({
                "player_id": pid,
                "name": full_name,
                "position": player.position,
                "team_id": rep_team_id,
                "team_abbrev": rep_team_abbrev,
                "team": rep_team_abbrev,
                "team_name": rep_team_name,
                "teams": rep_team_abbrev,
                "stints": stints_list,
                "season": season,
                # Individual Counting Stats
                "gp": gp,
                "goals": g,
                "assists": a,
                "points": p,
                "shots": sog,
                "shots_on_goal": sog,
                "unblocked_attempts": unblocked,
                "xg": xg,
                "goals_above_expected": g_minus_xg,
                "goals_minus_xg": g_minus_xg,
                "g_minus_xg": g_minus_xg,
                # Individual Rates
                "goals_per_60": goals_per_60,
                "xg_per_60": xg_per_60,
                "shooting_pct": shooting_pct,
                "expected_conversion_pct": exp_conv_pct,
                "shooting_vs_expected_diff": sh_diff,
                "toi_seconds": toi_sec,
                "toi_formatted": format_toi(toi_sec),
                # 5v5 On-Ice Metrics
                "on_ice_5v5": on_ice_5v5_dict
            })

        results.sort(key=lambda x: -x["points"])
        return results

    @classmethod
    def _get_season_skaters_summary_legacy(
        cls,
        season: str,
        team_id: Optional[int] = None,
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0,
        include_on_ice_5v5: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Aggregates season statistics for all skaters using grouped SQL queries to prevent N+1 overhead.
        When team_id is specified, stats are scoped strictly to games where the player represented that team.
        When team_id is None, full-season statistics are aggregated across all team stints, with chronological
        multi-team representation (e.g. CGY/VAN or CGY/VAN/CGY).
        """
        # 1. Fetch all games for this season ordered by date
        game_query = (
            db.session.query(Game.game_id, Game.game_date)
            .filter(Game.season == season)
        )
        if team_id is not None:
            game_query = game_query.filter(
                or_(Game.home_team_id == team_id, Game.away_team_id == team_id)
            )
        game_query = game_query.order_by(Game.game_date.asc(), Game.game_id.asc())
        season_game_rows = game_query.all()
        if not season_game_rows:
            return []
        season_game_ids = [r[0] for r in season_game_rows]

        # 2. Get GP, player info, and team association from GamePlayer in chronological game order
        gp_query = (
            db.session.query(
                GamePlayer.player_id,
                GamePlayer.game_id,
                GamePlayer.team_id,
                Player.first_name,
                Player.last_name,
                Player.position,
                Team.abbreviation.label('team_abbrev'),
                Team.name.label('team_name'),
                Game.game_date
            )
            .join(Player, GamePlayer.player_id == Player.player_id)
            .join(Team, GamePlayer.team_id == Team.team_id)
            .join(Game, GamePlayer.game_id == Game.game_id)
            .filter(
                GamePlayer.game_id.in_(season_game_ids),
                Player.position != 'G'
            )
            .order_by(Game.game_date.asc(), Game.game_id.asc())
        )
        if team_id is not None:
            gp_query = gp_query.filter(GamePlayer.team_id == team_id)

        gp_rows = gp_query.all()
        if not gp_rows:
            return []

        # Group appearances by player_id preserving chronological game order
        player_appearances = defaultdict(list)
        player_basic_info = {}
        for r in gp_rows:
            pid = r.player_id
            player_appearances[pid].append(r)
            if pid not in player_basic_info:
                player_basic_info[pid] = {
                    "player_id": pid,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "full_name": f"{r.first_name} {r.last_name}",
                    "position": r.position
                }

        skater_meta = {}
        for pid, appearances in player_appearances.items():
            info = player_basic_info[pid]
            distinct_game_ids = set(r.game_id for r in appearances)
            gp_count = len(distinct_game_ids)

            if team_id is not None:
                rep_team_id = team_id
                rep_team_abbrev = appearances[0].team_abbrev
                rep_team_name = appearances[0].team_name
                stints_list = [rep_team_abbrev]
            else:
                # Chronological stint sequence (compressing consecutive appearances for the same team)
                stints = []
                for r in appearances:
                    if not stints or stints[-1]["team_id"] != r.team_id:
                        stints.append({
                            "team_id": r.team_id,
                            "team_abbrev": r.team_abbrev,
                            "team_name": r.team_name
                        })
                rep_team_abbrev = "/".join(s["team_abbrev"] for s in stints)
                rep_team_name = " / ".join(s["team_name"] for s in stints) if len(stints) > 1 else stints[0]["team_name"]
                rep_team_id = stints[-1]["team_id"]
                stints_list = [s["team_abbrev"] for s in stints]

            skater_meta[pid] = {
                **info,
                "team_id": rep_team_id,
                "team_abbrev": rep_team_abbrev,
                "team_name": rep_team_name,
                "teams": rep_team_abbrev,
                "stints": stints_list,
                "gp": gp_count
            }

        relevant_pids = list(skater_meta.keys())

        # 3. Individual Goals (primary_player_id on goal events)
        goals_query = (
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
        )
        if team_id is not None:
            goals_query = goals_query.filter(Event.team_id == team_id)
        goals_rows = goals_query.group_by(Event.primary_player_id).all()
        goals_map = {pid: count for pid, count in goals_rows}

        # 4. Individual Assists (assist1 or assist2)
        a1_query = (
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
        )
        a2_query = (
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
        )
        if team_id is not None:
            a1_query = a1_query.filter(Event.team_id == team_id)
            a2_query = a2_query.filter(Event.team_id == team_id)
        a1_rows = a1_query.group_by(Event.assist1_player_id).all()
        a2_rows = a2_query.group_by(Event.assist2_player_id).all()

        assists_map = {}
        for pid, count in a1_rows:
            assists_map[pid] = assists_map.get(pid, 0) + count
        for pid, count in a2_rows:
            assists_map[pid] = assists_map.get(pid, 0) + count

        # 5. SOG, Unblocked Attempts, and Individual xG
        sog_query = (
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
        )
        if team_id is not None:
            sog_query = sog_query.filter(Shot.team_id == team_id)
        sog_rows = sog_query.group_by(Shot.shooter_id).all()
        sog_map = {pid: count for pid, count in sog_rows}

        unblocked_query = (
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
        )
        if team_id is not None:
            unblocked_query = unblocked_query.filter(Shot.team_id == team_id)
        unblocked_rows = unblocked_query.group_by(Shot.shooter_id).all()
        unblocked_map = {pid: count for pid, count, _ in unblocked_rows}
        xg_map = {pid: (round(float(sum_xg), 2) if sum_xg is not None else 0.0) for pid, _, sum_xg in unblocked_rows}

        # 6. Time on Ice (TOI) across the season
        toi_query = (
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
        )
        if team_id is not None:
            toi_query = toi_query.filter(Shift.team_id == team_id)
        toi_rows = toi_query.group_by(Shift.player_id).all()
        toi_map = {pid: (int(tot_sec) if tot_sec else 0) for pid, tot_sec in toi_rows}

        # 7. 5v5 On-Ice possession and xG metrics.
        # League overview leader cards do not use these fields, so callers can skip the
        # expensive shift/event reconstruction entirely.
        if include_on_ice_5v5:
            on_ice_5v5 = cls._aggregate_season_5v5_on_ice(
                season_game_ids,
                relevant_pids,
                target_team_id=team_id,
            )
        else:
            on_ice_5v5 = {}

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
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0,
                "toi_seconds": 0
            })

            results.append({
                "player_id": pid,
                "name": meta["full_name"],
                "position": meta["position"],
                "team_id": meta["team_id"],
                "team_abbrev": meta["team_abbrev"],
                "team": meta["team_abbrev"],
                "team_name": meta["team_name"],
                "teams": meta["teams"],
                "stints": meta.get("stints", [meta["team_abbrev"]]),
                "season": season,
                # Individual Counting Stats
                "gp": gp,
                "goals": g,
                "assists": a,
                "points": p,
                "shots": sog,
                "shots_on_goal": sog,
                "unblocked_attempts": unblocked,
                "xg": xg,
                "goals_above_expected": g_minus_xg,
                "goals_minus_xg": g_minus_xg,
                "g_minus_xg": g_minus_xg,
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
                    "on_ice_xg_pct": oi["on_ice_xg_pct"],
                    "xgf": oi["on_ice_xgf"],
                    "xga": oi["on_ice_xga"],
                    "xg_pct": oi["on_ice_xg_pct"],
                    "toi_seconds": oi.get("toi_seconds", 0),
                    "toi_formatted": format_toi(oi.get("toi_seconds", 0))
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
        limit: int = 50,
        team_id: Optional[int] = None,
        precomputed_skaters: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generates configurable skater analytical leaderboards.
        Supports bounded SQL query over PlayerGameAnalytics when derived coverage is complete.
        Valid sort_by keys: 'points', 'goals', 'assists', 'xg', 'goals_above_expected',
        'xg_per_60', 'goals_per_60', 'shooting_pct', 'expected_conversion_pct',
        'cf_pct', 'ff_pct', 'on_ice_xg_pct'.
        """
        if precomputed_skaters is not None:
            skaters = [
                s.copy() for s in precomputed_skaters
                if s.get("gp", 0) >= min_gp
                and s.get("toi_seconds", 0) >= min_toi_seconds
                and s.get("unblocked_attempts", 0) >= min_unblocked_attempts
                and (team_id is None or s.get("team_id") == team_id)
            ]
            def get_sort_val(skater: dict) -> float:
                if sort_by in ['cf_pct', 'ff_pct', 'on_ice_xg_pct']:
                    return skater.get('on_ice_5v5', {}).get(sort_by, 0.0) or 0.0
                return skater.get(sort_by, 0.0) or 0.0

            skaters.sort(key=get_sort_val, reverse=True)

            for rank_idx, skater in enumerate(skaters, 1):
                skater["rank"] = rank_idx

            return skaters[:limit]

        if PlayerGameAnalyticsAuditService.is_derived_coverage_complete(season):
            return cls._get_skater_leaderboards_derived(
                season=season,
                sort_by=sort_by,
                min_gp=min_gp,
                min_toi_seconds=min_toi_seconds,
                min_unblocked_attempts=min_unblocked_attempts,
                limit=limit,
                team_id=team_id
            )

        skaters = cls._get_season_skaters_summary_legacy(
            season=season,
            team_id=team_id,
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
    def _get_skater_leaderboards_derived(
        cls,
        season: str,
        sort_by: str = "points",
        min_gp: int = 1,
        min_toi_seconds: int = 0,
        min_unblocked_attempts: int = 0,
        limit: int = 50,
        team_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Direct bounded SQL leaderboard query over PlayerGameAnalytics.
        Aggregates, filters, orders, and LIMITs directly in SQL, then decorates Top N players.
        """
        sum_gp = func.count(PlayerGameAnalytics.game_id)
        sum_goals = func.sum(PlayerGameAnalytics.goals)
        sum_assists = func.sum(PlayerGameAnalytics.assists)
        sum_points = func.sum(PlayerGameAnalytics.points)
        sum_shots = func.sum(PlayerGameAnalytics.shots_on_goal)
        sum_unblocked = func.sum(PlayerGameAnalytics.unblocked_attempts)
        sum_xg = func.sum(PlayerGameAnalytics.individual_xg)
        sum_toi = func.sum(PlayerGameAnalytics.toi_seconds)
        sum_toi_5v5 = func.sum(PlayerGameAnalytics.toi_5v5_seconds)
        sum_cf = func.sum(PlayerGameAnalytics.cf_5v5)
        sum_ca = func.sum(PlayerGameAnalytics.ca_5v5)
        sum_ff = func.sum(PlayerGameAnalytics.ff_5v5)
        sum_fa = func.sum(PlayerGameAnalytics.fa_5v5)
        sum_xgf = func.sum(PlayerGameAnalytics.xgf_5v5)
        sum_xga = func.sum(PlayerGameAnalytics.xga_5v5)

        round_sum_xg = func.round(sum_xg, 2)
        round_sum_xgf = func.round(sum_xgf, 2)
        round_sum_xga = func.round(sum_xga, 2)

        if sort_by == 'goals':
            sort_expr = sum_goals
        elif sort_by == 'assists':
            sort_expr = sum_assists
        elif sort_by == 'xg':
            sort_expr = round_sum_xg
        elif sort_by in ['goals_above_expected', 'goals_minus_xg', 'g_minus_xg']:
            sort_expr = func.round(sum_goals - round_sum_xg, 2)
        elif sort_by in ['shots', 'shots_on_goal']:
            sort_expr = sum_shots
        elif sort_by == 'unblocked_attempts':
            sort_expr = sum_unblocked
        elif sort_by == 'toi_seconds':
            sort_expr = sum_toi
        elif sort_by == 'goals_per_60':
            sort_expr = func.round(func.coalesce(sum_goals * 3600.0 / func.nullif(sum_toi, 0), 0.0), 2)
        elif sort_by == 'xg_per_60':
            sort_expr = func.round(func.coalesce(round_sum_xg * 3600.0 / func.nullif(sum_toi, 0), 0.0), 2)
        elif sort_by == 'shooting_pct':
            sort_expr = func.round(func.coalesce(sum_goals * 100.0 / func.nullif(sum_shots, 0), 0.0), 2)
        elif sort_by in ['expected_conversion_pct', 'exp_conv_pct']:
            sort_expr = func.round(func.coalesce(round_sum_xg * 100.0 / func.nullif(sum_unblocked, 0), 0.0), 2)
        elif sort_by == 'cf_pct':
            sort_expr = func.round(func.coalesce(sum_cf * 100.0 / func.nullif(sum_cf + sum_ca, 0), 50.0), 2)
        elif sort_by == 'ff_pct':
            sort_expr = func.round(func.coalesce(sum_ff * 100.0 / func.nullif(sum_ff + sum_fa, 0), 50.0), 2)
        elif sort_by in ['on_ice_xg_pct', 'xg_pct']:
            sort_expr = func.round(func.coalesce(round_sum_xgf * 100.0 / func.nullif(round_sum_xgf + round_sum_xga, 0), 50.0), 2)
        else:
            sort_expr = sum_points

        query = (
            db.session.query(
                PlayerGameAnalytics.player_id,
                sum_gp.label("gp"),
                sum_goals.label("goals"),
                sum_assists.label("assists"),
                sum_points.label("points"),
                sum_shots.label("shots"),
                sum_unblocked.label("unblocked"),
                sum_xg.label("xg"),
                sum_toi.label("toi_seconds"),
                sum_toi_5v5.label("toi_5v5_seconds"),
                sum_cf.label("cf"),
                sum_ca.label("ca"),
                sum_ff.label("ff"),
                sum_fa.label("fa"),
                sum_xgf.label("xgf"),
                sum_xga.label("xga")
            )
            .filter(PlayerGameAnalytics.season == season)
        )
        if team_id is not None:
            query = query.filter(PlayerGameAnalytics.team_id == team_id)

        query = query.group_by(PlayerGameAnalytics.player_id)

        # Apply HAVING filters for min sample thresholds
        if min_gp > 1:
            query = query.having(sum_gp >= min_gp)
        if min_toi_seconds > 0:
            query = query.having(sum_toi >= min_toi_seconds)
        if min_unblocked_attempts > 0:
            query = query.having(sum_unblocked >= min_unblocked_attempts)

        query = query.order_by(sort_expr.desc(), sum_points.desc(), sum_goals.desc(), PlayerGameAnalytics.player_id.asc())

        if limit and limit > 0:
            query = query.limit(limit)

        top_rows = query.all()
        if not top_rows:
            return []

        # Step 2 of bounded leaderboard: fetch Player info and team/stint metadata ONLY for the Top N players
        top_pids = [r.player_id for r in top_rows]
        
        player_info_rows = (
            db.session.query(
                Player.player_id,
                Player.first_name,
                Player.last_name,
                Player.position
            )
            .filter(Player.player_id.in_(top_pids))
            .all()
        )
        player_info_map = {p.player_id: p for p in player_info_rows}

        teams_map = {
            t.team_id: {"abbrev": t.abbreviation, "name": t.name}
            for t in db.session.query(Team.team_id, Team.abbreviation, Team.name).all()
        }

        stint_query = (
            db.session.query(
                PlayerGameAnalytics.player_id,
                PlayerGameAnalytics.team_id
            )
            .filter(
                PlayerGameAnalytics.season == season,
                PlayerGameAnalytics.player_id.in_(top_pids)
            )
            .order_by(PlayerGameAnalytics.game_id.asc())
        )
        if team_id is not None:
            stint_query = stint_query.filter(PlayerGameAnalytics.team_id == team_id)

        stint_rows = stint_query.all()
        player_stints = defaultdict(list)
        for pid, tid in stint_rows:
            stints = player_stints[pid]
            t_info = teams_map.get(tid, {"abbrev": str(tid), "name": str(tid)})
            if not stints or stints[-1]["team_id"] != tid:
                stints.append({"team_id": tid, "abbrev": t_info["abbrev"], "name": t_info["name"]})

        results = []
        for rank_idx, r in enumerate(top_rows, 1):
            pid = r.player_id
            p_info = player_info_map.get(pid)
            first_name = p_info.first_name if p_info else ""
            last_name = p_info.last_name if p_info else ""
            position = p_info.position if p_info else "UNK"

            stints = player_stints.get(pid, [])
            if not stints:
                rep_team_abbrev = "UNK"
                rep_team_name = "Unknown"
                rep_team_id = 0
                stints_list = ["UNK"]
            elif team_id is not None:
                rep_team_id = team_id
                rep_team_abbrev = stints[0]["abbrev"]
                rep_team_name = stints[0]["name"]
                stints_list = [rep_team_abbrev]
            else:
                rep_team_abbrev = "/".join(s["abbrev"] for s in stints)
                rep_team_name = " / ".join(s["name"] for s in stints) if len(stints) > 1 else stints[0]["name"]
                rep_team_id = stints[-1]["team_id"]
                stints_list = [s["abbrev"] for s in stints]

            gp = r.gp
            g = r.goals or 0
            a = r.assists or 0
            p = g + a
            sog = r.shots or 0
            unblocked = r.unblocked or 0
            xg = round(float(r.xg or 0.0), 2)
            toi_sec = r.toi_seconds or 0

            toi_hours = toi_sec / 3600.0 if toi_sec > 0 else 0.0
            goals_per_60 = round(g / toi_hours, 2) if toi_hours > 0 else 0.0
            xg_per_60 = round(xg / toi_hours, 2) if toi_hours > 0 else 0.0
            g_minus_xg = round(g - xg, 2)

            shooting_pct = round((g / sog * 100), 2) if sog > 0 else 0.0
            exp_conv_pct = round((xg / unblocked * 100), 2) if unblocked > 0 else 0.0
            sh_diff = round(shooting_pct - exp_conv_pct, 2)

            cf = r.cf or 0
            ca = r.ca or 0
            ff = r.ff or 0
            fa = r.fa or 0
            xgf = round(float(r.xgf or 0.0), 2)
            xga = round(float(r.xga or 0.0), 2)
            toi_5v5 = r.toi_5v5_seconds or 0

            tot_c = cf + ca
            cf_pct = round((cf / tot_c * 100), 2) if tot_c > 0 else 50.0

            tot_f = ff + fa
            ff_pct = round((ff / tot_f * 100), 2) if tot_f > 0 else 50.0

            tot_xg = xgf + xga
            on_ice_xg_pct = round((xgf / tot_xg * 100), 2) if tot_xg > 0 else 50.0

            full_name = f"{first_name} {last_name}".strip()

            results.append({
                "rank": rank_idx,
                "player_id": pid,
                "name": full_name,
                "position": position,
                "team_id": rep_team_id,
                "team_abbrev": rep_team_abbrev,
                "team": rep_team_abbrev,
                "team_name": rep_team_name,
                "teams": rep_team_abbrev,
                "stints": stints_list,
                "season": season,
                "gp": gp,
                "goals": g,
                "assists": a,
                "points": p,
                "shots": sog,
                "shots_on_goal": sog,
                "unblocked_attempts": unblocked,
                "xg": xg,
                "goals_above_expected": g_minus_xg,
                "goals_minus_xg": g_minus_xg,
                "g_minus_xg": g_minus_xg,
                "goals_per_60": goals_per_60,
                "xg_per_60": xg_per_60,
                "shooting_pct": shooting_pct,
                "expected_conversion_pct": exp_conv_pct,
                "shooting_vs_expected_diff": sh_diff,
                "toi_seconds": toi_sec,
                "toi_formatted": format_toi(toi_sec),
                "on_ice_5v5": {
                    "cf": cf,
                    "ca": ca,
                    "cf_pct": cf_pct,
                    "ff": ff,
                    "fa": fa,
                    "ff_pct": ff_pct,
                    "on_ice_xgf": xgf,
                    "on_ice_xga": xga,
                    "on_ice_xg_pct": on_ice_xg_pct,
                    "xgf": xgf,
                    "xga": xga,
                    "xg_pct": on_ice_xg_pct,
                    "toi_seconds": toi_5v5,
                    "toi_formatted": format_toi(toi_5v5)
                }
            })

        return results

    @classmethod
    def _aggregate_season_5v5_on_ice(
        cls,
        season_game_ids: List[int],
        skater_ids: List[int],
        target_team_id: Optional[int] = None
    ) -> Dict[int, Dict[str, Any]]:
        """
        Computes 5v5 on-ice possession (Corsi, Fenwick) and on-ice xG metrics for skaters.
        Uses bounded season queries and in-memory game groupings to prevent N+1 query overhead.
        Accumulates true on_ice_xgf and on_ice_xga from Shot records.
        """
        skater_set = set(skater_ids)
        on_ice_res = {
            pid: {
                "cf": 0, "ca": 0, "cf_pct": 50.0,
                "ff": 0, "fa": 0, "ff_pct": 50.0,
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0,
                "toi_seconds": 0
            }
            for pid in skater_ids
        }

        # 1. Bulk query game home & away team mapping
        game_rows = db.session.query(Game.game_id, Game.home_team_id, Game.away_team_id).filter(Game.game_id.in_(season_game_ids)).all()
        game_teams_map = {gid: (h_id, a_id) for gid, h_id, a_id in game_rows}

        # 2. Bulk query shifts with player position pre-fetched
        shifts = (
            Shift.query.filter(
                Shift.game_id.in_(season_game_ids),
                Shift.is_anomaly == False,
                Shift.duration > 0,
                Shift.start_elapsed_seconds.isnot(None),
                Shift.end_elapsed_seconds.isnot(None)
            ).all()
        )
        if not shifts:
            return on_ice_res

        shift_pids = list(set(s.player_id for s in shifts))
        players_pos = dict(
            db.session.query(Player.player_id, Player.position)
            .filter(Player.player_id.in_(shift_pids))
            .all()
        )

        shifts_by_game = defaultdict(list)
        for s in shifts:
            shifts_by_game[s.game_id].append(s)

        # 3. Bulk query 5v5 shot events with outer joined Shot.xg
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events_with_shots = (
            db.session.query(Event, Shot.xg)
            .outerjoin(Shot, Event.event_id == Shot.shot_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Event.event_type.in_(shot_event_types),
                or_(Event.period_type != 'SO', Event.period_type.is_(None)),
                Event.elapsed_game_seconds.isnot(None)
            )
            .all()
        )
        events_by_game = defaultdict(list)
        for event, xg in events_with_shots:
            events_by_game[event.game_id].append((event, xg))

        # 4. In-memory processing by game using shift-boundary intervals rather
        # than per-second timelines or event x shift nested loops.
        for gid in season_game_ids:
            teams = game_teams_map.get(gid)
            if not teams:
                continue
            home_team_id, away_team_id = teams
            game_shifts = shifts_by_game.get(gid, [])
            if not game_shifts:
                continue

            max_time = max(
                3600,
                max((s.end_elapsed_seconds or 0) for s in game_shifts)
            )
            intervals = OnIceService.build_active_player_intervals(
                game_shifts, max_time, home_team_id
            )
            if not intervals:
                continue

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

                if target_team_id is None or home_team_id == target_team_id:
                    for p in hp:
                        if p in skater_set and players_pos.get(p) != "G":
                            on_ice_res[p]["toi_seconds"] += duration
                if target_team_id is None or away_team_id == target_team_id:
                    for p in ap:
                        if p in skater_set and players_pos.get(p) != "G":
                            on_ice_res[p]["toi_seconds"] += duration

            # Preserve the historical metric contract:
            # - TOI is counted only when the reconstructed lineup is true 5v5.
            # - Event attribution uses the event's authoritative 5v5 strength flag plus
            #   the player's active shift, even if other shift records are incomplete.
            starts = [interval["start"] for interval in intervals]
            game_events = sorted(
                events_by_game.get(gid, []),
                key=lambda item: item[0].elapsed_game_seconds
                if item[0].elapsed_game_seconds is not None else -1,
            )

            for event, xg in game_events:
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
                    if target_team_id is not None and side_team_id != target_team_id:
                        continue

                    is_for = (side_team_id == shot_team_id)
                    for pid in active_players:
                        if pid not in skater_set or players_pos.get(pid) == "G":
                            continue

                        if is_for:
                            on_ice_res[pid]["cf"] += 1
                            if not is_blocked:
                                on_ice_res[pid]["ff"] += 1
                                on_ice_res[pid]["on_ice_xgf"] += shot_xg
                        else:
                            on_ice_res[pid]["ca"] += 1
                            if not is_blocked:
                                on_ice_res[pid]["fa"] += 1
                                on_ice_res[pid]["on_ice_xga"] += shot_xg

        # 5. Compute percentages and finalize metrics
        for pid, stats in on_ice_res.items():
            tot_c = stats["cf"] + stats["ca"]
            tot_f = stats["ff"] + stats["fa"]
            stats["cf_pct"] = round((stats["cf"] / tot_c * 100), 2) if tot_c > 0 else 50.0
            stats["ff_pct"] = round((stats["ff"] / tot_f * 100), 2) if tot_f > 0 else 50.0
            xgf = round(stats["on_ice_xgf"], 2)
            xga = round(stats["on_ice_xga"], 2)
            stats["on_ice_xgf"] = xgf
            stats["on_ice_xga"] = xga
            tot_xg = xgf + xga
            # Crucial requirement: Never default real skaters with attempts to 50.0%.
            # Neutral 50.0% only when denominator is zero.
            if tot_xg > 0:
                stats["on_ice_xg_pct"] = round((xgf / tot_xg * 100), 2)
            else:
                stats["on_ice_xg_pct"] = 50.0

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
            "teams": player.current_team.abbreviation if player.current_team else "UNK",
            "stints": [player.current_team.abbreviation] if player.current_team else ["UNK"],
            "season": season,
            "gp": 0,
            "goals": 0,
            "assists": 0,
            "points": 0,
            "shots_on_goal": 0,
            "unblocked_attempts": 0,
            "unblocked_shot_attempts": 0,
            "xg": 0.0,
            "goals_above_expected": 0.0,
            "goals_minus_xg": 0.0,
            "g_minus_xg": 0.0,
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
                "on_ice_xgf": 0.0, "on_ice_xga": 0.0, "on_ice_xg_pct": 50.0,
                "xgf": 0.0, "xga": 0.0, "xg_pct": 50.0,
                "toi_seconds": 0, "toi_formatted": "00:00"
            }
        }
