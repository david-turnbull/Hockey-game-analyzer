import os
import json
from datetime import datetime
from app import create_app, db
from app.models import Player

def run():
    app = create_app()
    with app.app_context():
        roster_dir = 'data/raw'
        player_map = {}
        
        # Parse all cached roster JSON files
        for filename in os.listdir(roster_dir):
            if filename.startswith('roster_') and filename.endswith('.json'):
                filepath = os.path.join(roster_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    for category in ['forwards', 'defensemen', 'goalies']:
                        for p in data.get(category, []):
                            pid = p.get('id')
                            if pid:
                                player_map[pid] = p
                except Exception as e:
                    print(f"Failed to read {filename}: {e}")
        
        print(f"Loaded {len(player_map)} player profiles from cache.")
        
        # Match and update player records
        players = Player.query.all()
        updated_count = 0
        
        for p in players:
            p_data = player_map.get(p.player_id)
            if p_data:
                p.headshot_url = p_data.get('headshot')
                p.sweater_number = p_data.get('sweaterNumber')
                p.height_in_inches = p_data.get('heightInInches')
                p.weight_in_pounds = p_data.get('weightInPounds')
                
                bdate_str = p_data.get('birthDate')
                if bdate_str:
                    try:
                        p.birth_date = datetime.strptime(bdate_str, '%Y-%m-%d').date()
                    except ValueError:
                        pass
                
                # Retrieve default localization string for birth city
                birth_city_data = p_data.get('birthCity')
                if isinstance(birth_city_data, dict):
                    p.birth_city = birth_city_data.get('default')
                else:
                    p.birth_city = birth_city_data
                    
                p.birth_country = p_data.get('birthCountry')
                
                if p_data.get('shootsCatches'):
                    p.shoots_catches = p_data.get('shootsCatches')
                
                updated_count += 1
                
        db.session.commit()
        print(f"Successfully updated {updated_count} players in the database.")

if __name__ == '__main__':
    run()
