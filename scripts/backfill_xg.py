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

def main():
    app = create_app('development')
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
            
        updated_count = 0
        cleared_count = 0
        fallback_games = 0
        full_context_shots = 0
        fallback_shots = 0
        
        for game_id, game_shots in shots_by_game.items():
            pbp_file = os.path.join(raw_dir, f"pbp_{game_id}.json") if game_id else None
            pbp_feature_map = {}
            
            if pbp_file and os.path.exists(pbp_file):
                try:
                    with open(pbp_file, 'r', encoding='utf-8') as f:
                        pbp_data = json.load(f)
                    extracted_shots = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_data, unblocked_only=True)
                    pbp_feature_map = {s['event_id']: s for s in extracted_shots}
                except Exception as e:
                    print(f"[Backfill] Error reading PBP file for game {game_id}: {e}")
            else:
                fallback_games += 1
                if game_id:
                    print(f"[Backfill] Raw PBP file missing for game {game_id}; using reduced-context fallback.")
                    
            for shot in game_shots:
                if shot.outcome in ['Goal', 'Saved', 'Missed']:
                    feat = pbp_feature_map.get(shot.shot_id)
                    if feat is not None:
                        pred = XGService.predict_shot_xg(features=feat)
                        full_context_shots += 1
                    else:
                        pred = XGService.predict_shot_xg(
                            distance=shot.distance,
                            angle=shot.angle,
                            shot_type=shot.shot_type,
                            strength_state=shot.strength_state,
                            empty_net=shot.empty_net
                        )
                        fallback_shots += 1
                        
                    shot.xg = pred.xg
                    shot.model_name = pred.model_name
                    shot.model_version = pred.model_version
                    shot.prediction_method = pred.method
                    updated_count += 1
                else:
                    # Blocked shots invariant (Priority 0): strictly ineligible for xG
                    shot.xg = None
                    shot.model_name = None
                    shot.model_version = None
                    shot.prediction_method = None
                    cleared_count += 1
                    
        print(f"Scored {full_context_shots} shots with full PBP context, {fallback_shots} shots with reduced-context fallback.")
        print(f"Cleared {cleared_count} blocked/ineligible shots.")
        print("Saving updates to the database...")
        db.session.commit()
        print(f"Successfully populated xG values for {updated_count} unblocked shots across {len(shots_by_game)} games!")

if __name__ == '__main__':
    main()
