import os
import sys
import argparse
import json
import time
import tracemalloc
import logging
from sqlalchemy import event, text

sys.path.insert(0, os.path.abspath("."))

from app import create_app
from app.models import db, Game

logging.basicConfig(level=logging.WARNING)

app = create_app()

class QueryCounter:
    def __init__(self):
        self.count = 0
        self.statements = []

    def callback(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.statements.append(statement)

def measure_operation(name, func, *args, **kwargs):
    print(f"\nStarting benchmark: {name}...", flush=True)
    counter = QueryCounter()
    listener = lambda c, cur, stmt, p, ctx, em: counter.callback(c, cur, stmt, p, ctx, em)
    event.listen(db.engine, "before_cursor_execute", listener)
    
    tracemalloc.start()
    t0 = time.perf_counter()
    result = func(*args, **kwargs)
    t1 = time.perf_counter()
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    event.remove(db.engine, "before_cursor_execute", listener)
    
    elapsed_ms = (t1 - t0) * 1000
    peak_mb = peak_mem / (1024.0 * 1024.0)
    
    res_info = f"{len(result)} items" if isinstance(result, list) else ("Found" if result else "None")
    
    print(f"=== {name} ===", flush=True)
    print(f"Execution Time: {elapsed_ms:.2f} ms ({elapsed_ms/1000.0:.2f} s)", flush=True)
    print(f"SQL Queries Executed: {counter.count}", flush=True)
    print(f"Peak Memory Allocated: {peak_mb:.2f} MB", flush=True)
    print(f"Output Info: {res_info}", flush=True)
    print("-" * 50, flush=True)
    
    return {
        "operation": name,
        "time_ms": round(elapsed_ms, 2),
        "time_s": round(elapsed_ms / 1000.0, 2),
        "query_count": counter.count,
        "peak_mem_mb": round(peak_mb, 2)
    }

def get_season_dataset_scale(season: str):
    print("\n=== SEASON DATASET SCALE DIAGNOSTICS ===", flush=True)
    with app.app_context():
        with db.engine.connect() as conn:
            games_cnt = conn.execute(text("SELECT COUNT(*) FROM game WHERE season = :s"), {"s": season}).scalar()
            gp_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM game_player gp JOIN game g ON gp.game_id = g.game_id WHERE g.season = :s"
            ), {"s": season}).scalar()
            shifts_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM shift s JOIN game g ON s.game_id = g.game_id WHERE g.season = :s"
            ), {"s": season}).scalar()
            events_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM event e JOIN game g ON e.game_id = g.game_id WHERE g.season = :s"
            ), {"s": season}).scalar()
            shots_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM shot sh JOIN event e ON sh.shot_id = e.event_id JOIN game g ON e.game_id = g.game_id WHERE g.season = :s"
            ), {"s": season}).scalar()
            
            # 5v5 specific diagnostics
            shifts_5v5_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM shift s JOIN game g ON s.game_id = g.game_id WHERE g.season = :s AND s.is_anomaly = 0 AND s.duration > 0"
            ), {"s": season}).scalar()
            events_5v5_cnt = conn.execute(text(
                "SELECT COUNT(*) FROM event e JOIN game g ON e.game_id = g.game_id WHERE g.season = :s AND e.team_strength_state = '5v5'"
            ), {"s": season}).scalar()

            scale = {
                "season": season,
                "games": games_cnt,
                "game_player_rows": gp_cnt,
                "shifts": shifts_cnt,
                "valid_shifts": shifts_5v5_cnt,
                "events": events_cnt,
                "events_5v5": events_5v5_cnt,
                "shots": shots_cnt
            }

            print(f"Season: {season}", flush=True)
            print(f"Games: {games_cnt}", flush=True)
            print(f"GamePlayer rows: {gp_cnt}", flush=True)
            print(f"Shifts (total): {shifts_cnt}", flush=True)
            print(f"Shifts (valid, >0s): {shifts_5v5_cnt}", flush=True)
            print(f"Events (total): {events_cnt}", flush=True)
            print(f"Events (5v5): {events_5v5_cnt}", flush=True)
            print(f"Shots: {shots_cnt}", flush=True)
            print("-" * 50, flush=True)
            return scale

