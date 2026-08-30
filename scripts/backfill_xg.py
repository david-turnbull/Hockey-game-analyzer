import os
import sys

# Append project root directory to sys.path so we can import from the 'app' module
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Shot
from app.services.xg_service import XGService

def main():
    app = create_app('development')
    
    with app.app_context():
        print("Querying all shots from the database...")
        shots = Shot.query.all()
        total_shots = len(shots)
        print(f"Found {total_shots} shots. Populating Expected Goals (xG)...")
        
        updated_count = 0
        for i, shot in enumerate(shots):
            xg_val = XGService.calculate_shot_xg(
                distance=shot.distance,
                angle=shot.angle,
                shot_type=shot.shot_type,
                strength_state=shot.strength_state,
                empty_net=shot.empty_net
            )
            shot.xg = xg_val
            updated_count += 1
            
            if (i + 1) % 500 == 0:
                print(f"Processed {i + 1}/{total_shots} shots...")
                
        print("Saving updates to the database...")
        db.session.commit()
        print(f"Successfully populated xG values for {updated_count} shot attempts!")

if __name__ == '__main__':
    main()
