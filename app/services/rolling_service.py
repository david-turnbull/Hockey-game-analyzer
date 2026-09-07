import logging
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func
from app.models import db, Game, Team, Event, Shot, Shift, GamePlayer, Player
from app.services.game_service import GameService

logger = logging.getLogger(__name__)

class RollingService:
    """
    Service for calculating chronological rolling trend metrics for teams, skaters, and goalies.
    Guarantees strict chronological ordering with zero future-game data leakage.
    """

    @classmethod
    def get_team_rolling_trends(
        cls,
        team_id: int,
        season: str,
        window_sizes: List[int] = [5, 10, 20]
    ) -> Dict[str, Any]:
        """
        Calculates rolling metrics for a team across a season over multiple window sizes (5, 10, 20 games).
        Metrics per window: xGF%, xG differential, xGF/60, xGA/60, CF%, FF%, GF - xGF, GA - xGA.
        """
        # 1. Fetch team games ordered strictly chronologically
        games = Game.query.filter(
            Game.season == season,
            or_(Game.home_team_id == team_id, Game.away_team_id == team_id)
        ).order_by(Game.game_date.asc(), Game.game_id.asc()).all()

        if not games:
            return {"team_id": team_id, "season": season, "games": [], "windows": {}}

        game_ids = [g.game_id for g in games]

        # 2. Extract per-game team metrics efficiently
        # Events counts per game
        shot_event_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        event_counts = db.session.query(
            Event.game_id,
            Event.team_id,
            Event.event_type,
            func.count(Event.event_id)
        ).filter(
            Event.game_id.in_(game_ids),
            Event.event_type.in_(shot_event_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Event.game_id, Event.team_id, Event.event_type).all()

        # Shot xG sums per game
        xg_sums = db.session.query(
            Event.game_id,
            Shot.team_id,
            func.sum(Shot.xg)
        ).join(Event, Shot.shot_id == Event.event_id).filter(
            Event.game_id.in_(game_ids),
            Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Event.game_id, Shot.team_id).all()

        # Build game-level metrics map
        game_metrics = {
            gid: {
                "cf": 0, "ca": 0,
                "ff": 0, "fa": 0,
                "gf": 0, "ga": 0,
                "xgf": 0.0, "xga": 0.0
            }
            for gid in game_ids
        }

        for gid, tid, etype, count in event_counts:
            is_for = (tid == team_id)
            if is_for:
                game_metrics[gid]["cf"] += count
                if etype in ['shot-on-goal', 'goal', 'missed-shot']:
                    game_metrics[gid]["ff"] += count
                if etype == 'goal':
                    game_metrics[gid]["gf"] += count
            else:
                game_metrics[gid]["ca"] += count
                if etype in ['shot-on-goal', 'goal', 'missed-shot']:
                    game_metrics[gid]["fa"] += count
                if etype == 'goal':
                    game_metrics[gid]["ga"] += count

        for gid, tid, xg_val in xg_sums:
            if xg_val is None:
                continue
            if tid == team_id:
                game_metrics[gid]["xgf"] += float(xg_val)
            else:
                game_metrics[gid]["xga"] += float(xg_val)

        # 3. Calculate rolling windows without future-game leakage
        windows_data: Dict[str, List[Dict[str, Any]]] = {}

        # Format games list
        game_entries = []
        for idx, g in enumerate(games):
            is_home = (g.home_team_id == team_id)
            opp = g.away_team if is_home else g.home_team
            game_entries.append({
                "game_index": idx + 1,
                "game_id": g.game_id,
                "date": g.game_date.strftime("%Y-%m-%d"),
                "opponent_abbrev": opp.abbreviation if opp else "UNK",
                "opponent_name": opp.name if opp else "Unknown",
                "is_home": is_home,
                "score_for": g.home_score if is_home else g.away_score,
                "score_against": g.away_score if is_home else g.home_score
            })

        for w_size in window_sizes:
            w_points = []
            for i in range(len(games)):
                # Window range: [start_idx, i] inclusive
                start_idx = max(0, i - w_size + 1)
                window_slice = games[start_idx : i + 1]
                actual_w = len(window_slice)

                # Sum up metrics strictly within the window
                w_cf = sum(game_metrics[g.game_id]["cf"] for g in window_slice)
                w_ca = sum(game_metrics[g.game_id]["ca"] for g in window_slice)
                w_ff = sum(game_metrics[g.game_id]["ff"] for g in window_slice)
                w_fa = sum(game_metrics[g.game_id]["fa"] for g in window_slice)
                w_gf = sum(game_metrics[g.game_id]["gf"] for g in window_slice)
                w_ga = sum(game_metrics[g.game_id]["ga"] for g in window_slice)
                w_xgf = sum(game_metrics[g.game_id]["xgf"] for g in window_slice)
                w_xga = sum(game_metrics[g.game_id]["xga"] for g in window_slice)

                # Calculations
                tot_c = w_cf + w_ca
                cf_pct = round((w_cf / tot_c * 100), 2) if tot_c > 0 else 50.0

                tot_f = w_ff + w_fa
                ff_pct = round((w_ff / tot_f * 100), 2) if tot_f > 0 else 50.0

                tot_xg = w_xgf + w_xga
                xgf_pct = round((w_xgf / tot_xg * 100), 2) if tot_xg > 0 else 50.0
                xg_diff = round(w_xgf - w_xga, 2)

                # Rates per 60 (standard 60 min regulation per game in window)
                toi_hours = actual_w * 1.0  # 1.0 hr per game
                xgf_per_60 = round(w_xgf / toi_hours, 2) if toi_hours > 0 else 0.0
                xga_per_60 = round(w_xga / toi_hours, 2) if toi_hours > 0 else 0.0

                gf_minus_xgf = round(w_gf - w_xgf, 2)
                ga_minus_xga = round(w_ga - w_xga, 2)

                curr_g = games[i]
                w_points.append({
                    "game_index": i + 1,
                    "game_id": curr_g.game_id,
                    "date": curr_g.game_date.strftime("%Y-%m-%d"),
                    "window_size": w_size,
                    "games_in_window": actual_w,
                    "xgf_pct": xgf_pct,
                    "xg_diff": xg_diff,
                    "xgf_per_60": xgf_per_60,
                    "xga_per_60": xga_per_60,
                    "cf_pct": cf_pct,
                    "ff_pct": ff_pct,
                    "gf_minus_xgf": gf_minus_xgf,
                    "ga_minus_xga": ga_minus_xga
                })

            windows_data[str(w_size)] = w_points

        return {
            "team_id": team_id,
            "season": season,
            "games": game_entries,
            "windows": windows_data
        }

    @classmethod
    def get_goalie_rolling_trends(
        cls,
        goalie_id: int,
        season: str,
        window_size: int = 5
    ) -> Dict[str, Any]:
        """
        Calculates chronological rolling metrics for a goalie across games played:
        rolling GSAx, rolling GSAx/game, rolling save %, rolling expected save %.
        """
        # 1. Fetch distinct games where goalie appeared, ordered chronologically
        games = (
            db.session.query(Game)
            .join(Shot, Shot.game_id == Game.game_id)
            .filter(
                Game.season == season,
                Shot.goalie_id == goalie_id,
                or_(Shot.outcome.in_(['Goal', 'Saved']))
            )
            .distinct()
            .order_by(Game.game_date.asc(), Game.game_id.asc())
            .all()
        )

        if not games:
            return {"goalie_id": goalie_id, "season": season, "window_size": window_size, "trend": []}

        # 2. Extract per-game goalie metrics
        per_game_stats = []
        for g in games:
            # Shots faced & GA on net
            shots = Shot.query.filter(
                Shot.game_id == g.game_id,
                Shot.goalie_id == goalie_id,
                Shot.outcome.in_(['Goal', 'Saved'])
            ).all()

            shots_faced = len(shots)
            goals_against = sum(1 for s in shots if s.goal)
            saves = shots_faced - goals_against

            # xGA and GSAx (excluding empty net)
            nen_shots = [s for s in shots if not s.empty_net]
            xga = sum(s.xg for s in nen_shots if s.xg is not None)
            ga_faced = sum(1 for s in nen_shots if s.goal)
            gsax = xga - ga_faced

            per_game_stats.append({
                "game_id": g.game_id,
                "date": g.game_date.strftime("%Y-%m-%d"),
                "shots_faced": shots_faced,
                "goals_against": goals_against,
                "saves": saves,
                "nen_shots_count": len(nen_shots),
                "xga": xga,
                "gsax": gsax
            })

        # 3. Compute rolling window
        trend = []
        for i in range(len(per_game_stats)):
            start_idx = max(0, i - window_size + 1)
            w_slice = per_game_stats[start_idx : i + 1]
            actual_w = len(w_slice)

            w_sf = sum(p["shots_faced"] for p in w_slice)
            w_ga = sum(p["goals_against"] for p in w_slice)
            w_saves = sum(p["saves"] for p in w_slice)
            w_nen = sum(p["nen_shots_count"] for p in w_slice)
            w_xga = sum(p["xga"] for p in w_slice)
            w_gsax = sum(p["gsax"] for p in w_slice)

            rolling_save_pct = round((w_saves / w_sf * 100), 2) if w_sf > 0 else 0.0
            rolling_exp_save_pct = round(((w_nen - w_xga) / w_nen * 100), 2) if w_nen > 0 else 0.0
            rolling_gsax = round(w_gsax, 2)
            rolling_gsax_per_game = round(w_gsax / actual_w, 2) if actual_w > 0 else 0.0

            trend.append({
                "game_index": i + 1,
                "game_id": per_game_stats[i]["game_id"],
                "date": per_game_stats[i]["date"],
                "games_in_window": actual_w,
                "rolling_gsax": rolling_gsax,
                "rolling_gsax_per_game": rolling_gsax_per_game,
                "rolling_save_pct": rolling_save_pct,
                "rolling_expected_save_pct": rolling_exp_save_pct
            })

        return {
            "goalie_id": goalie_id,
            "season": season,
            "window_size": window_size,
            "trend": trend
        }

    @classmethod
    def get_player_rolling_trends(
        cls,
        player_id: int,
        season: str,
        window_size: int = 5
    ) -> Dict[str, Any]:
        """
        Calculates chronological rolling metrics for a skater across games played:
        rolling xG, rolling G - xG, rolling xG/60, rolling shot volume.
        """
        # 1. Fetch distinct games where skater appeared in GamePlayer or Shift, ordered chronologically
        games = (
            db.session.query(Game)
            .join(GamePlayer, GamePlayer.game_id == Game.game_id)
            .filter(
                Game.season == season,
                GamePlayer.player_id == player_id
            )
            .distinct()
            .order_by(Game.game_date.asc(), Game.game_id.asc())
            .all()
        )

        if not games:
            return {"player_id": player_id, "season": season, "window_size": window_size, "trend": []}

        # 2. Extract per-game stats
        per_game_stats = []
        for g in games:
            # Goals
            goals = Event.query.filter(
                Event.game_id == g.game_id,
                Event.event_type == 'goal',
                Event.primary_player_id == player_id,
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).count()

            # Unblocked shots and xG
            unblocked = Shot.query.filter(
                Shot.game_id == g.game_id,
                Shot.shooter_id == player_id,
                Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
                or_(Event.period_type != 'SO', Event.period_type.is_(None))
            ).join(Event, Shot.shot_id == Event.event_id).all()

            shots_count = len(unblocked)
            xg_val = sum(s.xg for s in unblocked if s.xg is not None)

            # TOI seconds
            shifts = Shift.query.filter(
                Shift.game_id == g.game_id,
                Shift.player_id == player_id,
                Shift.duration > 0,
                Shift.is_anomaly == False
            ).all()
            toi_sec = sum(s.duration for s in shifts)

            per_game_stats.append({
                "game_id": g.game_id,
                "date": g.game_date.strftime("%Y-%m-%d"),
                "goals": goals,
                "shot_volume": shots_count,
                "xg": xg_val,
                "toi_seconds": toi_sec
            })

        # 3. Compute rolling window
        trend = []
        for i in range(len(per_game_stats)):
            start_idx = max(0, i - window_size + 1)
            w_slice = per_game_stats[start_idx : i + 1]
            actual_w = len(w_slice)

            w_goals = sum(p["goals"] for p in w_slice)
            w_shots = sum(p["shot_volume"] for p in w_slice)
            w_xg = sum(p["xg"] for p in w_slice)
            w_toi = sum(p["toi_seconds"] for p in w_slice)

            toi_hours = w_toi / 3600.0 if w_toi > 0 else (actual_w * (18.0 / 60.0))  # fallback 18 mins avg
            rolling_xg_per_60 = round(w_xg / toi_hours, 2) if toi_hours > 0 else 0.0
            rolling_g_minus_xg = round(w_goals - w_xg, 2)

            trend.append({
                "game_index": i + 1,
                "game_id": per_game_stats[i]["game_id"],
                "date": per_game_stats[i]["date"],
                "games_in_window": actual_w,
                "rolling_xg": round(w_xg, 2),
                "rolling_goals_above_expected": rolling_g_minus_xg,
                "rolling_xg_per_60": rolling_xg_per_60,
                "rolling_shot_volume": w_shots
            })

        return {
            "player_id": player_id,
            "season": season,
            "window_size": window_size,
            "trend": trend
        }
