"""验收闸门推理档位的受控实验。

问题：验收闸门（beat3_visual_acceptance）能否留在低推理档而不牺牲判断质量？

做法：从一次真实 gpt-5 快照里取出该阶段production 用过的原始提示词，配上同一对
图片，只切换 reasoning_effort 重放。提示词与图片完全固定，档位是唯一变量，因此
判定差异可以直接归因于档位本身，不必重跑整条 15 分钟的流水线。

用法：
    python -u scripts/gate_effort_ab.py v2-20260815-0249 low medium
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

for _line in (BACKEND_DIR / ".env").read_text(encoding="utf-8").splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

from app.advisor_v2.service import _safe_candidate  # noqa: E402
from app.core.spec_render import render_vl_to_png_data_url  # noqa: E402
from app.llm import LLMClient  # noqa: E402
from app.llm_log import bind_llm_stage, reset_llm_stage  # noqa: E402

STAGE = "beat3_visual_acceptance"


def load_run(run_id: str) -> dict:
    raw = (Path("storage/runs") / f"{run_id}.json").read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.split("\n", 1)[1])


def load_gate_prompts(run_id: str) -> dict[str, tuple[str, str]]:
    """该次运行中，每个 persona 最后一次验收调用的 system / user 原文。"""
    path = Path("storage/runs") / f"{run_id}.llm.jsonl"
    prompts: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("stage") == STAGE and entry.get("persona_id"):
            prompts[entry["persona_id"]] = (entry.get("system", ""), entry.get("user", ""))
    return prompts


async def judge(llm: LLMClient, system: str, user: str, images: list[str], effort: str) -> tuple[dict, float]:
    os.environ["VIZGUIDE_VERIFY_REASONING_EFFORT"] = effort
    token = bind_llm_stage(STAGE)
    start = time.perf_counter()
    try:
        result = await llm.chat_json_vision(system, user, images, detail="high", retries=0)
    except Exception as error:  # noqa: BLE001 — 实验脚本，失败也要记入对照表
        result = {"verdict": f"ERROR: {error}"}
    finally:
        reset_llm_stage(token)
    return result if isinstance(result, dict) else {"verdict": str(result)[:80]}, time.perf_counter() - start


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--only=")]
    only = {p for a in sys.argv[1:] if a.startswith("--only=") for p in a.split("=", 1)[1].split(",")}
    run_id = args[0] if args else "v2-20260815-0249"
    efforts = args[1:] or ["low", "medium"]
    run = load_run(run_id)
    prompts = load_gate_prompts(run_id)
    llm = LLMClient()
    print(f"运行 {run_id} | 模型 {llm.model if hasattr(llm, 'model') else '?'} | 档位 {efforts}\n")

    source_image, _ = render_vl_to_png_data_url(run["request"]["spec"])
    rows: list[tuple[str, str, dict, float]] = []
    for agent in run["agents"]:
        persona = agent["persona_id"]
        if persona not in prompts or (only and persona not in only):
            continue
        system, user = prompts[persona]
        # 判的是修复后真正会交付给用户的那张图。
        repaired, report = _safe_candidate(run["request"]["spec"], agent["proposal"]["modified_spec"], [])
        candidate_image, _ = render_vl_to_png_data_url(repaired)
        if not candidate_image:
            print(f"{persona}: 候选图渲染失败，跳过")
            continue
        note = "；".join(report.get("structural_repairs") or []) or "无"
        print(f"{persona}: 程序修复 = {note}")
        for effort in efforts:
            verdict, seconds = await judge(llm, system, user, [source_image, candidate_image], effort)
            rows.append((persona, effort, verdict, seconds))
            print(f"  [{effort:>6}] {seconds:5.0f}s  verdict={verdict.get('verdict')} score={verdict.get('delivery_score')}")

    print("\n=== 对照表 ===")
    for persona, effort, verdict, seconds in rows:
        findings = verdict.get("findings") or []
        high = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "high")
        intent = (verdict.get("intent_assessment") or {}).get("comparison")
        print(f"{persona:<11} {effort:<7} {seconds:5.0f}s verdict={str(verdict.get('verdict')):<7} "
              f"score={str(verdict.get('delivery_score')):<5} 意图={str(intent):<10} 问题={len(findings)}(高危{high})")
        for finding in findings[:4]:
            if isinstance(finding, dict):
                print(f"        - [{finding.get('severity')}] {str(finding.get('issue'))[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
