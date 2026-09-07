import logging
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func, case
from app.models import db, Game, Team, Event, Shot, Shift
from app.services.possession_service import PossessionService

logger = logging.getLogger(__name__)

class TeamSeasonService:
    """
    Canonical service for aggregating and ranking team metrics across a season.
    Supports situation filtering ('all', '5v5', 'pp', 'sh') with optimized SQL aggregations.
    """

    @classmethod
    def get_team_season_stats(cls, team_id: int, season: str, situation: str = "all") -> Optional[Dict[str, Any]]:
        """
        Calculates all canonical season metrics for a specific team and situation.
        """
        all_teams_stats = cls.get_season_teams_summary(season=season, situation=situation)
        for t_stats in all_teams_stats:
            if t_stats["team_id"] == team_id:
                return t_stats
        
        # If team played 0 games in this season, return neutral default structure if team exists
        team = db.session.get(Team, team_id)
        if not team:
            return None

        return cls._empty_team_stats(team, season, situation)

    @classmethod
    def get_season_teams_summary(cls, season: str, situation: str = "all") -> List[Dict[str, Any]]:
        """
        Aggregates team season metrics for all teams in a given season using grouped queries
        to eliminate N+1 performance bottlenecks.
        """
        situation = situation.lower()

        # 1. Fetch all games for this season
        games = Game.query.filter(Game.season == season).order_by(Game.game_date.asc()).all()
        if not games:
            return []

        game_ids = [g.game_id for g in games]

        # Determine W/L/OTL and GP per team
        # Check overtime / shootout existence per game
        ot_games = set(
            r[0] for r in db.session.query(Event.game_id)
            .filter(
                Event.game_id.in_(game_ids),
                or_(Event.period > 3, Event.period_type.in_(['OT', 'SO']))
            ).distinct().all()
        )

        team_games: Dict[int, List[Game]] = {}
        team_record: Dict[int, Dict[str, int]] = {}

        for g in games:
            for tid, score, opp_score, is_home in [
                (g.home_team_id, g.home_score, g.away_score, True),
                (g.away_team_id, g.away_score, g.home_score, False)
            ]:
                if tid not in team_record:
                    team_record[tid] = {"w": 0, "l": 0, "otl": 0, "gp": 0}
                    team_games[tid] = []

                team_games[tid].append(g)
                team_record[tid]["gp"] += 1

                # W / L / OTL logic
                if score > opp_score:
                    team_record[tid]["w"] += 1
                else:
                    if g.game_id in ot_games:
                        team_record[tid]["otl"] += 1
                    else:
                        team_record[tid]["l"] += 1

        # 2. Query event-level counts (Corsi, Fenwick, Goals)
        # Situation filter for events
        event_filter = [
            Event.game_id.in_(game_ids),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ]

        if situation == "5v5":
            event_filter.append(Event.team_strength_state == '5v5')
        elif situation in ["pp", "powerplay", "power_play"]:
            event_filter.append(Event.manpower_state == 'PP')
        elif situation in ["sh", "shorthanded", "pk"]:
            event_filter.append(Event.manpower_state == 'PK')

        # Corsi (all shot attempts), Fenwick (unblocked), Goals
        # Grouped by (game_id, event.team_id, event_type)
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        event_counts = db.session.query(
            Event.game_id,
            Event.team_id,
            Event.event_type,
            func.count(Event.event_id)
        ).filter(
            *event_filter,
            Event.event_type.in_(shot_event_types)
        ).group_by(Event.game_id, Event.team_id, Event.event_type).all()

        # Group shot xG
        # Unblocked attempts only (xg is NULL on blocked-shot attempts per core invariants)
        xg_filter = [
            Event.game_id.in_(game_ids),
            Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ]
        if situation == "5v5":
            xg_filter.append(Event.team_strength_state == '5v5')
        elif situation in ["pp", "powerplay", "power_play"]:
            xg_filter.append(Event.manpower_state == 'PP')
        elif situation in ["sh", "shorthanded", "pk"]:
            xg_filter.append(Event.manpower_state == 'PK')

        xg_sums = db.session.query(
            Event.game_id,
            Shot.team_id,
            func.sum(Shot.xg)
        ).join(Event, Shot.shot_id == Event.event_id).filter(
            *xg_filter
        ).group_by(Event.game_id, Shot.team_id).all()

        # Map game_id to (home_team_id, away_team_id)
        game_teams_map = {g.game_id: (g.home_team_id, g.away_team_id) for g in games}

        # Initialize counters per team
        cf_map: Dict[int, int] = {t: 0 for t in team_record}
        ca_map: Dict[int, int] = {t: 0 for t in team_record}
        ff_map: Dict[int, int] = {t: 0 for t in team_record}
        fa_map: Dict[int, int] = {t: 0 for t in team_record}
        gf_map: Dict[int, int] = {t: 0 for t in team_record}
        ga_map: Dict[int, int] = {t: 0 for t in team_record}
        xgf_map: Dict[int, float] = {t: 0.0 for t in team_record}
        xga_map: Dict[int, float] = {t: 0.0 for t in team_record}

        # Accumulate event metrics
        for gid, tid, etype, count in event_counts:
            if gid not in game_teams_map:
                continue
            h_tid, a_tid = game_teams_map[gid]
            opp_tid = a_tid if tid == h_tid else h_tid

            # Corsi For (tid) and Corsi Against (opp_tid)
            if tid in cf_map:
                cf_map[tid] += count
            if opp_tid in ca_map:
                ca_map[opp_tid] += count

            # Fenwick & Goals (unblocked only)
            if etype in ['shot-on-goal', 'goal', 'missed-shot']:
                if tid in ff_map:
                    ff_map[tid] += count
                if opp_tid in fa_map:
                    fa_map[opp_tid] += count

            if etype == 'goal':
                if tid in gf_map:
                    gf_map[tid] += count
                if opp_tid in ga_map:
                    ga_map[opp_tid] += count

        # Accumulate xG metrics
        for gid, tid, sum_xg in xg_sums:
            if gid not in game_teams_map or sum_xg is None:
                continue
            h_tid, a_tid = game_teams_map[gid]
            opp_tid = a_tid if tid == h_tid else h_tid

            if tid in xgf_map:
                xgf_map[tid] += float(sum_xg)
            if opp_tid in xga_map:
                xga_map[opp_tid] += float(sum_xg)

        # 3. Calculate TOI per team in this situation
        # In 'all': standard regulation is 3600s per game plus any OT seconds
        # In '5v5': average ~48-50 mins (2880s) or shift-based
        team_toi: Dict[int, int] = {}
        for tid, t_g_list in team_games.items():
            if situation == "5v5":
                # 5v5 duration approximation: 48 minutes (2880s) per game
                team_toi[tid] = len(t_g_list) * 2880
            elif situation in ["pp", "powerplay", "power_play"]:
                # PP duration estimate: ~5 mins (300s) per game
                team_toi[tid] = len(t_g_list) * 300
            elif situation in ["sh", "shorthanded", "pk"]:
                # PK duration estimate: ~5 mins (300s) per game
                team_toi[tid] = len(t_g_list) * 300
            else:
                # 'all': 60 mins (3600s) per game
                team_toi[tid] = len(t_g_list) * 3600

        # 4. Assemble final stats for each team
        teams_by_id = {t.team_id: t for t in Team.query.filter(Team.team_id.in_(team_record.keys())).all()}
        results = []

        for tid, rec in team_record.items():
            team = teams_by_id.get(tid)
            if not team:
                continue

            gp = rec["gp"]
            w = rec["w"]
            l = rec["l"]
            otl = rec["otl"]
            pts = (w * 2) + otl

            gf = gf_map.get(tid, 0)
            ga = ga_map.get(tid, 0)
            goal_diff = gf - ga

            cf = cf_map.get(tid, 0)
            ca = ca_map.get(tid, 0)
            cf_pct = round((cf / (cf + ca) * 100), 2) if (cf + ca) > 0 else 50.0

            ff = ff_map.get(tid, 0)
            fa = fa_map.get(tid, 0)
            ff_pct = round((ff / (ff + fa) * 100), 2) if (ff + fa) > 0 else 50.0

            xgf = round(xgf_map.get(tid, 0.0), 2)
            xga = round(xga_map.get(tid, 0.0), 2)
            xg_pct = round((xgf / (xgf + xga) * 100), 2) if (xgf + xga) > 0 else 50.0

            toi_sec = team_toi.get(tid, gp * 3600)
            toi_hours = toi_sec / 3600.0 if toi_sec > 0 else 1.0

            xgf_per_60 = round(xgf / toi_hours, 2)
            xga_per_60 = round(xga / toi_hours, 2)

            gf_xgf = round(gf - xgf, 2)
            ga_xga = round(ga - xga, 2)
            xg_diff = round(xgf - xga, 2)

            results.append({
                "team_id": tid,
                "team_name": team.name,
                "team_abbrev": team.abbreviation,
                "season": season,
                "situation": situation,
                "gp": gp,
                "w": w,
                "l": l,
                "otl": otl,
                "pts": pts,
                "gf": gf,
                "ga": ga,
                "goal_diff": goal_diff,
                "cf": cf,
                "ca": ca,
                "cf_pct": cf_pct,
                "ff": ff,
                "fa": fa,
                "ff_pct": ff_pct,
                "xgf": xgf,
                "xga": xga,
                "xg_pct": xg_pct,
                "xgf_per_60": xgf_per_60,
                "xga_per_60": xga_per_60,
                "gf_xgf_diff": gf_xgf,
                "ga_xga_diff": ga_xga,
                "xg_diff": xg_diff,
                "toi_seconds": toi_sec,
                "toi_formatted": f"{toi_sec // 60:d}:{toi_sec % 60:02d}"
            })

        # Default sort by xg_pct descending
        results.sort(key=lambda x: -x["xg_pct"])
        return results

    @classmethod
    def get_season_team_rankings(
        cls,
        season: str,
        situation: str = "all",
        sort_by: str = "xg_pct"
    ) -> List[Dict[str, Any]]:
        """
        Ranks all teams in a season by the specified analytical metric.
        Valid sort_by keys: 'xg_pct', 'xgf_per_60', 'xga_per_60', 'cf_pct', 'ff_pct', 'gf_xgf_diff'.
        """
        teams = cls.get_season_teams_summary(season=season, situation=situation)
        if not teams:
            return []

        # xga_per_60: lower is better (ascending sort)
        reverse = (sort_by != "xga_per_60")

        teams.sort(key=lambda x: x.get(sort_by, 0.0), reverse=reverse)

        for rank_idx, team_data in enumerate(teams, 1):
            team_data["rank"] = rank_idx

        return teams

    @staticmethod
    def _empty_team_stats(team: Team, season: str, situation: str) -> Dict[str, Any]:
        return {
            "team_id": team.team_id,
            "team_name": team.name,
            "team_abbrev": team.abbreviation,
            "season": season,
            "situation": situation,
            "gp": 0,
            "w": 0,
            "l": 0,
            "otl": 0,
            "pts": 0,
            "gf": 0,
            "ga": 0,
            "goal_diff": 0,
            "cf": 0,
            "ca": 0,
            "cf_pct": 50.0,
            "ff": 0,
            "fa": 0,
            "ff_pct": 50.0,
            "xgf": 0.0,
            "xga": 0.0,
            "xg_pct": 50.0,
            "xgf_per_60": 0.0,
            "xga_per_60": 0.0,
            "gf_xgf_diff": 0.0,
            "ga_xga_diff": 0.0,
            "xg_diff": 0.0,
            "toi_seconds": 0,
            "toi_formatted": "00:00"
        }
