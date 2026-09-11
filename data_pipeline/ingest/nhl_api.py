import os
import json
import time
import urllib.request
import urllib.error
import logging

logger = logging.getLogger(__name__)

class NHLApiClient:
    """Client for downloading, validating, and caching raw JSON feeds from the NHL APIs."""
    
    def __init__(self, raw_data_dir=None):
        if raw_data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.raw_data_dir = os.path.join(base_dir, 'data', 'raw')
        else:
            self.raw_data_dir = raw_data_dir
            
        os.makedirs(self.raw_data_dir, exist_ok=True)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def _fetch_url(self, url: str, max_retries: int = 3, backoff_factor: float = 1.0) -> dict:
        """
        Helper to fetch a URL with bounded exponential backoff for transient failures (429, 500, 502, 503, 504, timeouts).
        Immediately returns None for HTTP 404 without endless retries.
        """
        logger.info(f"Fetching remote URL: {url}")
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    if response.status == 200:
                        return json.loads(response.read().decode('utf-8'))
                    else:
                        logger.error(f"HTTP status {response.status} fetching {url}")
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.warning(f"HTTP 404 Not Found fetching {url}")
                    return None
                elif e.code in [429, 500, 502, 503, 504]:
                    logger.warning(f"HTTP {e.code} transient error fetching {url} (Attempt {attempt}/{max_retries})")
                else:
                    logger.error(f"HTTP error {e.code} fetching {url}: {e.reason}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                logger.warning(f"Network error fetching {url}: {e} (Attempt {attempt}/{max_retries})")
            except Exception as e:
                logger.exception(f"Unexpected exception fetching {url}: {e}")
                return None

            if attempt < max_retries:
                sleep_time = backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_time)

        logger.error(f"Exhausted {max_retries} retries for URL: {url}")
        return None

    def _validate_json_file(self, filepath: str, validator_fn=None) -> dict:
        """Reads cached file and validates format. Returns parsed dict if valid, else None."""
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"Cached JSON at {filepath} is not a dictionary. Invalidating cache.")
                return None
            if validator_fn and not validator_fn(data):
                logger.warning(f"Cached JSON at {filepath} failed schema validation. Invalidating cache.")
                return None
            return data
        except Exception as e:
            logger.warning(f"Failed to parse cached JSON at {filepath}: {e}. Invalidating cache.")
            return None

    def get_season_schedule(self, team_abbr: str, season: str, force_refresh: bool = False) -> dict:
        """Fetches and caches the schedule of a team for a season."""
        filename = f"schedule_{team_abbr}_{season}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh:
            data = self._validate_json_file(filepath, lambda d: isinstance(d.get("games"), list))
            if data is not None:
                logger.debug(f"Loading valid cached schedule from {filepath}")
                return data
                
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
        
        if not force_refresh:
            data = self._validate_json_file(filepath, lambda d: (d.get("id") == game_id or d.get("gameId") == game_id) and isinstance(d.get("plays"), list))
            if data is not None:
                logger.debug(f"Loading valid cached play-by-play from {filepath}")
                return data
                
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
        
        if not force_refresh:
            data = self._validate_json_file(filepath, lambda d: isinstance(d.get("data"), list))
            if data is not None:
                logger.debug(f"Loading valid cached shifts from {filepath}")
                return data
                
        url = f"https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={game_id}"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached shifts to {filepath}")
        return data

    def get_season_roster(self, team_abbr: str, season: str, force_refresh: bool = False) -> dict:
        """Fetches and caches the roster of a team for a season."""
        filename = f"roster_{team_abbr}_{season}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh:
            data = self._validate_json_file(filepath, lambda d: any(k in d for k in ["forwards", "defensemen", "goalies"]))
            if data is not None:
                logger.debug(f"Loading valid cached roster from {filepath}")
                return data
                
        url = f"https://api-web.nhle.com/v1/roster/{team_abbr}/{season}"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached roster to {filepath}")
        return data

    def get_boxscore(self, game_id: int, force_refresh: bool = False) -> dict:
        """Fetches and caches the boxscore for a game."""
        filename = f"boxscore_{game_id}.json"
        filepath = os.path.join(self.raw_data_dir, filename)
        
        if not force_refresh:
            data = self._validate_json_file(filepath, lambda d: (d.get("id") == game_id or d.get("gameId") == game_id or "homeTeam" in d))
            if data is not None:
                logger.debug(f"Loading valid cached boxscore from {filepath}")
                return data
                
        url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
        data = self._fetch_url(url)
        if data:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Cached boxscore to {filepath}")
        return data

    def is_game_cached(self, game_id: int) -> bool:
        """Returns True if valid play-by-play and shifts data are already cached on disk."""
        pbp_path = os.path.join(self.raw_data_dir, f"pbp_{game_id}.json")
        shifts_path = os.path.join(self.raw_data_dir, f"shifts_{game_id}.json")
        pbp_valid = self._validate_json_file(pbp_path, lambda d: (d.get("id") == game_id or d.get("gameId") == game_id) and isinstance(d.get("plays"), list)) is not None
        shifts_valid = self._validate_json_file(shifts_path, lambda d: isinstance(d.get("data"), list)) is not None
        return pbp_valid and shifts_valid

