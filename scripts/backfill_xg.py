import os
import sys
import json
from collections import defaultdict

# Append project root directory to sys.path so we can import from the 'app' module
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Shot
from app.services.xg_service import XGService
from app.analytics.shot_features import ShotFeatureExtractor

def run_backfill(app, raw_dir=None):
    """
    Backfills xG values and provenance for all stored shots using full PBP contextual features.
    If full PBP context cannot be reconstructed (missing PBP, unparseable PBP, or missing feature match),
    shots are skipped rather than scored with reduced keyword context.
    """
    if raw_dir is None:
        raw_dir = os.path.join(project_root, 'data', 'raw')

    with app.app_context():
        print("Querying all shots from the database...")
        shots = Shot.query.all()
        total_shots = len(shots)
        print(f"Found {total_shots} shots. Populating Expected Goals (xG)...")
        
        # Group shots by game_id to batch-load play-by-play files efficiently
        shots_by_game = defaultdict(list)
        for shot in shots:
            shots_by_game[shot.game_id].append(shot)
            
        full_context_shots_scored = 0
        blocked_shots_cleared = 0
        shots_skipped_missing_pbp = 0
        shots_skipped_feature_missing = 0
        missing_pbp_games = set()
        
        for game_id, game_shots in shots_by_game.items():
            pbp_file = os.path.join(raw_dir, f"pbp_{game_id}.json") if game_id else None
            pbp_feature_map = None
            
            if pbp_file and os.path.exists(pbp_file):
                try:
                    with open(pbp_file, 'r', encoding='utf-8') as f:
                        pbp_data = json.load(f)
                    extracted_shots = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_data, unblocked_only=True)
                    pbp_feature_map = {}
                    for s in extracted_shots:
                        eid = s.get('event_id')
                        if eid and eid not in pbp_feature_map:
                            pbp_feature_map[eid] = s
                except Exception as e:
                    print(f"[Backfill] Error reading/parsing PBP file for game {game_id}: {e}")
                    missing_pbp_games.add(game_id)
            else:
                if game_id:
                    missing_pbp_games.add(game_id)
                    
            for shot in game_shots:
                if shot.outcome == 'Blocked':
                    # Blocked shots invariant: strictly ineligible for xG
                    shot.xg = None
                    shot.model_name = None
                    shot.model_version = None
                    shot.prediction_method = None
                    blocked_shots_cleared += 1
                elif shot.outcome in ['Goal', 'Saved', 'Missed']:
                    if pbp_feature_map is None:
                        # Raw PBP is missing or unparseable: skip without reduced-context fallback
                        shots_skipped_missing_pbp += 1
                        continue
                        
                    feat = pbp_feature_map.get(shot.shot_id)
                    if feat is not None:
                        pred = XGService.predict_shot_xg(features=feat)
                        shot.xg = pred.xg
                        shot.model_name = pred.model_name
                        shot.model_version = pred.model_version
                        shot.prediction_method = pred.method
                        full_context_shots_scored += 1
                    else:
                        # PBP available but feature match missing: skip without fallback
                        shots_skipped_feature_missing += 1
                        continue
                        
        print("\n=== Backfill Summary ===")
        print(f"Full-context shots scored: {full_context_shots_scored}")
        print(f"Blocked shots cleared: {blocked_shots_cleared}")
        print(f"Shots skipped - missing raw PBP: {shots_skipped_missing_pbp}")
        print(f"Shots skipped - feature match missing: {shots_skipped_feature_missing}")
        print(f"Games with missing PBP: {len(missing_pbp_games)}")
        print("Note: Reduced-context historical scoring is no longer silently persisted.")
        
        print("\nSaving updates to the database...")
        db.session.commit()
        print("Database commit completed successfully.")
        
        return {
            "full_context_shots_scored": full_context_shots_scored,
            "blocked_shots_cleared": blocked_shots_cleared,
            "shots_skipped_missing_pbp": shots_skipped_missing_pbp,
            "shots_skipped_feature_missing": shots_skipped_feature_missing,
            "games_missing_pbp": len(missing_pbp_games),
        }

def main():
    app = create_app('development')
    run_backfill(app)

if __name__ == '__main__':
    main()
