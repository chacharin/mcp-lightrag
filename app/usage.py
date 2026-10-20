"""Usage log: one JSON line per model call and per tool call, for usage research and performance tuning.

Records hold token counts, sizes, ids and timings - never the text that was checked. The field names follow
the schema harness-usage/1, the same as the usage-telemetry plugin of the agent (Hermes), so all logs can be
joined into one data set. Files: USAGE_DIR/usage-YYYY-MM-DD.jsonl, read back through GET /usage.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import threading
import time
from datetime import datetime

SCHEMA = "harness-usage/1"
TOKEN_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens", "cache_write_tokens",
                "total_tokens")


def _mem_total_mb() -> int | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def environment(component: str, version: str) -> dict:
    """The host and software the records come from (for comparing hardware and versions)."""
    return {"component": component, "version": version, "host": socket.gethostname(),
            "platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
            "cpu_count": os.cpu_count(), "mem_total_mb": _mem_total_mb()}


def openai_usage(d: dict) -> dict:
    """Token fields from an OpenAI-compatible response (OpenRouter, vLLM, Ollama ...); None when not reported."""
    u = d.get("usage") if isinstance(d, dict) else None
    if not isinstance(u, dict):
        return {k: None for k in TOKEN_FIELDS} | {"cost_usd": None, "tokens_estimated": None}
    prompt = int(u.get("prompt_tokens") or 0)
    cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    written = int((u.get("prompt_tokens_details") or {}).get("cache_write_tokens") or 0)
    out = int(u.get("completion_tokens") or 0)
    cost = u.get("cost")
    return {"input_tokens": max(prompt - cached - written, 0), "output_tokens": out,
            "reasoning_tokens": int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
            "cache_read_tokens": cached, "cache_write_tokens": written,
            "total_tokens": int(u.get("total_tokens") or prompt + out),
            "cost_usd": float(cost) if isinstance(cost, (int, float)) else None, "tokens_estimated": False}


def sum_tokens(calls: list[dict]) -> dict:
    """Totals of several model calls (a field stays None when no call reported it)."""
    out: dict = {}
    for k in (*TOKEN_FIELDS, "cost_usd"):
        vals = [c.get(k) for c in calls if c.get(k) is not None]
        out[k] = (round(sum(vals), 6) if k == "cost_usd" else sum(vals)) if vals else None
    return out


class UsageLog:
    def __init__(self, component: str, version: str, directory: str, enabled: bool = True):
        self.component, self.version = component, version
        self.dir = directory
        self.enabled = enabled
        self.error: str | None = None
        self._lock = threading.Lock()
        self.env = environment(component, version)

    def _path(self, day: str) -> str:
        return os.path.join(self.dir, f"usage-{day}.jsonl")

    def write(self, record: dict) -> None:
        if not self.enabled:
            return
        now = time.time()
        line = {"schema": SCHEMA, "ts": round(now, 3), "component": self.component, "host": self.env["host"],
                **record}
        try:
            with self._lock:
                os.makedirs(self.dir, exist_ok=True)
                with open(self._path(datetime.fromtimestamp(now).strftime("%Y-%m-%d")), "a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            self.error = None
        except OSError as e:   # the usage log must never break a tool call
            self.error = f"{type(e).__name__}: {e}"

    def writable(self) -> bool:
        try:
            os.makedirs(self.dir, exist_ok=True)
            return os.access(self.dir, os.W_OK)
        except OSError:
            return False

    def read(self, since: float | None = None, until: float | None = None, limit: int = 50000) -> list[dict]:
        """Records with since <= ts < until, oldest first (at most `limit`, the newest kept)."""
        try:
            names = sorted(n for n in os.listdir(self.dir) if n.startswith("usage-") and n.endswith(".jsonl"))
        except OSError:
            return []
        if since is not None:   # skip whole days before `since` (a day file holds records of that local day)
            first = datetime.fromtimestamp(since).strftime("%Y-%m-%d")
            names = [n for n in names if n[6:16] >= first]
        out: list[dict] = []
        for n in names:
            try:
                with open(os.path.join(self.dir, n), encoding="utf-8") as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                        except ValueError:
                            continue
                        ts = r.get("ts") or 0
                        if (since is None or ts >= since) and (until is None or ts < until):
                            out.append(r)
            except OSError:
                continue
        return out[-limit:]
