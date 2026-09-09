"""run 快照第一行记录 LLM API → mock 降级标记。"""
from __future__ import annotations

from pathlib import Path

from app.core.runner import (
    AgentState,
    RunState,
    RunStore,
    collect_llm_api_status,
    load_run_snapshot,
)


def _run_with_traces(llm_mode: str, traces_by_agent: dict[str, list]) -> RunState:
    agents = {}
    order = []
    for pid, traces in traces_by_agent.items():
        order.append(pid)
        agents[pid] = AgentState(
            persona_id=pid,
            status="done",
            proposal={
                "persona_id": pid,
                "facts": {},
                "trace": traces,
                "changes": [],
                "rejected": [],
            },
        )
    return RunState(
        run_id="testrun000001",
        spec={"mark": "bar"},
        context={},
        agents=agents,
        order=order,
        created_at="2026-08-01T00:00:00+00:00",
        status="done",
        llm_mode=llm_mode,
    )


def test_collect_detects_mock_fallback_from_live():
    run = _run_with_traces(
        "live",
        {
            "bbc": [
                {
                    "beat": 1,
                    "mode": "mock-fallback",
                    "note": "live 调用失败已降级启发式：timeout",
                }
            ]
        },
    )
    status = collect_llm_api_status(run)
    assert status["llm_api_mock_fallback"] is True
    assert status["configured_mode"] == "live"
    assert status["agents"][0]["api_fallback"] is True


def test_collect_configured_mock_is_not_api_fallback():
    run = _run_with_traces(
        "mock",
        {"bbc": [{"beat": 1, "mode": "mock", "note": ""}]},
    )
    status = collect_llm_api_status(run)
    assert status["llm_api_mock_fallback"] is False
    assert "configured_mock" in status["summary"]


def test_snapshot_writes_status_on_first_line(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    # settings 即取即读
    run = _run_with_traces(
        "live",
        {
            "economist": [
                {
                    "beat": 3,
                    "mode": "mock-fallback",
                    "note": "live 裁决失败已降级启发式：503",
                }
            ]
        },
    )
    store = RunStore()
    store.snapshot(run)
    path = Path(tmp_path) / "runs" / "testrun000001.json"
    assert path.is_file()
    first = path.read_text(encoding="utf-8").splitlines()[0]
    import json

    banner = json.loads(first)
    assert banner["llm_api_mock_fallback"] is True
    assert banner["run_id"] == "testrun000001"

    body = load_run_snapshot(path)
    assert body["llm_api_mock_fallback"] is True
    assert body["request"]["spec"]["mark"] == "bar"
    assert body["run_id"] == "testrun000001"
