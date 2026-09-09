"""按 run 记录每次 LLM API 往返（另存 *.llm.jsonl）。

通过 contextvars 绑定当前 run / persona，并行 agent 互不串台。
无绑定（Parser / Composer）时追加到 storage/llm_logs/orphan_YYYYMMDD.jsonl。
"""
from __future__ import annotations

import asyncio
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

_run_log: ContextVar["LLMRunLog | None"] = ContextVar("vizguide_llm_run_log", default=None)
_persona_id: ContextVar[str | None] = ContextVar("vizguide_llm_persona_id", default=None)
# 不记录阶段就无法把耗时归因到具体的拍，速度优化只能靠猜。
_stage: ContextVar[str | None] = ContextVar("vizguide_llm_stage", default=None)

_DATA_URL_RE = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", re.I)


@dataclass
class LLMRunLog:
    run_id: str
    kind: str = "advisor"  # advisor | orphan | parser | composer
    entries: list[dict[str, Any]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def record(self, entry: dict[str, Any]) -> None:
        row = redact_for_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "run_id": self.run_id,
                "persona_id": _persona_id.get(),
                "stage": _stage.get(),
                **entry,
            }
        )
        async with self._lock:
            self.entries.append(row)

    def flush(self, path: Path | None = None) -> Path | None:
        """落盘 JSONL（首行 header + 每条调用一行）。"""
        if not settings.llm_log_enabled:
            return None
        if path is None:
            if self.kind == "advisor":
                path = settings.storage_dir / "runs" / f"{self.run_id}.llm.jsonl"
            else:
                path = settings.storage_dir / "llm_logs" / f"{self.kind}_{self.run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "llm_log_header",
                        "run_id": self.run_id,
                        "kind": self.kind,
                        "count": len(self.entries),
                        "written_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            for row in self.entries:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path


def get_llm_run_log() -> LLMRunLog | None:
    return _run_log.get()


def bind_llm_run_log(log: LLMRunLog):
    return _run_log.set(log)


def reset_llm_run_log(token) -> None:
    _run_log.reset(token)


def bind_llm_persona(persona_id: str | None):
    return _persona_id.set(persona_id)


def reset_llm_persona(token) -> None:
    _persona_id.reset(token)


def bind_llm_stage(stage: str | None):
    return _stage.set(stage)


def reset_llm_stage(token) -> None:
    _stage.reset(token)


def current_llm_stage() -> str | None:
    return _stage.get()


def redact_for_log(value: Any, *, max_chars: int = 200_000) -> Any:
    """日志安全：去掉超长 data URL，截断极端长文本。"""
    if isinstance(value, str):
        s = _DATA_URL_RE.sub(
            lambda m: f"[data_url omitted chars={len(m.group(0))}]",
            value,
        )
        if len(s) > max_chars:
            return s[:max_chars] + f"…[truncated total={len(s)}]"
        return s
    if isinstance(value, list):
        return [redact_for_log(v, max_chars=max_chars) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in ("image_url", "preview_image") and isinstance(v, (str, dict)):
                if isinstance(v, str):
                    out[k] = f"[omitted chars={len(v)}]"
                else:
                    url = v.get("url") if isinstance(v.get("url"), str) else ""
                    out[k] = {**v, "url": f"[omitted chars={len(url)}]"}
            else:
                out[k] = redact_for_log(v, max_chars=max_chars)
        return out
    return value


async def ensure_log_and_record(entry: dict[str, Any]) -> None:
    """有 run 绑定则写入该 log；否则追加 orphan 日文件。"""
    if not settings.llm_log_enabled:
        return
    try:
        log = _run_log.get()
        if log is None:
            await _append_orphan(entry)
            return
        await log.record(entry)
    except OSError as exc:
        # 日志写失败不得掩盖原始的 LLM 错误或取消信号
        print(f"[llm-log] write failed: {exc}", flush=True)


async def _append_orphan(entry: dict[str, Any]) -> None:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = settings.storage_dir / "llm_logs" / f"orphan_{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = redact_for_log(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": None,
            "persona_id": _persona_id.get(),
            **entry,
        }
    )
    line = json.dumps(row, ensure_ascii=False) + "\n"

    def _write() -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    await asyncio.to_thread(_write)
