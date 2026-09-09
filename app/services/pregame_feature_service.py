import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy import or_, and_, func
from app.models import db, Game, Event, Shot, Team

logger = logging.getLogger(__name__)

class PregameFeatureService:
    """
    Service to generate leakage-safe pregame features for any given target game.
    
    Strict Invariant:
    Only source games strictly prior to the target game's start timestamp
    (source_game.start_time_utc < target_game.start_time_utc) are evaluated.
    """
    _stats_cache = {}
    _team_games_cache = {}

    @classmethod
    def clear_caches(cls):
        cls._stats_cache.clear()
        cls._team_games_cache.clear()

    @classmethod
    def preload_all_stats(cls):
        cls.clear_caches()
        shot_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events_q = db.session.query(
            Event.game_id, Event.team_id, Event.event_type, func.count(Event.event_id)
        ).filter(
            Event.event_type.in_(shot_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Event.game_id, Event.team_id, Event.event_type).all()

        xg_q = db.session.query(
            Event.game_id, Shot.team_id, func.sum(Shot.xg)
        ).join(Event, Shot.shot_id == Event.event_id).filter(
            Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Event.game_id, Shot.team_id).all()

        for gid, tid, etype, count in events_q:
            if gid not in cls._stats_cache:
                cls._stats_cache[gid] = {"cf_by_team": {}, "sog_by_team": {}, "xg_by_team": {}}
            cls._stats_cache[gid]["cf_by_team"][tid] = cls._stats_cache[gid]["cf_by_team"].get(tid, 0) + count
            if etype in ['shot-on-goal', 'goal']:
                cls._stats_cache[gid]["sog_by_team"][tid] = cls._stats_cache[gid]["sog_by_team"].get(tid, 0) + count

        for gid, tid, xg_val in xg_q:
            if xg_val is not None:
                if gid not in cls._stats_cache:
                    cls._stats_cache[gid] = {"cf_by_team": {}, "sog_by_team": {}, "xg_by_team": {}}
                cls._stats_cache[gid]["xg_by_team"][tid] = float(xg_val)

        # Pre-index completed games per team sorted by start_time_utc
        all_games = Game.query.filter(
            Game.game_type == 'R',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        cls._team_games_cache = {}
        for g in all_games:
            if g.home_team_id not in cls._team_games_cache:
                cls._team_games_cache[g.home_team_id] = []
            cls._team_games_cache[g.home_team_id].append(g)

            if g.away_team_id not in cls._team_games_cache:
                cls._team_games_cache[g.away_team_id] = []
            cls._team_games_cache[g.away_team_id].append(g)

    @classmethod
    def get_prior_completed_games_for_team(
        cls,
        team_id: int,
        target_game: Game,
        limit: Optional[int] = None,
        venue: Optional[str] = None  # 'home' or 'away'
    ) -> List[Game]:
        """
        Fetches completed regular season games for team_id strictly prior to target_game.start_time_utc.
        """
        target_start = target_game.start_time
        target_date = target_game.game_date

        if team_id in cls._team_games_cache:
            team_games = cls._team_games_cache[team_id]
            matching = []
            for g in reversed(team_games):
                if g.game_id == target_game.game_id:
                    continue
                g_start = g.start_time
                if g_start < target_start:
                    if venue == 'home' and g.home_team_id != team_id:
                        continue
                    if venue == 'away' and g.away_team_id != team_id:
                        continue
                    matching.append(g)
                    if limit and len(matching) >= limit:
                        break
            return matching

        query = Game.query.filter(
            Game.game_type == 'R',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER']),
            Game.game_id != target_game.game_id
        )

        if venue == 'home':
            query = query.filter(Game.home_team_id == team_id)
        elif venue == 'away':
            query = query.filter(Game.away_team_id == team_id)
        else:
            query = query.filter(or_(Game.home_team_id == team_id, Game.away_team_id == team_id))

        if target_game.start_time_utc:
            query = query.filter(
                Game.start_time_utc < target_start
            ).order_by(
                Game.start_time_utc.desc(),
                Game.game_id.desc()
            )
        else:
            query = query.filter(Game.game_date < target_date).order_by(Game.game_date.desc(), Game.game_id.desc())

        if limit:
            query = query.limit(limit)

        return query.all()

    @classmethod
    def get_game_stats(cls, game_id: int) -> Dict[str, Any]:
        if game_id in cls._stats_cache:
            return cls._stats_cache[game_id]

        shot_types = ['shot-on-goal', 'goal', 'missed-shot', 'blocked-shot']
        events_q = db.session.query(
            Event.team_id, Event.event_type, func.count(Event.event_id)
        ).filter(
            Event.game_id == game_id,
            Event.event_type.in_(shot_types),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Event.team_id, Event.event_type).all()

        xg_q = db.session.query(
            Shot.team_id, func.sum(Shot.xg)
        ).join(Event, Shot.shot_id == Event.event_id).filter(
            Event.game_id == game_id,
            Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
            or_(Event.period_type != 'SO', Event.period_type.is_(None))
        ).group_by(Shot.team_id).all()

        cf_by_team = {}
        sog_by_team = {}
        for tid, etype, count in events_q:
            cf_by_team[tid] = cf_by_team.get(tid, 0) + count
            if etype in ['shot-on-goal', 'goal']:
                sog_by_team[tid] = sog_by_team.get(tid, 0) + count

        xg_by_team = {}
        for tid, xg_val in xg_q:
            if xg_val is not None:
                xg_by_team[tid] = float(xg_val)

        res = {
            "cf_by_team": cf_by_team,
            "sog_by_team": sog_by_team,
            "xg_by_team": xg_by_team
        }
        cls._stats_cache[game_id] = res
        return res

    @classmethod
    def compute_team_rolling_stats(cls, team_id: int, prior_games: List[Game]) -> Dict[str, float]:
        """
        Computes aggregate rolling form metrics across a list of prior games.
        """
        if not prior_games:
            return {
                "count": 0,
                "gf_per_game": 3.0,
                "ga_per_game": 3.0,
                "win_pct": 50.0,
                "xgf_pct": 50.0,
                "cf_pct": 50.0,
                "sf_pct": 50.0,
                "shooting_pct": 9.5,
                "save_pct": 90.5
            }

        n_games = len(prior_games)
        total_gf = 0
        total_ga = 0
        wins = 0

        cf = 0
        ca = 0
        sog_for = 0
        sog_against = 0
        xgf = 0.0
        xga = 0.0

        for g in prior_games:
            is_home = (g.home_team_id == team_id)
            gf = g.home_score if is_home else g.away_score
            ga = g.away_score if is_home else g.home_score
            total_gf += gf
            total_ga += ga
            if gf > ga:
                wins += 1

            opp_id = g.away_team_id if is_home else g.home_team_id

            g_stats = cls.get_game_stats(g.game_id)
            cf += g_stats["cf_by_team"].get(team_id, 0)
            ca += g_stats["cf_by_team"].get(opp_id, 0)

            sog_for += g_stats["sog_by_team"].get(team_id, 0)
            sog_against += g_stats["sog_by_team"].get(opp_id, 0)

            xgf += g_stats["xg_by_team"].get(team_id, 0.0)
            xga += g_stats["xg_by_team"].get(opp_id, 0.0)

        tot_c = cf + ca
        tot_xg = xgf + xga

        return {
            "count": n_games,
            "gf_per_game": round(total_gf / n_games, 2),
            "ga_per_game": round(total_ga / n_games, 2),
            "win_pct": round((wins / n_games) * 100.0, 2),
            "xgf_pct": round((xgf / tot_xg * 100.0), 2) if tot_xg > 0 else 50.0,
            "cf_pct": round((cf / tot_c * 100.0), 2) if tot_c > 0 else 50.0,
            "sf_pct": round((sog_for / (sog_for + sog_against) * 100.0), 2) if (sog_for + sog_against) > 0 else 50.0,
            "shooting_pct": round((total_gf / sog_for * 100.0), 2) if sog_for > 0 else 9.5,
            "save_pct": round((1.0 - (total_ga / sog_against)) * 100.0, 2) if sog_against > 0 else 90.5
        }

    @classmethod
    def get_pregame_features(cls, target_game: Game) -> Dict[str, Any]:
        """
        Calculates all leakage-safe pregame features for target_game.
        """
        home_id = target_game.home_team_id
        away_id = target_game.away_team_id

        # 1. Prior games L10 and L20
        home_l10_games = cls.get_prior_completed_games_for_team(home_id, target_game, limit=10)
        home_l20_games = cls.get_prior_completed_games_for_team(home_id, target_game, limit=20)
        away_l10_games = cls.get_prior_completed_games_for_team(away_id, target_game, limit=10)
        away_l20_games = cls.get_prior_completed_games_for_team(away_id, target_game, limit=20)

        home_l10 = cls.compute_team_rolling_stats(home_id, home_l10_games)
        home_l20 = cls.compute_team_rolling_stats(home_id, home_l20_games)
        away_l10 = cls.compute_team_rolling_stats(away_id, away_l10_games)
        away_l20 = cls.compute_team_rolling_stats(away_id, away_l20_games)

        # 2. Rest days calculation
        target_time = target_game.start_time
        home_prev = home_l10_games[0] if home_l10_games else None
        away_prev = away_l10_games[0] if away_l10_games else None

        if home_prev:
            delta_home = (target_time - home_prev.start_time).total_seconds() / 86400.0
            home_rest = min(7.0, max(1.0, round(delta_home, 1)))
        else:
            home_rest = 4.0

        if away_prev:
            delta_away = (target_time - away_prev.start_time).total_seconds() / 86400.0
            away_rest = min(7.0, max(1.0, round(delta_away, 1)))
        else:
            away_rest = 4.0

        home_is_b2b = 1.0 if home_rest <= 1.2 else 0.0
        away_is_b2b = 1.0 if away_rest <= 1.2 else 0.0
        rest_diff = home_rest - away_rest

        # 3. Venue splits
        home_venue_l10 = cls.get_prior_completed_games_for_team(home_id, target_game, limit=10, venue='home')
        away_venue_l10 = cls.get_prior_completed_games_for_team(away_id, target_game, limit=10, venue='away')

        home_home_wins = sum(1 for g in home_venue_l10 if g.home_score > g.away_score)
        home_venue_win_pct = round((home_home_wins / len(home_venue_l10) * 100.0), 2) if home_venue_l10 else 50.0

        away_away_wins = sum(1 for g in away_venue_l10 if g.away_score > g.home_score)
        away_venue_win_pct = round((away_away_wins / len(away_venue_l10) * 100.0), 2) if away_venue_l10 else 50.0

        # 4. Head-to-head history
        h2h_games = Game.query.filter(
            Game.game_type == 'R',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER']),
            Game.game_id != target_game.game_id,
            or_(
                and_(Game.home_team_id == home_id, Game.away_team_id == away_id),
                and_(Game.home_team_id == away_id, Game.away_team_id == home_id)
            )
        ).filter(
            Game.start_time_utc < target_time
        ).order_by(Game.start_time_utc.desc(), Game.game_id.desc()).limit(5).all()

        if h2h_games:
            h2h_wins = 0
            h2h_gd_sum = 0
            for g in h2h_games:
                is_home = (g.home_team_id == home_id)
                gf = g.home_score if is_home else g.away_score
                ga = g.away_score if is_home else g.home_score
                if gf > ga:
                    h2h_wins += 1
                h2h_gd_sum += (gf - ga)
            h2h_home_win_pct = round((h2h_wins / len(h2h_games)) * 100.0, 2)
            h2h_home_gd_avg = round(h2h_gd_sum / len(h2h_games), 2)
        else:
            h2h_home_win_pct = 50.0
            h2h_home_gd_avg = 0.0

        features = {
            "game_id": target_game.game_id,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "target_start_time": target_time.isoformat(),
            
            # Rest & B2B
            "home_rest_days": home_rest,
            "away_rest_days": away_rest,
            "home_is_b2b": home_is_b2b,
            "away_is_b2b": away_is_b2b,
            "rest_differential": rest_diff,

            # Form L10
            "home_l10_gf_per_game": home_l10["gf_per_game"],
            "home_l10_ga_per_game": home_l10["ga_per_game"],
            "home_l10_win_pct": home_l10["win_pct"],
            "home_l10_xgf_pct": home_l10["xgf_pct"],
            "home_l10_cf_pct": home_l10["cf_pct"],
            "home_l10_sf_pct": home_l10["sf_pct"],
            "home_l10_shooting_pct": home_l10["shooting_pct"],
            "home_l10_save_pct": home_l10["save_pct"],

            "away_l10_gf_per_game": away_l10["gf_per_game"],
            "away_l10_ga_per_game": away_l10["ga_per_game"],
            "away_l10_win_pct": away_l10["win_pct"],
            "away_l10_xgf_pct": away_l10["xgf_pct"],
            "away_l10_cf_pct": away_l10["cf_pct"],
            "away_l10_sf_pct": away_l10["sf_pct"],
            "away_l10_shooting_pct": away_l10["shooting_pct"],
            "away_l10_save_pct": away_l10["save_pct"],

            # Form L20
            "home_l20_xgf_pct": home_l20["xgf_pct"],
            "home_l20_cf_pct": home_l20["cf_pct"],
            "away_l20_xgf_pct": away_l20["xgf_pct"],
            "away_l20_cf_pct": away_l20["cf_pct"],

            # Differentials (Home minus Away)
            "l10_xgf_pct_diff": round(home_l10["xgf_pct"] - away_l10["xgf_pct"], 2),
            "l10_cf_pct_diff": round(home_l10["cf_pct"] - away_l10["cf_pct"], 2),
            "l10_goal_diff_per_game": round((home_l10["gf_per_game"] - home_l10["ga_per_game"]) - (away_l10["gf_per_game"] - away_l10["ga_per_game"]), 2),
            "l20_xgf_pct_diff": round(home_l20["xgf_pct"] - away_l20["xgf_pct"], 2),

            # Venue splits
            "home_venue_l10_win_pct": home_venue_win_pct,
            "away_venue_l10_win_pct": away_venue_win_pct,

            # H2H
            "h2h_home_win_pct": h2h_home_win_pct,
            "h2h_home_gd_avg": h2h_home_gd_avg
        }

        return features
