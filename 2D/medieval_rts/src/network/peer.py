"""
NetworkPeer, NetworkHost, NetworkGuest — thread-safe TCP wrappers.

Architecture:
  - Background recv-thread reads from socket → puts parsed dicts into _recv_q
  - Background send-thread drains _send_q → writes bytes to socket
  - Main thread calls poll() to get incoming messages and send() to enqueue outgoing ones

Host flow  : NetworkHost.start() → wait_for_guest() → exchange messages → game
Guest flow : NetworkGuest.connect(ip) → receive game_start → game
"""
from __future__ import annotations

import queue
import socket
import threading

from . import protocol


def _local_ip() -> str:
    """Best-effort LAN IP detection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class NetworkPeer:
    """
    Shared base class.  After _start_threads(sock) is called the object is
    fully operational: send / poll work from any thread.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._recv_q: queue.Queue[dict] = queue.Queue()
        self._send_q: queue.Queue[bytes] = queue.Queue()
        self._running = False

    # ── Internal setup ────────────────────────────────────────────────────────

    def _start_threads(self, sock: socket.socket) -> None:
        self._sock = sock
        self._running = True
        threading.Thread(
            target=self._recv_loop, daemon=True, name="net-recv"
        ).start()
        threading.Thread(
            target=self._send_loop, daemon=True, name="net-send"
        ).start()

    def _recv_loop(self) -> None:
        buf = ""
        while self._running:
            try:
                assert self._sock is not None
                raw = self._sock.recv(8192)
                if not raw:
                    break
                buf += raw.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    msg = protocol.decode(line)
                    if msg is not None:
                        self._recv_q.put(msg)
            except (socket.timeout, BlockingIOError):
                pass
            except OSError:
                break
            except Exception:
                break
        self._running = False

    def _send_loop(self) -> None:
        while self._running:
            try:
                data = self._send_q.get(timeout=0.05)
                if self._sock:
                    self._sock.sendall(data)
            except queue.Empty:
                pass
            except OSError:
                self._running = False
                break
            except Exception:
                self._running = False
                break

    # ── Public API ────────────────────────────────────────────────────────────

    def send(self, msg: dict) -> None:
        """Queue a message for sending (non-blocking)."""
        if self._running:
            self._send_q.put(protocol.encode(msg))

    def poll(self) -> list[dict]:
        """Return all messages received since last poll (non-blocking)."""
        msgs: list[dict] = []
        while True:
            try:
                msgs.append(self._recv_q.get_nowait())
            except queue.Empty:
                break
        return msgs

    @property
    def connected(self) -> bool:
        return self._running

    def close(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


# ── Host ──────────────────────────────────────────────────────────────────────

class NetworkHost(NetworkPeer):
    """
    Runs a TCP server and accepts exactly one guest connection.
    Call start() first (non-blocking), then wait_for_guest().
    """

    def __init__(self, port: int = protocol.PORT) -> None:
        super().__init__()
        self._port = port
        self._server_sock: socket.socket | None = None
        self._guest_event = threading.Event()

    def start(self) -> str:
        """
        Bind the server socket and begin accepting in a daemon thread.
        Returns the LAN IP address the guest should connect to.
        """
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("", self._port))
        self._server_sock.listen(1)
        threading.Thread(
            target=self._accept_loop, daemon=True, name="net-accept"
        ).start()
        return _local_ip()

    def _accept_loop(self) -> None:
        try:
            assert self._server_sock is not None
            self._server_sock.settimeout(600)   # wait up to 10 min
            conn, _ = self._server_sock.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._start_threads(conn)
        except Exception:
            pass
        finally:
            self._guest_event.set()  # always unblock wait_for_guest()
            try:
                if self._server_sock:
                    self._server_sock.close()
            except Exception:
                pass

    def wait_for_guest(self, timeout: float = 600.0) -> bool:
        """
        Block the calling thread until a guest connects (or timeout expires).
        Returns True if guest successfully connected.
        """
        self._guest_event.wait(timeout)
        return self.connected

    @property
    def port(self) -> int:
        return self._port

    @property
    def local_ip(self) -> str:
        return _local_ip()


# ── Guest ─────────────────────────────────────────────────────────────────────

class NetworkGuest(NetworkPeer):
    """Connects to a NetworkHost as a guest."""

    def connect(
        self,
        host_ip: str,
        port: int = protocol.PORT,
        timeout: float = 10.0,
    ) -> bool:
        """
        Connect to the host.  Returns True on success, False on failure.
        Starts background send/recv threads on success.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host_ip.strip(), port))
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._start_threads(sock)
            return True
        except Exception:
            return False
