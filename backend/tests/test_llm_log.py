"""LLM 调用日志：按 run 绑定并落盘 *.llm.jsonl。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.llm import LLMClient
from app.llm_log import (
    LLMRunLog,
    bind_llm_persona,
    bind_llm_run_log,
    redact_for_log,
    reset_llm_persona,
    reset_llm_run_log,
)


def test_redact_strips_data_url():
    s = "prefix data:image/png;base64,AAAA suffix"
    out = redact_for_log(s)
    assert "AAAA" not in out
    assert "data_url omitted" in out


def test_run_log_records_and_flushes(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("VIZGUIDE_LLM_LOG", "1")
    monkeypatch.setenv("VIZGUIDE_LLM_MODE", "live")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeCompletions:
        async def create(self, **kwargs):
            message = SimpleNamespace(content='{"ok": true, "n": 1}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def close(self):
            pass

    log = LLMRunLog(run_id="logtest000001", kind="advisor")
    llm = LLMClient()
    llm._client = FakeClient()

    async def _run():
        t_log = bind_llm_run_log(log)
        t_p = bind_llm_persona("bbc")
        try:
            out = await llm.chat_json("sys", '{"ask":1}', retries=0)
            assert out == {"ok": True, "n": 1}
        finally:
            reset_llm_persona(t_p)
            reset_llm_run_log(t_log)

    asyncio.run(_run())
    assert len(log.entries) == 1
    assert log.entries[0]["ok"] is True
    assert log.entries[0]["raw"] == '{"ok": true, "n": 1}'
    assert log.entries[0]["parsed"] == {"ok": True, "n": 1}
    assert log.entries[0]["persona_id"] == "bbc"

    path = log.flush()
    assert path is not None and path.is_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["type"] == "llm_log_header"
    assert json.loads(lines[0])["count"] == 1
    assert json.loads(lines[1])["kind"] == "chat_json"
    assert path == Path(tmp_path) / "runs" / "logtest000001.llm.jsonl"
