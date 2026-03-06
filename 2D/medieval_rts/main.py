import os

import pygame

from game import Game
from settings import FULLSCREEN_DEFAULT, TITLE
from src.ui.civ_select import CivilizationSelectScreen
from src.ui.campaign_menu import CampaignMenu
from src.ui.display import apply_display_mode, ensure_display_surface
from src.ui.graphics_menu import GraphicsMenu
from src.ui.menu import MainMenu
from src.ui.multiplayer_menu import MultiplayerMenu
from src.systems.replay import ReplayManager
from version import VERSION


def main() -> None:
    pygame.init()
    screen = apply_display_mode(fullscreen=FULLSCREEN_DEFAULT)
    pygame.display.set_caption(f"{TITLE} v{VERSION}")
    clock = pygame.time.Clock()
    menu = MainMenu()
    civ_select = CivilizationSelectScreen()
    multiplayer_menu = MultiplayerMenu()
    campaign_menu = CampaignMenu()
    graphics_menu = GraphicsMenu()
    replay_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replays")

    running = True
    while running:
        screen = ensure_display_surface()
        action = menu.run(screen, clock)
        screen = ensure_display_surface()
        if action == MainMenu.ACTION_EXIT:
            running = False
            break
        if action == MainMenu.ACTION_GRAPHICS:
            screen = ensure_display_surface()
            g_action = graphics_menu.run(screen, clock)
            screen = ensure_display_surface()
            pygame.display.set_caption(f"{TITLE} v{VERSION}")
            if g_action == GraphicsMenu.ACTION_EXIT:
                running = False
                break
            continue
        if action == MainMenu.ACTION_TUTORIAL:
            civ = civ_select.run(screen, clock)
            screen = ensure_display_surface()
            if not civ:
                continue
            Game(player_civilization=civ, scenario="tutorial", replay_mode=ReplayManager.MODE_RECORD).run()
            screen = ensure_display_surface()
            pygame.display.set_caption(f"{TITLE} v{VERSION}")
            continue
        if action == MainMenu.ACTION_CAMPAIGN:
            choice = campaign_menu.run(screen, clock)
            screen = ensure_display_surface()
            if choice == CampaignMenu.ACTION_EXIT:
                running = False
                break
            if choice == CampaignMenu.ACTION_BACK:
                continue
            civ = civ_select.run(screen, clock)
            screen = ensure_display_surface()
            if not civ:
                continue
            Game(
                player_civilization=civ,
                scenario="campaign",
                campaign_mission=int(choice),
                replay_mode=ReplayManager.MODE_RECORD,
            ).run()
            screen = ensure_display_surface()
            pygame.display.set_caption(f"{TITLE} v{VERSION}")
            continue
        if action == MainMenu.ACTION_REPLAY:
            replay_path = ReplayManager.latest_replay_file(replay_dir)
            if not replay_path:
                continue
            header = ReplayManager.load_header(replay_path)
            civ = str(header.get("player_civilization", "Blue"))
            scenario = str(header.get("scenario", "skirmish"))
            campaign_mission = int(header.get("campaign_mission", 0))
            seed = int(header.get("seed", 1))
            Game(
                player_civilization=civ,
                map_seed=seed,
                scenario=scenario,
                campaign_mission=campaign_mission,
                replay_mode=ReplayManager.MODE_PLAYBACK,
                replay_path=replay_path,
            ).run()
            screen = ensure_display_surface()
            pygame.display.set_caption(f"{TITLE} v{VERSION}")
            continue
        if action == MainMenu.ACTION_MULTIPLAYER:
            mp = multiplayer_menu.run(screen, clock)
            screen = ensure_display_surface()
            if mp is None:
                continue
            try:
                Game(
                    player_civilization=mp.my_civ,
                    map_seed=mp.seed,
                    net=mp.client,
                    player_id=0 if mp.role == "host" else 1,
                    online_opponent_civ=mp.enemy_civ,
                ).run()
            finally:
                mp.client.close()
                if mp.server is not None:
                    mp.server.stop()
            screen = ensure_display_surface()
            pygame.display.set_caption(f"{TITLE} v{VERSION}")
            continue

        civ = civ_select.run(screen, clock)
        screen = ensure_display_surface()
        if not civ:
            continue
        Game(player_civilization=civ).run()
        screen = ensure_display_surface()
        pygame.display.set_caption(f"{TITLE} v{VERSION}")

    pygame.quit()


if __name__ == "__main__":
    main()
