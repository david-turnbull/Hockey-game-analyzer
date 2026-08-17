import os
import json
import urllib.request
import logging

logger = logging.getLogger(__name__)

class NHLApiClient:
    """Client for downloading and caching raw JSON feeds from the NHL APIs."""
    
    def __init__(self, raw_data_dir=None):
        # Default to data/raw in the project root
        if raw_data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.raw_data_dir = os.path.join(base_dir, 'data', 'raw')
        else:
            self.raw_data_dir = raw_data_dir
            
        os.makedirs(self.raw_data_dir, exist_ok=True)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def _fetch_url(self, url: str) -> dict:
        """Helper to fetch a URL and return parsed JSON."""
        logger.info(f"Fetching remote URL: {url}")
        try:
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    return json.loads(response.read().decode('utf-8'))
                else:
                    logger.error(f"HTTP error status {response.status} fetching {url}")
        except Exception as e:
            logger.exception(f"Exception raised fetching {url}")
        return None

    def get_season_schedule(self, team_abbr: str, season: str, force_refresh: bool = False) -> dict:
        """Fetches and caches the schedule of a team for a season."""
        filename = f"schedule_{team_abbr}_{season}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh and os.path.exists(filepath):
            logger.debug(f"Loading cached schedule from {filepath}")
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{team_abbr}/{season}"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached schedule to {filepath}")
        return data

    def get_play_by_play(self, game_id: int, force_refresh: bool = False) -> dict:
        """Fetches and caches the play-by-play data for a game."""
        filename = f"pbp_{game_id}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh and os.path.exists(filepath):
            logger.debug(f"Loading cached play-by-play from {filepath}")
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached play-by-play to {filepath}")
        return data

    def get_shifts(self, game_id: int, force_refresh: bool = False) -> dict:
        """Fetches and caches the shift chart data for a game."""
        filename = f"shifts_{game_id}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh and os.path.exists(filepath):
            logger.debug(f"Loading cached shifts from {filepath}")
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        url = f"https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached shifts to {filepath}")
        return data
