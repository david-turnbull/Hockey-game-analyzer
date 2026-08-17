import logging
from app import create_app
from app.models.base import db
from data_pipeline.ingest.nhl_api import NHLApiClient
from data_pipeline.transform.normalizer import DataNormalizer
from data_pipeline.validation.quality_checker import DataQualityChecker
from data_pipeline.loaders.db_loader import DatabaseLoader

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    """Orchestrates the NHL data pipeline phases: Ingest -> Transform -> Validate -> Load."""
    
    def __init__(self, raw_data_dir=None, session=None):
        self.api_client = NHLApiClient(raw_data_dir)
        self.normalizer = DataNormalizer()
        self.loader = DatabaseLoader(session)

    def ingest_game(self, game_id: int, force_refresh: bool = False) -> tuple:
        """
        Runs the full ingestion, transformation, validation, and loading pipeline for a single game.
        
        Returns:
            (success (bool), summary (dict))
        """
        logger.info(f"--- Starting Pipeline for Game ID: {game_id} ---")
        
        # 1. Ingest Phase
        pbp_raw = self.api_client.get_play_by_play(game_id, force_refresh=force_refresh)
        shifts_raw = self.api_client.get_shifts(game_id, force_refresh=force_refresh)
        
        if not pbp_raw:
            logger.error(f"Failed to fetch play-by-play data for game {game_id}. Aborting pipeline.")
            return False, {"error": "Missing play-by-play data"}
        if not shifts_raw:
            logger.warning(f"Failed to fetch shifts data for game {game_id}. Pipeline will proceed without shifts.")
            shifts_raw = {"data": [], "total": 0}
            
        # 2. Transform Phase
        try:
            # Game level
            game_model = self.normalizer.transform_game(pbp_raw)
            
            # Teams
            home_team_raw = pbp_raw["homeTeam"]
            away_team_raw = pbp_raw["awayTeam"]
            
            # Try to resolve full names from shifts if available
            home_name, away_name = None, None
            for shift in shifts_raw.get("data", []):
                if shift.get("teamId") == home_team_raw["id"] and shift.get("teamName"):
                    home_name = shift["teamName"]
                elif shift.get("teamId") == away_team_raw["id"] and shift.get("teamName"):
                    away_name = shift["teamName"]
                    
            home_team_model = self.normalizer.transform_team(home_team_raw["id"], home_team_raw["abbrev"], home_name)
            away_team_model = self.normalizer.transform_team(away_team_raw["id"], away_team_raw["abbrev"], away_name)
            teams_list = [home_team_model, away_team_model]
            
            # Players
            players_list = []
            for spot in pbp_raw.get("rosterSpots", []):
                players_list.append(self.normalizer.transform_player(spot))
            
            # Events & Shots
            events_list = []
            shots_list = []
            for play in pbp_raw.get("plays", []):
                event_model, shot_model = self.normalizer.transform_event(
                    play, game_id, home_team_raw["id"]
                )
                events_list.append(event_model)
                if shot_model:
                    shots_list.append(shot_model)
                    
            # Shifts
            shifts_list = []
            for shift_raw in shifts_raw.get("data", []):
                shifts_list.append(self.normalizer.transform_shift(shift_raw, game_id))
        except Exception as e:
            logger.exception(f"Exception during transformation phase for game {game_id}")
            return False, {"error": f"Transformation failure: {str(e)}"}
            
        # 3. Validation Phase
        checker = DataQualityChecker()
        
        # Validate game & teams & players
        checker.validate_game(game_model)
        for t in teams_list:
            checker.validate_team(t)
        for p in players_list:
            checker.validate_player(p)
            
        # Roster sets for foreign key checking
        known_player_ids = set(p.player_id for p in players_list)
        known_team_ids = set(t.team_id for t in teams_list)
        
        # Validate events & shots
        valid_events = []
        for event in events_list:
            if checker.validate_event(event, known_player_ids, known_team_ids):
                valid_events.append(event)
                
        valid_shots = []
        for shot in shots_list:
            if checker.validate_shot(shot, known_player_ids):
                valid_shots.append(shot)
                
        # Validate shifts
        valid_shifts = checker.validate_shifts(shifts_list)
        
        summary = checker.get_summary()
        
        # 4. Loading Phase
        if checker.rejected_records_count > (len(events_list) * 0.5) and len(events_list) > 0:
            logger.error(f"Game {game_id} rejected due to high record rejection rate (>50%).")
            return False, summary
            
        success = self.loader.load_game_data(
            game_model, teams_list, players_list, valid_events, valid_shots, valid_shifts
        )
        
        return success, summary

    def ingest_season(self, team_abbr: str, season: str, limit: int = None, force_refresh: bool = False) -> dict:
        """
        Orchestrates ingestion of a whole season schedule for a team.
        """
        logger.info(f"Ingesting season schedule for {team_abbr} {season}")
        schedule_data = self.api_client.get_season_schedule(team_abbr, season, force_refresh=force_refresh)
        
        if not schedule_data or "games" not in schedule_data:
            return {"error": "Failed to retrieve schedule"}
            
        # Filter regular season games
        reg_games = [g for g in schedule_data["games"] if g.get("gameType") == 2]
        total_games = len(reg_games)
        
        if limit:
            reg_games = reg_games[:limit]
            
        logger.info(f"Found {total_games} regular season games. Ingesting {len(reg_games)} games.")
        
        results = {
            "total_games": total_games,
            "processed_games": 0,
            "successful_games": 0,
            "failed_games": 0,
            "game_summaries": {}
        }
        
        for game in reg_games:
            game_id = game["id"]
            results["processed_games"] += 1
            
            # Skip games that are not final/played
            # gameState can be 'OFF', 'FINAL', 'LIVE', 'PRV'
            if game.get("gameState") not in ['OFF', 'FINAL']:
                logger.info(f"Skipping game {game_id} because state is {game.get('gameState')} (not final).")
                results["failed_games"] += 1
                results["game_summaries"][game_id] = {"error": f"Game state is {game.get('gameState')}"}
                continue
                
            success, summary = self.ingest_game(game_id, force_refresh=force_refresh)
            if success:
                results["successful_games"] += 1
            else:
                results["failed_games"] += 1
            results["game_summaries"][game_id] = summary
            
        return results
