"""Live 冒烟：验证拍3.5 机构口吻标题文案的线上效果。

用法（在 backend/ 下，vizguide conda 环境）:
  VIZGUIDE_LLM_MODE=live python scripts/live_copy_smoke.py [spec路径] [persona ...]

默认跑 Berlin 自行车失窃图 × bbc/ibm/ebay，打印每个机构的标题/副标题 ops 与理由。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _load_dotenv_defaults(path: Path) -> None:
    """加载 .env 但不覆盖已设的进程环境（命令行 VIZGUIDE_LLM_MODE=live 优先）。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_dotenv_defaults(BACKEND_DIR / ".env")
os.environ.setdefault("VIZGUIDE_LLM_MODE", "live")

from app.config import settings  # noqa: E402
from app.core.persona import PersonaRegistry  # noqa: E402
from app.core.runner import RunStore, start_run, wait_run  # noqa: E402
from app.llm import LLMClient  # noqa: E402

DEFAULT_SPEC = BACKEND_DIR.parent / "data" / "dataset" / "08_berlin bike theft" / "Berlin's Bike.json"


async def main() -> None:
    args = sys.argv[1:]
    spec_path = Path(args[0]) if args and args[0].endswith(".json") else DEFAULT_SPEC
    personas = [a for a in args if not a.endswith(".json")] or ["bbc", "ibm", "ebay"]
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)

    registry = PersonaRegistry(
        data_dir=settings.data_dir, custom_dir=settings.storage_dir / "personas"
    )
    store = RunStore()
    run, err = start_run(
        store, registry, LLMClient(), spec, personas,
        {"communication_goal": "Emphasize how few of the recorded bike thefts ever get solved"},
    )
    assert err == "" and run is not None, err
    await wait_run(run)
    print(f"run status: {run.status} · llm mode: {settings.llm_mode} · model: {settings.model}")

    if run.agenda:
        print("\n=== moderator agenda ===")
        for i, issue in enumerate(run.agenda.get("issues", []), 1):
            print(f"#{i} [{issue['category']}] {issue['title']}")
            if issue.get("blurb"):
                print(f"   blurb: {issue['blurb']}")
            for t in issue["treatments"]:
                print(f"   - {t['persona_id']}: {t['line']}  ({', '.join(t['change_ids'])})")
                if t.get("why"):
                    print(f"     why: {t['why']}")
            if issue.get("discussion_intro"):
                print(f"   intro: {issue['discussion_intro']}")
            if issue.get("quick_asks"):
                print(f"   asks: {' | '.join(issue['quick_asks'])}")
    else:
        print("\n=== moderator agenda: None (fallback to local derivation) ===")

    for pid in personas:
        agent = run.agents.get(pid)
        if agent is None:
            print(f"\n=== {pid} · MISSING ===")
            continue
        prop = agent.proposal or {}
        print(f"\n=== {pid} · agent status: {agent.status} ===")
        found_title = False
        for c in prop.get("changes", []):
            for op in c.get("ops") or []:
                if op.get("action") in ("set_title_text", "set_subtitle"):
                    found_title = True
                    print(f"  [{c.get('rule_id')}][{c.get('status')}] {op['action']}: {op.get('text')!r}")
        if not found_title:
            print("  (no title/subtitle ops)")
        for c in prop.get("changes", [])[:3]:
            print(f"  reason[{c.get('rule_id')}]: {str(c.get('reason'))[:160]}")
        # 布局多样性总览：每条 change 的动作集合（applied 才计入落地）
        print("  --- changes × ops ---")
        for c in prop.get("changes", []):
            actions = sorted({op.get("action") for op in (c.get("ops") or []) if op.get("action")})
            if actions:
                print(f"  [{c.get('status')}] {c.get('rule_id')}: {', '.join(actions)}")


if __name__ == "__main__":
    asyncio.run(main())
