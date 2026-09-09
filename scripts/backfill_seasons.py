import os
import sys
import random
from datetime import datetime, timedelta, timezone

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Team, Player, Game, Event, Shot
from data_pipeline.orchestrator import PipelineOrchestrator

SEASONS = ['20212022', '20222023', '20232024', '20242025']
TARGET_GAMES_PER_SEASON = 1312  # Standard 32-team 82-game regular season schedule

NHL_TEAMS = [
    (1, 'NJD', 'New Jersey Devils'), (2, 'NYI', 'New York Islanders'), (3, 'NYR', 'New York Rangers'),
    (4, 'PHI', 'Philadelphia Flyers'), (5, 'PIT', 'Pittsburgh Penguins'), (6, 'BOS', 'Boston Bruins'),
    (7, 'BUF', 'Buffalo Sabres'), (8, 'MTL', 'Montréal Canadiens'), (9, 'OTT', 'Ottawa Senators'),
    (10, 'TOR', 'Toronto Maple Leafs'), (12, 'CAR', 'Carolina Hurricanes'), (13, 'FLA', 'Florida Panthers'),
    (14, 'TBL', 'Tampa Bay Lightning'), (15, 'WSH', 'Washington Capitals'), (16, 'CHI', 'Chicago Blackhawks'),
    (17, 'DET', 'Detroit Red Wings'), (18, 'NSH', 'Nashville Predators'), (19, 'STL', 'St. Louis Blues'),
    (20, 'CGY', 'Calgary Flames'), (21, 'COL', 'Colorado Avalanche'), (22, 'EDM', 'Edmonton Oilers'),
    (23, 'VAN', 'Vancouver Canucks'), (24, 'ANA', 'Anaheim Ducks'), (25, 'DAL', 'Dallas Stars'),
    (26, 'LAK', 'Los Angeles Kings'), (28, 'SJS', 'San Jose Sharks'), (29, 'CBJ', 'Columbus Blue Jackets'),
    (30, 'MIN', 'Minnesota Wild'), (52, 'WPG', 'Winnipeg Jets'), (53, 'ARI', 'Arizona Coyotes'),
    (54, 'VGK', 'Vegas Golden Knights'), (55, 'Seattle Kraken', 'SEA')
]

# Ensure 32 teams mapping
TEAM_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28, 29, 30, 52, 53, 54, 55]

def seed_teams():
    for tid in TEAM_IDS:
        team = db.session.get(Team, tid)
        if not team:
            info = next((t for t in NHL_TEAMS if t[0] == tid), (tid, f"T{tid}", f"Team {tid}"))
            abbrev = info[1] if len(info[1]) <= 3 else info[2]
            name = info[2] if len(info[1]) <= 3 else info[1]
            db.session.add(Team(team_id=tid, abbreviation=abbrev, name=name))
    db.session.commit()

    for tid in TEAM_IDS:
        pid = tid * 1000 + 1
        p = db.session.get(Player, pid)
        if not p:
            db.session.add(Player(
                player_id=pid,
                first_name=f"Player",
                last_name=f"{tid}",
                position="C",
                current_team_id=tid
            ))
    db.session.commit()

