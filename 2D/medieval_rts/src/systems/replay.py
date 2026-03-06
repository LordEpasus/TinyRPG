from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass


@dataclass(slots=True)
class ReplayEvent:
    tick: int
    msg: dict[str, object]


class ReplayManager:
    MODE_OFF = "off"
    MODE_RECORD = "record"
    MODE_PLAYBACK = "playback"

    def __init__(
        self,
        *,
        mode: str = MODE_OFF,
        replay_path: str | None = None,
        meta: dict[str, object] | None = None,
        base_dir: str | None = None,
    ) -> None:
        self.mode = mode if mode in (self.MODE_OFF, self.MODE_RECORD, self.MODE_PLAYBACK) else self.MODE_OFF
        self.base_dir = base_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "replays")
        os.makedirs(self.base_dir, exist_ok=True)

        self.replay_path = replay_path
        self._writer = None
        self._events: list[ReplayEvent] = []
        self._cursor = 0
        self._counts: dict[str, int] = {}
        self.meta: dict[str, object] = dict(meta or {})

        if self.mode == self.MODE_RECORD:
            if not self.replay_path:
                stamp = time.strftime("%Y%m%d_%H%M%S")
                self.replay_path = os.path.join(self.base_dir, f"match_{stamp}.jsonl")
            self._writer = open(self.replay_path, "w", encoding="utf-8")
            self._write_line({"type": "meta", **self.meta})
        elif self.mode == self.MODE_PLAYBACK and self.replay_path:
            self._load(self.replay_path)

    @property
    def is_recording(self) -> bool:
        return self.mode == self.MODE_RECORD and self._writer is not None

    @property
    def is_playback(self) -> bool:
        return self.mode == self.MODE_PLAYBACK

    def record_message(self, tick: int, msg: dict[str, object]) -> None:
        if not self.is_recording:
            return
        clean = dict(msg)
        mtype = str(clean.get("type", ""))
        if not mtype:
            return
        row = {"type": "event", "tick": int(max(0, tick)), "msg": clean}
        self._write_line(row)
        self._counts[mtype] = self._counts.get(mtype, 0) + 1

    def poll(self, tick: int) -> list[dict[str, object]]:
        if not self.is_playback:
            return []
        ready: list[dict[str, object]] = []
        t = int(max(0, tick))
        while self._cursor < len(self._events) and self._events[self._cursor].tick <= t:
            ev = self._events[self._cursor]
            ready.append(dict(ev.msg))
            self._cursor += 1
        return ready

    def summary(self) -> dict[str, int]:
        if self.is_playback:
            counts: dict[str, int] = {}
            for ev in self._events:
                mtype = str(ev.msg.get("type", ""))
                if not mtype:
                    continue
                counts[mtype] = counts.get(mtype, 0) + 1
            return counts
        return dict(self._counts)

    def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None

    def _write_line(self, obj: dict[str, object]) -> None:
        if self._writer is None:
            return
        self._writer.write(json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n")
        self._writer.flush()

    def _load(self, path: str) -> None:
        self._events.clear()
        self._cursor = 0
        self.meta = {}
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                row_type = str(row.get("type", ""))
                if row_type == "meta":
                    self.meta = dict(row)
                    continue
                if row_type != "event":
                    continue
                tick = int(row.get("tick", 0))
                msg = row.get("msg", {})
                if isinstance(msg, dict):
                    self._events.append(ReplayEvent(tick=tick, msg=dict(msg)))

    @classmethod
    def latest_replay_file(cls, base_dir: str) -> str | None:
        if not os.path.isdir(base_dir):
            return None
        files = [
            os.path.join(base_dir, name)
            for name in os.listdir(base_dir)
            if name.endswith(".jsonl")
        ]
        if not files:
            return None
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return files[0]

    @staticmethod
    def load_header(path: str) -> dict[str, object]:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    return {}
                if isinstance(row, dict) and str(row.get("type", "")) == "meta":
                    return dict(row)
                return {}
        return {}
