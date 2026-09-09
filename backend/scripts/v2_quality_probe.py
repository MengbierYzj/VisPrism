"""v2 引擎质量探针：跑一次多 persona 咨询并汇总可交付性指标。

与 v1_v2_compare 的分工：那个脚本比较两个引擎的产出差异，这个脚本只盯 v2
自己的「能不能交付」——渲染是否成功、验收闸门是否真的跑过、确定性修复救回了
什么、画布有没有异常留白。调试期用小模型快速迭代，正式实验再换回大模型。

用法：
    python scripts/v2_quality_probe.py --personas bbc,ebay,economist --model gpt-4o-mini
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import pathlib
import sys
import time

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_env(path: pathlib.Path) -> None:
    """读取 backend/.env：脚本不经 uvicorn --env-file，需自行加载。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line[0] in "#;":
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def canvas_size(png_bytes: bytes) -> str:
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(png_bytes))
        return f"{image.width}x{image.height}"
    except Exception:  # noqa: BLE001 — 尺寸只是诊断信息
        return "?"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personas", default="bbc,ebay,economist")
    parser.add_argument("--model", default="")
    parser.add_argument("--spec", default="../data/dataset/01_global_temperature/chart_spec.json")
    parser.add_argument("--out", default="../tmp_review")
    args = parser.parse_args()

    load_env(BACKEND / ".env")
    if args.model:
        os.environ["VIZGUIDE_MODEL"] = args.model
    os.environ["VIZGUIDE_ADVISOR_ENGINE"] = "v2"

    from fastapi.testclient import TestClient

    from app.core.spec_render import render_vl_to_png_data_url
    from app.main import app

    spec = json.loads((BACKEND / args.spec).resolve().read_text(encoding="utf-8"))
    personas = [p.strip() for p in args.personas.split(",") if p.strip()]
    out_dir = (BACKEND / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"模型={os.environ.get('VIZGUIDE_MODEL')} personas={personas}")
    started = time.perf_counter()
    with TestClient(app) as client:
        response = client.post(
            "/api/advisor/run?wait=true",
            json={"spec": spec, "persona_ids": personas},
        )
        if response.status_code != 200:
            print("HTTP", response.status_code, response.text[:400])
            return 1
        payload = response.json()
    total = time.perf_counter() - started

    print(f"\nrun_id={payload['run_id']} 总耗时={total:.0f}s\n")
    header = f"{'persona':<11}{'状态':<7}{'落地':>4}{'建议':>5}{'耗时s':>7}  {'画布':<11}{'验收':<12}{'意图':<10}L1未兑现"
    print(header)
    print("-" * len(header))

    failures = 0
    for agent in payload["agents"]:
        pid = agent["persona_id"]
        proposal = agent.get("proposal") or {}
        facts = proposal.get("facts") or {}
        changes = proposal.get("changes") or []
        applied = sum(1 for c in changes if c.get("status") == "applied")
        suggested = sum(1 for c in changes if c.get("status") == "suggested")

        image, report = render_vl_to_png_data_url(proposal.get("modified_spec") or {})
        if image:
            png = base64.b64decode(image.split(",", 1)[1])
            (out_dir / f"probe_{pid}.png").write_bytes(png)
            size = canvas_size(png)
        else:
            size = "渲染失败"
            failures += 1

        review = facts.get("visual_review") or {}
        acceptance = review.get("acceptance") or {}
        verdict = acceptance.get("verdict") or acceptance.get("skipped") or "-"
        intent = ((acceptance.get("intent_assessment") or review.get("intent_assessment")) or {}).get("comparison") or "-"
        unmet = len((facts.get("l1_contract_verification") or {}).get("unmet") or [])

        print(
            f"{pid:<11}{agent['status']:<7}{applied:>4}{suggested:>5}"
            f"{round(proposal.get('elapsed_ms', 0) / 1000):>7}  {size:<11}{str(verdict):<12}{str(intent):<10}{unmet}"
        )
        layers: dict[str, int] = {}
        for change in changes:
            key = f"{change.get('layer')}/{change.get('strength')}"
            layers[key] = layers.get(key, 0) + 1
        payload_kb = len(json.dumps(agent, ensure_ascii=False).encode("utf-8")) / 1024
        print(f"    溯源: {layers}  载荷: {payload_kb:.0f} KB")
        for repair in (facts.get("structural_repairs") or []):
            print(f"    程序修复: {repair}")
        for error in (proposal.get("llm_errors") or [])[:2]:
            print(f"    LLM错误: {str(error)[:110]}")

    print(f"\n图已存至 {out_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
