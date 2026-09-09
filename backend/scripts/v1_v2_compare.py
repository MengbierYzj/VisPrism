"""用同一份 spec 与同一批机构，把 v1 的历史 run 与新发起的 v2 run 做逐项对比。

    conda activate vizguide && cd backend
    python scripts/v1_v2_compare.py --baseline 20260814-2153 --start
    python scripts/v1_v2_compare.py --baseline 20260814-2153 --v2 v2-...   # 只出报告
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"
RUNS = Path(__file__).resolve().parents[1] / "storage" / "runs"


def read_run(run_id: str) -> dict:
    raw = (RUNS / f"{run_id}.json").read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.split("\n", 1)[1])


def post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as response:
        return json.loads(response.read())


def marks(spec: dict) -> list[str]:
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            mark = node.get("mark")
            if mark is not None:
                found.append(mark.get("type") if isinstance(mark, dict) else str(mark))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
    return found


def leaf_paths(node, prefix: str = "") -> set[str]:
    if isinstance(node, dict):
        return {p for key, value in node.items() for p in leaf_paths(value, f"{prefix}/{key}")}
    if isinstance(node, list):
        return {p for index, value in enumerate(node) for p in leaf_paths(value, f"{prefix}/{index}")}
    return {prefix}


def describe(engine: str, document: dict) -> None:
    source = document["request"]["spec"]
    src_paths = leaf_paths(source)
    print(f"\n{'=' * 78}\n{engine}  run={document.get('run_id')}\n{'=' * 78}")
    print(f"{'persona':<11}{'状态':<7}{'落地':<5}{'驳回':<5}{'marks':<16}{'层':<4}{'改动叶子':<9}{'L1未兑现':<10}耗时s")
    for agent in document["agents"]:
        proposal = agent.get("proposal") or {}
        spec = proposal.get("modified_spec") or {}
        changes = proposal.get("changes") or []
        applied = [c for c in changes if c.get("status") == "applied"]
        invariants = proposal.get("invariants") or []
        unmet = [i["rule_id"] for i in invariants if isinstance(i, dict) and not i.get("ok")]
        touched = len(leaf_paths(spec) ^ src_paths) if spec else 0
        print(
            f"{agent['persona_id']:<11}{agent.get('status',''):<7}{len(applied):<5}"
            f"{len(proposal.get('rejected') or []):<5}{','.join(dict.fromkeys(marks(spec))) or '-':<16}"
            f"{len(spec.get('layer') or []):<4}{touched:<9}{len(unmet):<10}"
            f"{round((proposal.get('elapsed_ms') or 0)/1000)}"
        )
    print(f"\n源图: marks={','.join(dict.fromkeys(marks(source)))} | layer={len(source.get('layer') or [])} | 叶子数={len(src_paths)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="v1 历史 run id")
    parser.add_argument("--start", action="store_true", help="用相同 spec 发起 v2 run")
    parser.add_argument("--v2", help="已有的 v2 run id（跳过发起）")
    parser.add_argument("--personas", help="逗号分隔；缺省沿用基线的机构")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    baseline = read_run(args.baseline)
    request = baseline["request"]
    personas = args.personas.split(",") if args.personas else request["persona_ids"]

    v2_id = args.v2
    if args.start:
        started = post("/api/v2/advisor/run", {
            "spec": request["spec"],
            "persona_ids": personas,
            "context": request.get("context") or {},
        })
        v2_id = started["run_id"]
        print(f"已发起 v2 run: {v2_id}（机构 {len(personas)} 个，请耐心等待）")
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(20)
            try:
                state = get(f"/api/v2/advisor/run/{v2_id}")
            except urllib.error.URLError as exc:
                print(f"  轮询失败（服务可能在热重载）: {exc}")
                continue
            stages = {a["persona_id"]: a["status"] for a in state["agents"]}
            print(f"  [{time.strftime('%H:%M:%S')}] {state['status']}: {stages}", flush=True)
            if state["status"] == "done":
                break
        else:
            print("超时未完成")
            return 1

    if not v2_id:
        print("需要 --start 或 --v2")
        return 1

    describe("v1（编译执行）", baseline)
    describe("v2（契约核验）", read_run(v2_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
