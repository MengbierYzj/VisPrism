"""端到端冒烟：v2 契约引擎跑真实 persona，检查拍4 的 L1 核验确实生效。

用 stub LLM 模拟「拍3 自由重建」——刻意生成一张违反 BBC L1 签名的图，
以验证快道核验能检出并按令牌修补，而不是听信模型的说法。

    conda activate vizguide && cd backend && python scripts/v2_contract_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.advisor_v2 import AdvisorV2
from app.config import settings
from app.core.persona import PersonaRegistry

SOURCE = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "data": {"values": [{"city": "London", "v": 32}, {"city": "Leeds", "v": 21}, {"city": "Cardiff", "v": 14}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "city", "type": "nominal"},
        "y": {"field": "v", "type": "quantitative"},
    },
    "title": "Reported cases by city",
}


class RedesignLLM:
    """拍3 返回一张结构更丰富、但违反机构 L1 的重建图。"""

    mode = "live"

    async def chat_json(self, system: str, user: str):
        if "repairing the user-facing change manifest" in system:
            return {"commitments": [], "unapplied": []}
        if "Beat 1" in system:
            return {"story": "Cases concentrate in London.", "audience": "general public", "data_roles": [], "risks": []}
        candidate = json.loads(json.dumps(SOURCE))
        # 自由重建：加注释层与轴配置——这些是封闭动作词汇表做不到的
        candidate["layer"] = [
            {"mark": {"type": "bar"}, "encoding": candidate.pop("encoding")},
            {
                "mark": {"type": "text", "align": "left", "dx": 6},
                "data": {"values": [{"city": "London", "v": 32, "note": "Highest caseload"}]},
                "encoding": {
                    "x": {"field": "city", "type": "nominal"},
                    "y": {"field": "v", "type": "quantitative"},
                    "text": {"field": "note", "type": "nominal"},
                },
            },
        ]
        candidate.pop("mark", None)
        return {
            "story": "Rebuilt with an annotation layer.",
            "commitments": [],
            "text_changes": [],
            "candidate_spec": candidate,
        }

    async def chat_json_vision(self, system, user, images, detail="low"):
        raise RuntimeError("vision skipped in smoke test")


async def main() -> int:
    registry = PersonaRegistry(data_dir=settings.data_dir, custom_dir=settings.storage_dir / "personas")
    persona = registry.get("bbc")
    if persona is None:
        print("FAIL: bbc persona not found")
        return 1

    result = await AdvisorV2(RedesignLLM()).advise(persona, SOURCE, {})
    verification = result["beats"]["beat4"]["l1_contract_verification"]
    final = result["spec"]

    print(f"engine            : {result['version']}")
    print(f"delivery_state    : {result['beats']['beat4']['delivery_state']}")
    print(f"enforcement mode  : {verification.get('mode')}")
    print(f"L1 before         : {[(i['rule_id'], i['ok']) for i in verification.get('before', [])]}")
    print(f"patched by fast   : {verification.get('patched')}")
    print(f"patch rejected    : {verification.get('patch_rejected')}")
    print(f"still unmet       : {verification.get('unmet')}")
    print(f"annotation layer  : {'layer' in final}")

    # 各消融臂的预期不同：patch 应修补掉违规，report/off 应如实留下 unmet。
    mode = verification.get("mode")
    enforcement_ok = (
        not verification.get("unmet") and verification.get("patched")
        if mode == "patch"
        else verification.get("unmet") and not verification.get("patched")
    )
    ok = (
        result["beats"]["beat4"]["changed"]
        and "layer" in final  # LLM 的结构自由度被保留
        and enforcement_ok
    )
    print("\nSMOKE:", "PASS" if ok else "FAIL", f"(arm={mode})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
