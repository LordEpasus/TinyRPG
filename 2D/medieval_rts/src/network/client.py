"""Threaded TCP client for LAN multiplayer."""
from __future__ import annotations

import queue
import socket
import threading
from typing import Any

from . import protocol


class NetworkClient:
    """Simple non-blocking client with send queue + polled receive queue."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._recv_q: queue.Queue[dict[str, Any]] = queue.Queue()
        self._send_q: queue.Queue[bytes] = queue.Queue()
        self._running = False
        self._client_id = 0

    @property
    def connected(self) -> bool:
        return self._running

    @property
    def client_id(self) -> int:
        return self._client_id

    def connect(self, host_ip: str, *, port: int = protocol.PORT, timeout: float = 8.0) -> bool:
        if self._running:
            return True
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(max(0.5, float(timeout)))
            sock.connect((host_ip.strip(), int(port)))
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = sock
            self._running = True
            threading.Thread(target=self._recv_loop, name="lan-client-recv", daemon=True).start()
            threading.Thread(target=self._send_loop, name="lan-client-send", daemon=True).start()
            return True
        except Exception:
            self.close()
            return False

    def send(self, msg: dict[str, Any]) -> None:
        if not self._running:
            return
        self._send_q.put(protocol.encode(msg))

    def poll(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        while True:
            try:
                out.append(self._recv_q.get_nowait())
            except queue.Empty:
                break
        return out

    def close(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _recv_loop(self) -> None:
        buf = ""
        while self._running:
            try:
                sock = self._sock
                if sock is None:
                    break
                raw = sock.recv(8192)
                if not raw:
                    break
                buf += raw.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    msg = protocol.decode(line)
                    if msg is None:
                        continue
                    if msg.get("type") == protocol.MSG_HELLO and msg.get("server"):
                        try:
                            self._client_id = int(msg.get("client_id", 0))
                        except Exception:
                            self._client_id = 0
                        continue
                    self._recv_q.put(msg)
            except (socket.timeout, BlockingIOError):
                pass
            except Exception:
                break
        self._running = False

    def _send_loop(self) -> None:
        while self._running:
            try:
                data = self._send_q.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                sock = self._sock
                if sock is None:
                    break
                sock.sendall(data)
            except Exception:
                self._running = False
                break
