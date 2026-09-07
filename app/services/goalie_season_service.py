import logging
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func, distinct
from app.models import db, Game, Player, Event, Shot, Shift, GamePlayer, Team
from app.utils.time_helpers import format_toi

logger = logging.getLogger(__name__)

class GoalieSeasonService:
    """
    Canonical service for aggregating goalie season statistics, expected goals against (xGA),
    goals saved above expected (GSAx), and leaderboards with configurable sample thresholds.
    """

    @classmethod
    def get_goalie_season_stats(cls, goalie_id: int, season: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves season statistics for a single goalie.
        """
        all_goalies = cls.get_season_goalies_summary(season=season, min_gp=0, min_shots_faced=0, min_toi_seconds=0)
        for goalie in all_goalies:
            if goalie["player_id"] == goalie_id:
                return goalie

        # If goalie exists in DB but has no appearances in this season
        player = db.session.get(Player, goalie_id)
        if not player or player.position != 'G':
            return None

        return cls._empty_goalie_stats(player, season)

    @classmethod
    def get_season_goalies_summary(
        cls,
        season: str,
        team_id: Optional[int] = None,
        min_gp: int = 1,
        min_shots_faced: int = 0,
        min_toi_seconds: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Aggregates season statistics for all goalies in a given season using grouped SQL queries.
        Population / Denominator rules:
        - Conventional shots faced and saves include all shots on goal (Goal, Saved), excluding shootouts.
        - xGA and GSAx strictly exclude empty-net attempts and shootout attempts.
        """
        # 1. Fetch all games for this season
        game_query = db.session.query(Game.game_id).filter(Game.season == season)
        season_game_ids = [r[0] for r in game_query.all()]
        if not season_game_ids:
            return []

        # 2. Get GP, player info, and team association from GamePlayer / Player
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
                Player.position == 'G'
            )
        )
        if team_id:
            gp_query = gp_query.filter(GamePlayer.team_id == team_id)

        gp_rows = gp_query.group_by(GamePlayer.player_id, GamePlayer.team_id).all()
        if not gp_rows:
            return []

        goalie_meta = {}
        for r in gp_rows:
            pid = r.player_id
            if pid not in goalie_meta:
                goalie_meta[pid] = {
                    "player_id": pid,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "full_name": f"{r.first_name} {r.last_name}",
                    "position": "G",
                    "team_id": r.team_id,
                    "team_abbrev": r.team_abbrev,
                    "team_name": r.team_name,
                    "gp": r.gp
                }
            else:
                goalie_meta[pid]["gp"] += r.gp

        relevant_pids = list(goalie_meta.keys())

        # 3. Shots on Goal Faced (outcome in ['Goal', 'Saved'], excluding shootouts)
        sog_rows = (
            db.session.query(
                Shot.goalie_id,
                func.count(Shot.shot_id)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.goalie_id.in_(relevant_pids),
                Shot.outcome.in_(['Goal', 'Saved']),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.goalie_id).all()
        )
        shots_faced_map = {pid: count for pid, count in sog_rows}

        # 4. Goals Against (goal == True, outcome in ['Goal'], excluding shootouts)
        ga_rows = (
            db.session.query(
                Shot.goalie_id,
                func.count(Shot.shot_id)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.goalie_id.in_(relevant_pids),
                Shot.goal == True,
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.goalie_id).all()
        )
        ga_map = {pid: count for pid, count in ga_rows}

        # 5. Non-Empty-Net Shots Faced, Goals Against Faced, and xGA
        # Excludes empty-net attempts and shootouts
        xga_rows = (
            db.session.query(
                Shot.goalie_id,
                func.sum(Shot.xg),
                func.count(Shot.shot_id)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.goalie_id.in_(relevant_pids),
                Shot.outcome.in_(['Goal', 'Saved']),
                Shot.empty_net == False,
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.goalie_id).all()
        )
        xga_map = {pid: (round(float(sum_xg), 2) if sum_xg is not None else 0.0) for pid, sum_xg, _ in xga_rows}
        shots_faced_nen_map = {pid: count for pid, _, count in xga_rows}

        ga_faced_rows = (
            db.session.query(
                Shot.goalie_id,
                func.count(Shot.shot_id)
            )
            .join(Event, Shot.shot_id == Event.event_id)
            .filter(
                Event.game_id.in_(season_game_ids),
                Shot.goalie_id.in_(relevant_pids),
                Shot.goal == True,
                Shot.empty_net == False,
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            )
            .group_by(Shot.goalie_id).all()
        )
        ga_faced_map = {pid: count for pid, count in ga_faced_rows}

        # 6. Time on Ice (TOI) from Shift
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

        # 7. Assemble goalie season records
        results = []
        for pid, meta in goalie_meta.items():
            gp = meta["gp"]
            shots_faced = shots_faced_map.get(pid, 0)
            ga = ga_map.get(pid, 0)
            saves = shots_faced - ga
            save_pct = round((saves / shots_faced * 100), 2) if shots_faced > 0 else 0.0

            toi_sec = toi_map.get(pid, 0)

            # Sample filtering
            if gp < min_gp or shots_faced < min_shots_faced or toi_sec < min_toi_seconds:
                continue

            xga = xga_map.get(pid, 0.0)
            ga_faced = ga_faced_map.get(pid, 0)
            # Goals Saved Above Expected = Expected Goals Against - Actual Non-Empty-Net Goals Allowed
            gsax = round(xga - ga_faced, 2)

            toi_hours = toi_sec / 3600.0 if toi_sec > 0 else 0.0
            gsax_per_60 = round(gsax / toi_hours, 2) if toi_hours > 0 else 0.0
            xga_per_60 = round(xga / toi_hours, 2) if toi_hours > 0 else 0.0

            # Expected save percentage based on shots faced
            # (shots_faced - xga) / shots_faced * 100
            nen_shots = shots_faced_nen_map.get(pid, shots_faced)
            if nen_shots > 0:
                expected_save_pct = round(((nen_shots - xga) / nen_shots * 100), 2)
            else:
                expected_save_pct = 0.0

            save_pct_diff = round(save_pct - expected_save_pct, 2)

            results.append({
                "player_id": pid,
                "name": meta["full_name"],
                "position": "G",
                "team_id": meta["team_id"],
                "team_abbrev": meta["team_abbrev"],
                "team_name": meta["team_name"],
                "season": season,
                # Traditional Metrics
                "gp": gp,
                "toi_seconds": toi_sec,
                "toi_formatted": format_toi(toi_sec),
                "shots_faced": shots_faced,
                "goals_against": ga,
                "saves": saves,
                "save_pct": save_pct,
                # Predictive / Quality-Adjusted Metrics
                "xga": xga,
                "expected_goals_against": xga,
                "gsax": gsax,
                "goals_saved_above_expected": gsax,
                "gsax_per_60": gsax_per_60,
                "xga_per_60": xga_per_60,
                "expected_save_pct": expected_save_pct,
                "save_pct_diff": save_pct_diff,
                "save_pct_above_expected": save_pct_diff,
                # Population metadata
                "empty_net_excluded": True,
                "shootout_excluded": True
            })

        results.sort(key=lambda x: -x["gsax"])
        return results

    @classmethod
    def get_goalie_leaderboards(
        cls,
        season: str,
        sort_by: str = "gsax",
        min_gp: int = 1,
        min_shots_faced: int = 0,
        min_toi_seconds: int = 0,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Generates goalie analytical leaderboards with sample thresholds.
        Valid sort_by keys: 'gsax', 'gsax_per_60', 'save_pct', 'expected_save_pct',
        'save_pct_above_expected', 'shots_faced', 'xga', 'xga_per_60'.
        """
        goalies = cls.get_season_goalies_summary(
            season=season,
            min_gp=min_gp,
            min_shots_faced=min_shots_faced,
            min_toi_seconds=min_toi_seconds
        )
        if not goalies:
            return []

        # xga and xga_per_60: lower is better (ascending sort)
        reverse = (sort_by not in ['xga', 'xga_per_60'])

        goalies.sort(key=lambda x: x.get(sort_by, 0.0) or 0.0, reverse=reverse)

        for rank_idx, goalie in enumerate(goalies, 1):
            goalie["rank"] = rank_idx

        return goalies[:limit]

    @staticmethod
    def _empty_goalie_stats(player: Player, season: str) -> Dict[str, Any]:
        return {
            "player_id": player.player_id,
            "name": player.full_name,
            "position": "G",
            "team_id": player.current_team_id,
            "team_abbrev": player.current_team.abbreviation if player.current_team else "UNK",
            "team_name": player.current_team.name if player.current_team else "Unknown",
            "season": season,
            "gp": 0,
            "toi_seconds": 0,
            "toi_formatted": "00:00",
            "shots_faced": 0,
            "goals_against": 0,
            "saves": 0,
            "save_pct": 0.0,
            "xga": 0.0,
            "expected_goals_against": 0.0,
            "gsax": 0.0,
            "goals_saved_above_expected": 0.0,
            "gsax_per_60": 0.0,
            "xga_per_60": 0.0,
            "expected_save_pct": 0.0,
            "save_pct_diff": 0.0,
            "save_pct_above_expected": 0.0,
            "empty_net_excluded": True,
            "shootout_excluded": True
        }
