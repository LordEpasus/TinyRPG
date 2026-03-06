"""Asyncio TCP relay server for LAN multiplayer."""
from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import Any

from . import protocol


def local_ip() -> str:
    """Best-effort LAN IP detection."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


class RelayServer:
    """TCP message relay. Every received JSON line is forwarded to other clients."""

    def __init__(self, *, host: str = "0.0.0.0", port: int = protocol.PORT) -> None:
        self.host = host
        self.port = int(port)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: asyncio.AbstractServer | None = None
        self._started_evt = threading.Event()
        self._stopped_evt = threading.Event()
        self._clients: dict[int, asyncio.StreamWriter] = {}
        self._writer_to_id: dict[asyncio.StreamWriter, int] = {}
        self._next_client_id = 1
        self._client_lock = threading.Lock()
        self._last_error = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def client_count(self) -> int:
        with self._client_lock:
            return len(self._clients)

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self, timeout: float = 3.0) -> str:
        """Start server in background thread and return LAN IP."""
        if self.running:
            return local_ip()
        self._started_evt.clear()
        self._stopped_evt.clear()
        self._thread = threading.Thread(target=self._run_loop, name="lan-relay-server", daemon=True)
        self._thread.start()
        self._started_evt.wait(timeout=max(0.1, float(timeout)))
        return local_ip()

    def wait_for_clients(self, min_clients: int = 2, timeout: float = 30.0) -> bool:
        """Wait until at least `min_clients` connected."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if self.client_count >= max(1, int(min_clients)):
                return True
            time.sleep(0.05)
        return self.client_count >= max(1, int(min_clients))

    def stop(self, timeout: float = 2.0) -> None:
        if not self.running:
            return
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(self._shutdown()))
        self._stopped_evt.wait(timeout=max(0.2, float(timeout)))
        if self._thread is not None:
            self._thread.join(timeout=max(0.2, float(timeout)))
        self._thread = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._server = loop.run_until_complete(asyncio.start_server(self._handle_client, self.host, self.port))
            self._started_evt.set()
            loop.run_forever()
        except Exception as exc:
            self._last_error = str(exc)
            self._started_evt.set()
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            loop.close()
            self._stopped_evt.set()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client_id = self._register_writer(writer)
        hello = {
            "type": protocol.MSG_HELLO,
            "server": True,
            "client_id": client_id,
            "protocol": protocol.PROTOCOL_VERSION,
        }
        await self._send_raw(writer, protocol.encode(hello))

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace")
                msg = protocol.decode(line)
                if msg is None:
                    continue
                msg.setdefault("protocol", protocol.PROTOCOL_VERSION)
                msg.setdefault("client_id", client_id)
                await self._broadcast(msg, exclude=writer)
        except Exception:
            pass
        finally:
            self._unregister_writer(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _register_writer(self, writer: asyncio.StreamWriter) -> int:
        with self._client_lock:
            cid = self._next_client_id
            self._next_client_id += 1
            self._clients[cid] = writer
            self._writer_to_id[writer] = cid
            return cid

    def _unregister_writer(self, writer: asyncio.StreamWriter) -> None:
        with self._client_lock:
            cid = self._writer_to_id.pop(writer, None)
            if cid is not None:
                self._clients.pop(cid, None)

    async def _broadcast(self, msg: dict[str, Any], *, exclude: asyncio.StreamWriter | None = None) -> None:
        data = protocol.encode(msg)
        with self._client_lock:
            writers = list(self._writer_to_id.keys())
        for writer in writers:
            if writer is exclude:
                continue
            await self._send_raw(writer, data)

    async def _send_raw(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        try:
            writer.write(data)
            await writer.drain()
        except Exception:
            self._unregister_writer(writer)

    async def _shutdown(self) -> None:
        with self._client_lock:
            writers = list(self._writer_to_id.keys())
        for writer in writers:
            try:
                writer.close()
            except Exception:
                pass
        for writer in writers:
            try:
                await writer.wait_closed()
            except Exception:
                pass
        with self._client_lock:
            self._clients.clear()
            self._writer_to_id.clear()
        if self._server is not None:
            try:
                self._server.close()
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.stop()
