"""LAN multiplayer lobby screens (Host / Join)."""
from __future__ import annotations

import random
from dataclasses import dataclass

import pygame

from src.network import protocol
from src.network.client import NetworkClient
from src.network.server import RelayServer
from src.ui.display import toggle_fullscreen

_ALL_CIVS: tuple[str, ...] = ("Blue", "Red", "Yellow", "Purple", "Black")

_CIV_COLORS: dict[str, tuple[int, int, int]] = {
    "Blue": (60, 120, 220),
    "Red": (220, 60, 60),
    "Yellow": (220, 200, 30),
    "Purple": (160, 60, 220),
    "Black": (70, 70, 70),
}

_BG = (17, 24, 36)
_GOLD = (220, 180, 60)
_CONNECT_TIMEOUT_MS = 20_000


@dataclass(slots=True)
class MultiplayerResult:
    role: str
    client: NetworkClient
    seed: int
    my_civ: str
    enemy_civ: str
    server: RelayServer | None = None


class MultiplayerMenu:
    """Runs LAN setup flow and returns launch parameters for Game."""

    def __init__(self) -> None:
        self._ft = pygame.font.SysFont("georgia", 38, bold=True)
        self._fm = pygame.font.SysFont("georgia", 24)
        self._fs = pygame.font.SysFont("monospace", 19)
        self._fxs = pygame.font.SysFont("georgia", 15)
        self._screen_size = (1280, 720)

    def run(self, screen: pygame.Surface, clock: pygame.time.Clock) -> MultiplayerResult | None:
        while True:
            choice = self._choice_screen(screen, clock)
            if choice == "back":
                return None
            if choice == "host":
                result = self._host_screen(screen, clock)
            else:
                result = self._join_screen(screen, clock)
            if result is not None:
                return result

    def _choice_screen(self, screen: pygame.Surface, clock: pygame.time.Clock) -> str:
        buttons = [("host", "Oyun Kur"), ("join", "Oyuna Katil"), ("back", "Geri")]
        sel = 0
        while True:
            self._screen_size = screen.get_size()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return "back"
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F11 or (
                        ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (ev.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if ev.key == pygame.K_ESCAPE:
                        return "back"
                    if ev.key in (pygame.K_UP, pygame.K_w):
                        sel = max(0, sel - 1)
                    if ev.key in (pygame.K_DOWN, pygame.K_s):
                        sel = min(len(buttons) - 1, sel + 1)
                    if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        return buttons[sel][0]
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    for i, (action, _) in enumerate(buttons):
                        if self._btn_rect(i, len(buttons)).collidepoint(ev.pos):
                            return action

            screen.fill(_BG)
            title = self._ft.render("Cok Oyunculu - LAN", True, (220, 210, 190))
            sw, _ = self._screen_size
            screen.blit(title, ((sw - title.get_width()) // 2, 170))

            mx, my = pygame.mouse.get_pos()
            for i, (_, label) in enumerate(buttons):
                r = self._btn_rect(i, len(buttons))
                self._draw_btn(screen, r, label, selected=(i == sel), hover=r.collidepoint(mx, my))

            pygame.display.flip()
            clock.tick(60)

    def _host_screen(self, screen: pygame.Surface, clock: pygame.time.Clock) -> MultiplayerResult | None:
        server = RelayServer()
        local_ip = server.start()
        host_client = NetworkClient()
        if not host_client.connect("127.0.0.1"):
            server.stop()
            return None

        selected_civ = "Blue"
        host_client.send({"type": protocol.MSG_HELLO, "role": "host", "civ_pref": selected_civ})
        guest_seen = False
        guest_pref = "Red"
        status = "Misafir baglantisi bekleniyor..."
        dots_tick = 0

        while True:
            self._screen_size = screen.get_size()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    host_client.close()
                    server.stop()
                    return None
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F11 or (
                        ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (ev.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if ev.key == pygame.K_ESCAPE:
                        host_client.close()
                        server.stop()
                        return None
                    if ev.key == pygame.K_RETURN and guest_seen:
                        return self._host_start_match(host_client, server, selected_civ, guest_pref)
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if self._back_btn_rect().collidepoint(ev.pos):
                        host_client.close()
                        server.stop()
                        return None
                    if self._start_btn_rect().collidepoint(ev.pos) and guest_seen:
                        return self._host_start_match(host_client, server, selected_civ, guest_pref)
                    for ci, civ in enumerate(_ALL_CIVS):
                        if self._civ_btn_rect(ci).collidepoint(ev.pos):
                            selected_civ = civ
                            host_client.send(
                                {"type": protocol.MSG_HELLO, "role": "host", "civ_pref": selected_civ}
                            )

            for msg in host_client.poll():
                if msg.get("type") != protocol.MSG_HELLO:
                    continue
                if msg.get("server"):
                    continue
                if msg.get("role") == "guest":
                    guest_seen = True
                    pref = str(msg.get("civ_pref", ""))
                    if pref in _ALL_CIVS:
                        guest_pref = pref
                    status = f"Misafir baglandi (tercih: {guest_pref}). Baslat icin Enter/tikla."

            if not guest_seen and server.client_count >= 2:
                status = "Misafir baglandi, medeniyet bilgisi bekleniyor..."

            screen.fill(_BG)
            dots_tick += 1
            sw, _ = self._screen_size

            t = self._ft.render("Oyun Kur", True, (220, 210, 190))
            screen.blit(t, ((sw - t.get_width()) // 2, 56))

            panel_w, panel_h = 660, 86
            panel_x = (sw - panel_w) // 2
            panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            pygame.draw.rect(panel, (30, 42, 60, 220), panel.get_rect(), border_radius=12)
            pygame.draw.rect(panel, (60, 100, 160, 255), panel.get_rect(), 2, border_radius=12)
            screen.blit(panel, (panel_x, 122))

            ip_surf = self._fs.render(f"IP: {local_ip}:{protocol.PORT}", True, (140, 220, 140))
            screen.blit(ip_surf, (panel_x + (panel_w - ip_surf.get_width()) // 2, 142))
            hint = self._fxs.render("Arkadasiniz bu adrese baglanmali", True, (160, 200, 160))
            screen.blit(hint, (panel_x + (panel_w - hint.get_width()) // 2, 172))
            local_hint = self._fxs.render("Ayni PC icin: 127.0.0.1:5555", True, (180, 210, 228))
            screen.blit(local_hint, (panel_x + (panel_w - local_hint.get_width()) // 2, 188))

            civ_lbl = self._fm.render("Medeniyet:", True, (200, 200, 200))
            screen.blit(civ_lbl, ((sw - civ_lbl.get_width()) // 2, 236))
            for ci, civ in enumerate(_ALL_CIVS):
                cr = self._civ_btn_rect(ci)
                color = _CIV_COLORS.get(civ, (120, 120, 120))
                is_sel = civ == selected_civ
                pygame.draw.rect(screen, color, cr, border_radius=9)
                pygame.draw.rect(screen, (255, 255, 80) if is_sel else (60, 60, 80), cr, 4 if is_sel else 1, 9)
                ln = self._fxs.render(civ, True, (255, 255, 255))
                screen.blit(ln, (cr.x + (cr.width - ln.get_width()) // 2, cr.y + (cr.height - ln.get_height()) // 2))

            n_dots = (dots_tick // 22) % 4
            status_line = status if guest_seen else (status + ("." * n_dots))
            wait_txt = self._fm.render(status_line, True, _GOLD)
            screen.blit(wait_txt, ((sw - wait_txt.get_width()) // 2, 360))

            self._draw_btn(screen, self._start_btn_rect(), "Baslat", selected=guest_seen, hover=False)
            self._draw_btn(screen, self._back_btn_rect(), "< Geri")

            pygame.display.flip()
            clock.tick(60)

    def _host_start_match(
        self,
        host_client: NetworkClient,
        server: RelayServer,
        host_civ: str,
        guest_pref: str,
    ) -> MultiplayerResult:
        available = [c for c in _ALL_CIVS if c != host_civ]
        guest_civ = guest_pref if guest_pref in available else (available[0] if available else "Red")
        ai_civs = [c for c in _ALL_CIVS if c not in (host_civ, guest_civ)][:2]
        seed = random.randint(1, 2_147_483_647)
        civs = {host_civ: 0, guest_civ: 1}
        for idx, civ in enumerate(ai_civs, start=2):
            civs[civ] = idx
        game_start_msg = {
            "type": protocol.MSG_GAME_START,
            "seed": seed,
            "civs": civs,
            "host_civ": host_civ,
            "guest_civ": guest_civ,
            "ai_civs": ai_civs,
        }
        host_client.send(game_start_msg)
        return MultiplayerResult(
            role="host",
            client=host_client,
            seed=seed,
            my_civ=host_civ,
            enemy_civ=guest_civ,
            server=server,
        )

    def _join_screen(self, screen: pygame.Surface, clock: pygame.time.Clock) -> MultiplayerResult | None:
        ip_text = ""
        selected_civ = "Red"
        status = ""
        error = ""
        connecting = False
        guest_client: NetworkClient | None = None
        connect_ts = 0

        while True:
            self._screen_size = screen.get_size()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    if guest_client:
                        guest_client.close()
                    return None

                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F11 or (
                        ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)
                        and (ev.mod & pygame.KMOD_ALT)
                    ):
                        screen = toggle_fullscreen()
                        continue
                    if ev.key == pygame.K_ESCAPE:
                        if guest_client:
                            guest_client.close()
                        return None
                    if not connecting:
                        if ev.key == pygame.K_BACKSPACE:
                            ip_text = ip_text[:-1]
                        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            guest_client, connecting, status, error, connect_ts = self._try_connect(
                                ip_text, selected_civ, guest_client
                            )
                        elif ev.unicode and (ev.unicode.isdigit() or ev.unicode in ".:abcdefABCDEF"):
                            ip_text += ev.unicode

                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if self._back_btn_rect().collidepoint(ev.pos):
                        if guest_client:
                            guest_client.close()
                        return None
                    if self._connect_btn_rect().collidepoint(ev.pos) and not connecting:
                        guest_client, connecting, status, error, connect_ts = self._try_connect(
                            ip_text, selected_civ, guest_client
                        )
                    for ci, civ in enumerate(_ALL_CIVS):
                        if self._civ_btn_rect(ci).collidepoint(ev.pos):
                            selected_civ = civ

            if connecting and guest_client:
                if pygame.time.get_ticks() - connect_ts > _CONNECT_TIMEOUT_MS:
                    guest_client.close()
                    guest_client = None
                    connecting = False
                    status = ""
                    error = "Baglanti zaman asimi."
                else:
                    for msg in guest_client.poll():
                        if msg.get("type") != protocol.MSG_GAME_START:
                            continue
                        seed = int(msg.get("seed", 1))
                        host_civ = str(msg.get("host_civ", "Blue"))
                        guest_civ = str(msg.get("guest_civ", selected_civ))
                        civ_map = msg.get("civs", {})
                        if isinstance(civ_map, dict):
                            if guest_civ not in civ_map:
                                for civ_name, civ_idx in civ_map.items():
                                    if int(civ_idx) == 1:
                                        guest_civ = str(civ_name)
                            if host_civ not in civ_map:
                                for civ_name, civ_idx in civ_map.items():
                                    if int(civ_idx) == 0:
                                        host_civ = str(civ_name)
                        return MultiplayerResult(
                            role="guest",
                            client=guest_client,
                            seed=seed,
                            my_civ=guest_civ,
                            enemy_civ=host_civ,
                            server=None,
                        )

            screen.fill(_BG)
            sw, _ = self._screen_size

            t = self._ft.render("Oyuna Katil", True, (220, 210, 190))
            screen.blit(t, ((sw - t.get_width()) // 2, 86))

            lbl = self._fm.render("Sunucu IP:", True, (200, 200, 200))
            screen.blit(lbl, ((sw - lbl.get_width()) // 2, 158))

            box = self._ip_input_rect()
            pygame.draw.rect(screen, (24, 36, 52), box, border_radius=8)
            pygame.draw.rect(screen, (60, 120, 200) if not connecting else (60, 80, 60), box, 2, 8)
            cursor = "_" if not connecting and (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            ip_surf = self._fs.render(ip_text + cursor, True, (220, 230, 248))
            screen.blit(ip_surf, (box.x + 14, box.y + (box.height - ip_surf.get_height()) // 2))

            civ_lbl = self._fm.render(f"Medeniyet tercihi: {selected_civ}", True, (212, 212, 212))
            screen.blit(civ_lbl, ((sw - civ_lbl.get_width()) // 2, 248))
            for ci, civ in enumerate(_ALL_CIVS):
                cr = self._civ_btn_rect(ci)
                color = _CIV_COLORS.get(civ, (120, 120, 120))
                is_sel = civ == selected_civ
                pygame.draw.rect(screen, color, cr, border_radius=9)
                pygame.draw.rect(screen, (255, 255, 80) if is_sel else (60, 60, 80), cr, 4 if is_sel else 1, 9)
                ln = self._fxs.render(civ, True, (255, 255, 255))
                screen.blit(ln, (cr.x + (cr.width - ln.get_width()) // 2, cr.y + (cr.height - ln.get_height()) // 2))

            conn_r = self._connect_btn_rect()
            if connecting:
                self._draw_btn(screen, conn_r, "Baglaniyor...")
            else:
                self._draw_btn(
                    screen,
                    conn_r,
                    "Baglan",
                    selected=bool(ip_text.strip()),
                    hover=conn_r.collidepoint(pygame.mouse.get_pos()),
                )

            if error:
                er = self._fm.render(error, True, (220, 80, 80))
                screen.blit(er, ((sw - er.get_width()) // 2, 452))
            elif status:
                st = self._fm.render(status, True, _GOLD)
                screen.blit(st, ((sw - st.get_width()) // 2, 452))

            hint = self._fxs.render("Ornek: 192.168.1.10:5555 veya 127.0.0.1:5555", True, (120, 130, 150))
            screen.blit(hint, ((sw - hint.get_width()) // 2, 488))

            self._draw_btn(screen, self._back_btn_rect(), "< Geri")

            pygame.display.flip()
            clock.tick(60)

    def _try_connect(
        self,
        ip_text: str,
        selected_civ: str,
        old_client: NetworkClient | None,
    ) -> tuple[NetworkClient | None, bool, str, str, int]:
        if old_client:
            old_client.close()
        ip = ip_text.strip()
        if not ip:
            return None, False, "", "Bir IP girin.", 0
        host, port = self._parse_host_port(ip)
        client = NetworkClient()
        if not client.connect(host, port=port):
            return None, False, "", "Baglanti basarisiz. Ayni PC icin 127.0.0.1:5555 deneyin.", 0
        client.send({"type": protocol.MSG_HELLO, "role": "guest", "civ_pref": selected_civ})
        return client, True, "Host'tan oyun bilgisi bekleniyor...", "", pygame.time.get_ticks()

    def _parse_host_port(self, value: str) -> tuple[str, int]:
        text = value.strip()
        if not text:
            return "127.0.0.1", protocol.PORT
        if ":" in text:
            host_part, port_part = text.rsplit(":", 1)
            host = host_part.strip() or "127.0.0.1"
            if port_part.isdigit():
                return host, int(port_part)
            return host, protocol.PORT
        return text, protocol.PORT

    def _btn_rect(self, i: int, _total: int) -> pygame.Rect:
        sw, _ = self._screen_size
        bw, bh = 340, 62
        bx = (sw - bw) // 2
        by = 300 + i * 84
        return pygame.Rect(bx, by, bw, bh)

    def _civ_btn_rect(self, ci: int) -> pygame.Rect:
        sw, _ = self._screen_size
        btn_w, btn_h = 96, 48
        spacing = 16
        total_w = len(_ALL_CIVS) * btn_w + (len(_ALL_CIVS) - 1) * spacing
        sx = (sw - total_w) // 2
        return pygame.Rect(sx + ci * (btn_w + spacing), 286, btn_w, btn_h)

    def _back_btn_rect(self) -> pygame.Rect:
        return pygame.Rect(32, 32, 110, 42)

    def _start_btn_rect(self) -> pygame.Rect:
        sw, _ = self._screen_size
        return pygame.Rect((sw - 220) // 2, 412, 220, 56)

    def _ip_input_rect(self) -> pygame.Rect:
        sw, _ = self._screen_size
        w = 380
        return pygame.Rect((sw - w) // 2, 194, w, 52)

    def _connect_btn_rect(self) -> pygame.Rect:
        sw, _ = self._screen_size
        w = 200
        return pygame.Rect((sw - w) // 2, 370, w, 54)

    def _draw_btn(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        text: str,
        *,
        selected: bool = False,
        hover: bool = False,
    ) -> None:
        if selected:
            fill, border, tc = (74, 126, 178), (22, 54, 86), (245, 249, 252)
        elif hover:
            fill, border, tc = (92, 142, 192), (30, 64, 98), (250, 252, 255)
        else:
            fill, border, tc = (126, 174, 220), (44, 86, 126), (18, 28, 40)
        pygame.draw.rect(screen, fill, rect, border_radius=11)
        pygame.draw.rect(screen, border, rect, 2, border_radius=11)
        lbl = self._fm.render(text, True, tc)
        screen.blit(lbl, (rect.x + (rect.width - lbl.get_width()) // 2, rect.y + (rect.height - lbl.get_height()) // 2))
