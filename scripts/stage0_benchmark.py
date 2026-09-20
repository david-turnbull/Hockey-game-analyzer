import os
import sys
sys.path.insert(0, os.path.abspath("."))
import time
import tracemalloc
import logging
from sqlalchemy import event, text
from app import create_app
from app.models import db, Game
from app.services.player_season_service import PlayerSeasonService
from app.services.team_season_service import TeamSeasonService

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

def run_explain_queries():
    print("\n=== SQL EXPLAIN QUERY PLAN ANALYSIS ===", flush=True)
    
    queries = [
        ("Game Season Query", "EXPLAIN QUERY PLAN SELECT game_id, game_date FROM game WHERE season = '20232024' ORDER BY game_date ASC, game_id ASC"),
        ("GamePlayer Season Join Query", "EXPLAIN QUERY PLAN SELECT game_player.player_id, game_player.game_id, game_player.team_id FROM game_player JOIN player ON game_player.player_id = player.player_id JOIN team ON game_player.team_id = team.team_id JOIN game ON game_player.game_id = game.game_id WHERE game.season = '20232024' AND player.position != 'G'"),
        ("Shifts Bulk Query", "EXPLAIN QUERY PLAN SELECT player_id, duration FROM shift WHERE game_id IN (SELECT game_id FROM game WHERE season = '20232024') AND is_anomaly = 0 AND duration > 0"),
        ("Events 5v5 Shot Query", "EXPLAIN QUERY PLAN SELECT event.game_id, event.event_type, shot.xg FROM event LEFT OUTER JOIN shot ON event.event_id = shot.shot_id WHERE event.season = '20232024' AND event.team_strength_state = '5v5'"),
        ("Goals Query by Player", "EXPLAIN QUERY PLAN SELECT primary_player_id, COUNT(event_id) FROM event WHERE season = '20232024' AND event_type = 'goal' GROUP BY primary_player_id")
    ]
    
    with app.app_context():
        with db.engine.connect() as conn:
            for name, q in queries:
                print(f"\nQuery: {name}", flush=True)
                print(f"SQL: {q}", flush=True)
                try:
                    res = conn.execute(text(q)).fetchall()
                    for r in res:
                        print(f"  -> {r}", flush=True)
                except Exception as e:
                    print(f"  -> Error executing query plan: {e}", flush=True)

if __name__ == "__main__":
    with app.app_context():
        seasons = [r[0] for r in db.session.query(Game.season).distinct().all()]
        print(f"Available seasons in DB: {seasons}", flush=True)
        target_season = seasons[0] if seasons else "20232024"
        print(f"Benchmarking season: {target_season}\n", flush=True)

        sample_skaters = PlayerSeasonService.get_season_skaters_summary(season=target_season, include_on_ice_5v5=False)
        sample_pid = sample_skaters[0]["player_id"] if sample_skaters else 8478402
        sample_team_id = sample_skaters[0]["team_id"] if sample_skaters else 1

        print(f"Sample player_id: {sample_pid}, sample team_id: {sample_team_id}\n", flush=True)

        results = []

        results.append(measure_operation(
            "1. Single Player Season Stats (get_skater_season_stats)",
            PlayerSeasonService.get_skater_season_stats,
            player_id=sample_pid,
            season=target_season
        ))

        results.append(measure_operation(
            "2. Full Season Skaters Summary (include_on_ice_5v5=True)",
            PlayerSeasonService.get_season_skaters_summary,
            season=target_season,
            include_on_ice_5v5=True
        ))

        results.append(measure_operation(
            "3. Full Season Skaters Summary (include_on_ice_5v5=False)",
            PlayerSeasonService.get_season_skaters_summary,
            season=target_season,
            include_on_ice_5v5=False
        ))

        results.append(measure_operation(
            "4. Team Season Stats (get_team_season_stats)",
            TeamSeasonService.get_team_season_stats,
            team_id=sample_team_id,
            season=target_season
        ))

        results.append(measure_operation(
            "5. Skater Leaderboards (get_skater_leaderboards limit=50)",
            PlayerSeasonService.get_skater_leaderboards,
            season=target_season,
            sort_by="points",
            limit=50
        ))

        run_explain_queries()
