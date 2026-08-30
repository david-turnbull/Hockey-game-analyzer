import os
import sys

# Append project root directory to sys.path so we can import from the 'app' module
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Team, Player

def initialize():
    """Initializes the SQLite database and seeds default demonstration records."""
    app = create_app('development')
    
    with app.app_context():
        print("Initializing database tables...")
        # Re-create tables cleanly
        db.drop_all()
        db.create_all()
        print("Tables created successfully!")

        # Seed demonstration team: Calgary Flames (team_id 20 in NHL API)
        cgy = Team.query.filter_by(team_id=20).first()
        if not cgy:
            print("Seeding team: Calgary Flames...")
            cgy = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
            db.session.add(cgy)

            # Seed a couple of notable Flames players
            players = [
                Player(
                    player_id=8476456, 
                    first_name='Jonathan', 
                    last_name='Huberdeau', 
                    position='L', 
                    shoots_catches='L', 
                    current_team=cgy
                ),
                Player(
                    player_id=8475172, 
                    first_name='Nazem', 
                    last_name='Kadri', 
                    position='C', 
                    shoots_catches='L', 
                    current_team=cgy
                )
            ]
            db.session.add_all(players)
            
            db.session.commit()
            print("Seeding complete.")
        else:
            print("Demonstration data already exists. Skipping seed.")

if __name__ == '__main__':
    initialize()
