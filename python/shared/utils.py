"""Shared utilities: structured logging, config loading, event emission to Electron."""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = Path(os.environ.get("LAWGIC_EULAW_DATA_DIR", REPO_ROOT / "data"))


def load_config(name: str) -> dict[str, Any]:
    """Load a JSON config file from config/<name>.json."""
    path = CONFIG_DIR / f"{name}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def emit(event_type: str, **payload: Any) -> None:
    """Emit a single-line JSON event to stdout for Electron to parse.

    Every pipeline script writes events here. The Electron main.js parses
    stdout line by line and forwards to the renderer as 'pipeline-event'.
    Keep events flat and small.
    """
    event = {"type": event_type, "ts": time.time(), **payload}
    sys.stdout.write(json.dumps(event, default=str) + "\n")
    sys.stdout.flush()


def log(level: str, message: str, **extra: Any) -> None:
    emit("log", level=level, message=message, **extra)


def deterministic_uuid(*parts: str) -> str:
    """uuid5 from the joined parts. Used for EULaws, EUCourtDecisions, EULawIngestionStatus keys."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "::".join(parts)))


def sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class CostLogger:
    """Append-only JSONL cost log at scripts/cost_log.jsonl."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (REPO_ROOT / "scripts" / "cost_log.jsonl")
        ensure_dir(self.path.parent)

    def record(self, *, model: str, celex: str, task: str,
               input_tokens: int, cached_tokens: int, output_tokens: int,
               cost_usd: float) -> None:
        row = {
            "ts": time.time(),
            "model": model,
            "celex": celex,
            "task": task,
            "input_tokens": input_tokens,
            "cached_tokens": cached_tokens,
            "output_tokens": output_tokens,
            "cache_hit_ratio": (cached_tokens / input_tokens) if input_tokens else 0.0,
            "cost_usd": cost_usd,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