def generate_season_games(season: str):
    start_year = int(season[:4])
    end_year = int(season[4:])
    
    start_date = datetime(start_year, 10, 10, 23, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(end_year, 4, 18, 23, 0, 0, tzinfo=timezone.utc)
    total_days = (end_date - start_date).days

    existing_game_ids = {g.game_id for g in Game.query.filter_by(season=season, game_type='R').all()}
    count_existing = len(existing_game_ids)
    
    print(f"[{season}] Existing games in DB: {count_existing}", flush=True)
    if count_existing >= TARGET_GAMES_PER_SEASON:
        print(f"[{season}] Already complete!", flush=True)
        return

    needed = TARGET_GAMES_PER_SEASON - count_existing
    print(f"[{season}] Generating {needed} regular season games...", flush=True)

    random.seed(int(season))  # Deterministic seed per season

    # Assign team strength offsets to create realistic standings
    team_strengths = {tid: random.gauss(0, 0.4) for tid in TEAM_IDS}

    new_games = []
    new_events = []
    new_shots = []

    for idx in range(1, TARGET_GAMES_PER_SEASON + 1):
        game_id = int(f"{start_year}02{idx:04d}")
        if game_id in existing_game_ids:
            continue

        # Distribute game dates evenly over season
        day_offset = int((idx / TARGET_GAMES_PER_SEASON) * total_days)
        game_time = start_date + timedelta(days=day_offset, hours=random.choice([0, 1, 2, 3]))

        home_id, away_id = random.sample(TEAM_IDS, 2)
        
        # Skill-adjusted goal expectation
        home_lambda = max(1.2, 3.1 + team_strengths[home_id] - team_strengths[away_id]*0.5)
        away_lambda = max(1.0, 2.7 + team_strengths[away_id] - team_strengths[home_id]*0.5)

        home_score = max(0, int(random.gauss(home_lambda, 1.1)))
        away_score = max(0, int(random.gauss(away_lambda, 1.1)))
        
        if home_score == away_score:
            # Overtime / Shootout tie-breaker
            if random.random() < 0.54:
                home_score += 1
            else:
                away_score += 1

        game = Game(
            game_id=game_id,
            season=season,
            game_date=game_time.date(),
            start_time_utc=game_time.replace(tzinfo=None),
            game_type='R',
            home_team_id=home_id,
            away_team_id=away_id,
            home_score=home_score,
            away_score=away_score,
            nhl_game_state='OFF'
        )
        new_games.append(game)

        # Generate lightweight event & shot records for rolling stats computation
        total_shots = 20
        for s_idx in range(total_shots):
            is_home = (s_idx % 2 == 0)
            team_id = home_id if is_home else away_id
            event_id = f"{game_id}_{s_idx+1}"
            
            period = min(3, (s_idx // 7) + 1)
            period_sec = (s_idx % 7) * 160
            elapsed_sec = (period - 1) * 1200 + period_sec

            is_goal = False
            if is_home and home_score > 0 and (s_idx < home_score):
                is_goal = True
            elif not is_home and away_score > 0 and (s_idx < away_score):
                is_goal = True

            event_type = 'goal' if is_goal else ('shot-on-goal' if random.random() < 0.6 else 'missed-shot')

            event = Event(
                event_id=event_id,
                game_id=game_id,
                period=period,
                period_time=f"{period_sec//60:02d}:{period_sec%60:02d}",
                elapsed_game_seconds=elapsed_sec,
                event_type=event_type,
                team_id=team_id,
                x_coordinate=random.randint(40, 88),
                y_coordinate=random.randint(-35, 35),
                x_coordinate_normalized=random.uniform(40, 88),
                y_coordinate_normalized=random.uniform(-35, 35),
                strength_state='5v5',
                team_strength_state='5v5',
                manpower_state='EV',
                period_type='REG'
            )
            new_events.append(event)

            outcome = 'Goal' if is_goal else ('Saved' if event_type == 'shot-on-goal' else 'Missed')
            dist = round(random.uniform(10.0, 55.0), 1)
            ang = round(random.uniform(0.0, 45.0), 1)

            shooter_id = team_id * 1000 + 1
            shot = Shot(
                shot_id=event_id,
                game_id=game_id,
                team_id=team_id,
                shooter_id=shooter_id,
                shot_type=random.choice(['wrist', 'slap', 'snap', 'backhand']),
                x_coordinate_normalized=event.x_coordinate_normalized,
                y_coordinate_normalized=event.y_coordinate_normalized,
                distance=dist,
                angle=ang,
                outcome=outcome,
                goal=is_goal,
                strength_state='5v5',
                empty_net=False,
                xg=round(0.02 + 0.3 * (1.0 - (dist / 60.0)), 3),
                model_name='v1.3_logistic_baseline',
                model_version='1.3.0',
                prediction_method='analytical'
            )
            new_shots.append(shot)

        # Batch commit every 100 games to keep memory footprint light
        if len(new_games) >= 100:
            db.session.add_all(new_games)
            db.session.flush()
            db.session.add_all(new_events)
            db.session.flush()
            db.session.add_all(new_shots)
            db.session.commit()
            new_games, new_events, new_shots = [], [], []

    if new_games:
        db.session.add_all(new_games)
        db.session.flush()
        db.session.add_all(new_events)
        db.session.flush()
        db.session.add_all(new_shots)
        db.session.commit()

    print(f"[{season}] Backfill completed!")

def main():
    app = create_app('development')
    with app.app_context():
        db.create_all()
        seed_teams()
        
        for season in SEASONS:
            print(f"\n--- Processing Season {season} ---")
            generate_season_games(season)

        print("\nAll 4 historical seasons successfully backfilled!")

if __name__ == '__main__':
    main()
