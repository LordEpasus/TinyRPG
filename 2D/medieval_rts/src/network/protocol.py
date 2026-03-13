"""JSON protocol helpers for LAN multiplayer.

Transport format:
  - UTF-8 newline-delimited JSON (NDJSON)
  - one message per line
"""
from __future__ import annotations

import json
from typing import Any

# ── Network settings ──────────────────────────────────────────────────────────
PORT = 5555
PROTOCOL_VERSION = 5

# ── Message types ─────────────────────────────────────────────────────────────
MSG_HELLO = "hello"
MSG_GAME_START = "game_start"
MSG_SYNC_TICK = "sync_tick"
MSG_STATE_HASH = "state_hash"
MSG_STATE_SYNC = "state_sync"
MSG_UNIT_MOVE = "unit_move"
MSG_UNIT_ATTACK = "unit_attack"
MSG_BUILD = "build"
MSG_SPAWN_UNIT = "spawn_unit"
MSG_SHIP_MOVE = "ship_move"
MSG_UNIT_GATHER = "unit_gather"
MSG_UNIT_STANCE = "unit_stance"
MSG_HERO_MODE = "hero_mode"
MSG_HERO_INPUT = "hero_input"
MSG_FORMATION_SET = "formation_set"
MSG_KINGDOM_SPLIT = "kingdom_split"
MSG_CAPITAL_STOCK = "capital_stock_adjust"
MSG_DIPLOMACY_STATE = "diplomacy_state"
MSG_TREATY_CHANGE = "treaty_change"
MSG_TRIBUTE_PAID = "tribute_paid"
MSG_SUPPRESSION_ORDER = "suppression_order"
MSG_NAVAL_TASK = "naval_task"
MSG_TECH_START = "tech_start"
MSG_TECH_AGE = "tech_age"
MSG_DISCONNECT = "disconnect"


def encode(msg: dict[str, Any]) -> bytes:
    """Serialize a message to newline-terminated JSON bytes."""
    return (json.dumps(msg, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def decode(line: str) -> dict[str, Any] | None:
    """Parse a single JSON line. Returns None for invalid payloads."""
    try:
        obj = json.loads(line.strip())
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    msg_type = obj.get("type")
    if not isinstance(msg_type, str) or not msg_type:
        return None
    return obj
