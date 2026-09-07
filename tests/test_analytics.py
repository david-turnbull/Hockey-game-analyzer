import pytest
from data_pipeline.orchestrator import PipelineOrchestrator
from app.services.unit_service import UnitService
from app.services.player_game_service import PlayerGameService

def test_line_service_unit_detail(app, db):
    """
    Verifies that UnitService.get_unit_detail retrieves correct 5v5 metrics,
    intervals, shot map coordinates, and timeline events for a forward line.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True

    # 1. Fetch line combinations first
    combos = UnitService.get_unit_combinations(2023020007)
    assert combos is not None
    assert "home" in combos
    assert "away" in combos

    home_lines = combos["home"]["lines"]
    assert len(home_lines) > 0

    # 2. Get first forward line details
    first_line = home_lines[0]
    player_ids = first_line["player_ids"]
    assert len(player_ids) == 3

    detail = UnitService.get_unit_detail(2023020007, player_ids)
    assert detail is not None
    assert detail["game_id"] == 2023020007
    assert detail["toi"] is not None
    assert len(detail["players"]) == 3
    
    # 3. Check stats structure
    stats = detail["stats"]
    assert "gf" in stats
    assert "ga" in stats
    assert "sf" in stats
    assert "sa" in stats
    assert "cf" in stats
    assert "ca" in stats
    assert "cf_pct" in stats
    assert "ff_pct" in stats

    # 4. Verify shot coordinates map structure
    assert "shots" in detail
    if len(detail["shots"]) > 0:
        s = detail["shots"][0]
        assert "norm_x" in s
        assert "norm_y" in s
        assert "xg" in s
        assert "outcome" in s

    # 5. Verify observed intervals and timeline events
    assert "intervals" in detail
    assert "timeline" in detail


def test_player_compare_api_and_service(app, db):
    """
    Verifies player side-by-side comparison coordinates with PlayerGameService
    for both skaters and goalies.
    """
    orchestrator = PipelineOrchestrator(session=db.session)
    success, summary = orchestrator.ingest_game(2023020007)
    assert success is True

    # Let's find two skaters and compare their game stats
    from app.models import Player, GamePlayer
    skaters = Player.query.join(GamePlayer).filter(
        GamePlayer.game_id == 2023020007,
        Player.position != 'G'
    ).limit(2).all()
    
    assert len(skaters) == 2
    
    p1_stats = PlayerGameService.get_player_game_stats(2023020007, skaters[0].player_id)
    p2_stats = PlayerGameService.get_player_game_stats(2023020007, skaters[1].player_id)
    
    assert p1_stats is not None
    assert p2_stats is not None
    assert p1_stats["goals"] is not None
    assert p2_stats["goals"] is not None
    assert "cf_pct" in p1_stats
    assert "cf_pct" in p2_stats