def run_explain_queries(season: str):
    print("\n=== SQL EXPLAIN QUERY PLAN ANALYSIS ===", flush=True)
    
    queries = [
        ("Game Season Query", 
         "EXPLAIN QUERY PLAN SELECT game_id, game_date FROM game WHERE season = :s ORDER BY game_date ASC, game_id ASC"),
        ("GamePlayer Season Join Query", 
         "EXPLAIN QUERY PLAN SELECT gp.player_id, gp.game_id, gp.team_id FROM game_player gp JOIN player p ON gp.player_id = p.player_id JOIN team t ON gp.team_id = t.team_id JOIN game g ON gp.game_id = g.game_id WHERE g.season = :s AND p.position != 'G'"),
        ("Shifts Bulk Query", 
         "EXPLAIN QUERY PLAN SELECT player_id, duration FROM shift WHERE game_id IN (SELECT game_id FROM game WHERE season = :s) AND is_anomaly = 0 AND duration > 0"),
        ("Events 5v5 Shot Query", 
         "EXPLAIN QUERY PLAN SELECT e.game_id, e.event_type, sh.xg FROM event e JOIN game g ON e.game_id = g.game_id LEFT OUTER JOIN shot sh ON e.event_id = sh.shot_id WHERE g.season = :s AND e.team_strength_state = '5v5'"),
        ("Goals Query by Player", 
         "EXPLAIN QUERY PLAN SELECT primary_player_id, COUNT(event_id) FROM event e JOIN game g ON e.game_id = g.game_id WHERE g.season = :s AND e.event_type = 'goal' GROUP BY primary_player_id")
    ]
    
    plan_results = []
    with app.app_context():
        with db.engine.connect() as conn:
            for name, q in queries:
                print(f"\nQuery: {name}", flush=True)
                print(f"SQL: {q}", flush=True)
                lines = []
                try:
                    res = conn.execute(text(q), {"s": season}).fetchall()
                    for r in res:
                        r_str = str(r)
                        print(f"  -> {r_str}", flush=True)
                        lines.append(r_str)
                except Exception as e:
                    err_str = f"Error executing query plan: {e}"
                    print(f"  -> {err_str}", flush=True)
                    lines.append(err_str)
                plan_results.append({"query_name": name, "query_plan": lines})
    return plan_results

def main():
    parser = argparse.ArgumentParser(description="PuckLens v1.5 Stage 0 Baseline Benchmarking & Diagnostics Utility")
    parser.add_argument("--season", type=str, default="20212022", help="Target season to benchmark (default: 20212022)")
    parser.add_argument("--output", type=str, default=None, help="Optional output JSON filepath to save benchmark results")
    args = parser.parse_args()

    target_season = args.season

    with app.app_context():
        seasons_in_db = [r[0] for r in db.session.query(Game.season).distinct().all()]
        if seasons_in_db and target_season not in seasons_in_db:
            print(f"WARNING: Specified season {target_season} not found in database. Available seasons: {seasons_in_db}", flush=True)

        print(f"=== PuckLens Stage 0 Benchmark (Season: {target_season}) ===", flush=True)

        from app.services.player_season_service import PlayerSeasonService
        from app.services.team_season_service import TeamSeasonService

        # Fetch sample player and team
        sample_skaters = PlayerSeasonService.get_season_skaters_summary(season=target_season, include_on_ice_5v5=False)
        sample_pid = sample_skaters[0]["player_id"] if sample_skaters else 8477934
        sample_team_id = sample_skaters[0]["team_id"] if sample_skaters else 22

        print(f"Sample player_id: {sample_pid}, Sample team_id: {sample_team_id}\n", flush=True)

        scale_info = get_season_dataset_scale(target_season)

        benchmarks = []
        benchmarks.append(measure_operation(
            "1. Single Player Season Stats (get_skater_season_stats)",
            PlayerSeasonService.get_skater_season_stats,
            player_id=sample_pid,
            season=target_season
        ))
        benchmarks.append(measure_operation(
            "2. Full Season Skaters Summary (include_on_ice_5v5=True)",
            PlayerSeasonService.get_season_skaters_summary,
            season=target_season,
            include_on_ice_5v5=True
        ))
        benchmarks.append(measure_operation(
            "3. Full Season Skaters Summary (include_on_ice_5v5=False)",
            PlayerSeasonService.get_season_skaters_summary,
            season=target_season,
            include_on_ice_5v5=False
        ))
        benchmarks.append(measure_operation(
            "4. Team Season Stats (get_team_season_stats)",
            TeamSeasonService.get_team_season_stats,
            team_id=sample_team_id,
            season=target_season
        ))
        benchmarks.append(measure_operation(
            "5. Skater Leaderboards (get_skater_leaderboards limit=50)",
            PlayerSeasonService.get_skater_leaderboards,
            season=target_season,
            sort_by="points",
            limit=50
        ))

        query_plans = run_explain_queries(target_season)

        report = {
            "season": target_season,
            "dataset_scale": scale_info,
            "benchmarks": benchmarks,
            "query_plans": query_plans
        }

        if args.output:
            out_path = os.path.abspath(args.output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            print(f"\nSaved benchmark report JSON to: {out_path}", flush=True)

if __name__ == "__main__":
    main()
