from sqlalchemy import or_
from app.models import db, Player, Team, Shift, Event

class PlayerProfileService:
    """Service for compiling player game biographical metadata and resolving team assignments historically."""

    @staticmethod
    def resolve_profile_metadata(game, player, gp) -> dict:
        """
        Resolves player team, position historically and returns biographical metadata.
        """
        player_id = player.player_id
        game_id = game.game_id
        
        if gp:
            player_team = gp.team
            is_home_player = (gp.team_id == game.home_team_id)
            position = gp.position or player.position
        else:
            # Fallback to valid shift team
            first_shift = Shift.query.filter(
                Shift.game_id == game_id,
                Shift.player_id == player_id,
                Shift.is_anomaly == False,
                Shift.duration > 0
            ).first()
            if first_shift:
                team_id = first_shift.team_id
                player_team = db.session.get(Team, team_id)
                is_home_player = (team_id == game.home_team_id)
                position = player.position
            else:
                # Fallback to valid game-specific event/team evidence
                first_event = Event.query.filter(
                    Event.game_id == game_id,
                    or_(
                        Event.primary_player_id == player_id,
                        Event.secondary_player_id == player_id,
                        Event.assist1_player_id == player_id,
                        Event.assist2_player_id == player_id
                    )
                ).first()
                if first_event:
                    team_id = first_event.team_id
                    player_team = db.session.get(Team, team_id)
                    is_home_player = (team_id == game.home_team_id)
                    position = player.position
                else:
                    player_team = None
                    is_home_player = False
                    position = player.position
                    
        height_str = f"{player.height_in_inches // 12}'{player.height_in_inches % 12}\"" if player.height_in_inches else None
        weight_str = f"{player.weight_in_pounds} lb" if player.weight_in_pounds else None
        sweater_number = gp.sweater_number if (gp and gp.sweater_number) else player.sweater_number
        
        return {
            "player_id": player.player_id,
            "name": player.full_name,
            "position": position,
            "shoots_catches": player.shoots_catches,
            "headshot_url": player.headshot_url,
            "sweater_number": sweater_number,
            "height_str": height_str,
            "weight_str": weight_str,
            "birth_date": player.birth_date,
            "birth_city": player.birth_city,
            "birth_country": player.birth_country,
            "team_name": player_team.name if player_team else "Unknown",
            "team_abbrev": player_team.abbreviation if player_team else "UNK",
            "team_id": player_team.team_id if player_team else None,
            "is_home": is_home_player
        }
