"""回放一次历史咨询，并生成一个可以直接在浏览器里看的网页。

回放接口本身只返回 JSON，看不出图长什么样。这个脚本走同一个只读回放接口，
再把原图与各机构的候选图渲染出来，连同改动清单写成一个 HTML，双击即可查看。

用法：
    python scripts/replay_view.py                     # 列出所有可回放的历史记录
    python scripts/replay_view.py v2-20260815-1431    # 回放这一条并生成网页
    python scripts/replay_view.py v2-20260815-1431 economist   # 只看某个机构
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.request
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

for _line in (BACKEND_DIR / ".env").read_text(encoding="utf-8").splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

from app.core.spec_render import render_vl_to_png_data_url  # noqa: E402

BASE_URL = os.environ.get("VIZGUIDE_BASE_URL", "http://127.0.0.1:8000")
OUTPUT_DIR = BACKEND_DIR.parent / "tmp_review" / "replay"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=60) as response:
        return json.load(response)


def _post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def list_runs() -> None:
    runs = _get("/api/v2/advisor/runs")["runs"]
    print(f"共 {len(runs)} 条可回放记录（最近的在最前）：\n")
    print(f"{'run_id':<26}{'引擎':<12}{'机构':<34}图表")
    for run in runs[:40]:
        title = run.get("chart_title") or ""
        if isinstance(title, list):
            title = " ".join(str(part) for part in title)
        personas = ",".join(run["replayable_persona_ids"])
        print(f"{run['run_id']:<26}{run['engine']:<12}{personas[:32]:<34}{str(title)[:46]}")
    if len(runs) > 40:
        print(f"\n……另有 {len(runs) - 40} 条更早的记录")
    print("\n挑一个 run_id，再跑：python scripts/replay_view.py <run_id>")


def _render(spec: dict) -> str | None:
    image, _meta = render_vl_to_png_data_url(spec)
    return image


def _changes_table(changes: list) -> str:
    rows = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        detail = change.get("component_detail")
        before_after = ""
        if isinstance(detail, dict):
            before = html.escape(str(detail.get("before") or ""))
            after = html.escape(str(detail.get("after") or ""))
            if before or after:
                before_after = f"<div class='delta'><b>改前</b> {before}<br><b>改后</b> {after}</div>"
        cells = [
            html.escape(str(change.get("label") or change.get("scope") or "")),
            f"{html.escape(str(change.get('layer') or ''))} · {html.escape(str(change.get('strength') or ''))}",
            html.escape(str(change.get("rule_id") or "")),
            html.escape(str(change.get("status") or "")),
            html.escape(str(change.get("reason") or "")) + before_after,
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    if not rows:
        return "<p>（无改动记录）</p>"
    return (
        "<table><thead><tr><th>部件</th><th>层级/强度</th><th>规则</th><th>状态</th><th>理由与前后对比</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def replay(run_id: str, persona_ids: list[str] | None) -> None:
    body: dict = {"run_id": run_id, "beat_delay_ms": 0}
    if persona_ids:
        body["persona_ids"] = persona_ids
    payload = _post("/api/v2/advisor/replay?wait=true", body)
    print(f"回放完成：{payload['run_id']}（复现自 {payload.get('replay_of')}）")

    record = _get(f"/api/v2/advisor/runs/{run_id}")
    source_image = _render((record.get("request") or {}).get("spec") or {})

    sections = []
    for agent in payload.get("agents", []):
        proposal = agent.get("proposal") or {}
        image = _render(proposal.get("modified_spec") or {})
        name = html.escape(str(proposal.get("persona_name") or agent.get("persona_id")))
        summary = html.escape(str(proposal.get("summary") or ""))
        changes = proposal.get("changes") or []
        print(f"  {agent['persona_id']:<12} 改动 {len(changes)} 条，图{'已渲染' if image else '渲染失败'}")
        picture = f'<img src="{image}" alt="{name}">' if image else "<p>（这张图渲染失败）</p>"
        sections.append(
            f"<section><h2>{name}</h2><p class='summary'>{summary}</p>"
            f"{picture}<h3>改动清单（{len(changes)} 条）</h3>{_changes_table(changes)}</section>"
        )

    source_block = f'<section><h2>原图</h2><img src="{source_image}" alt="原图"></section>' if source_image else ""
    page = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>回放 {html.escape(run_id)}</title>
<style>
 body {{ font: 15px/1.6 -apple-system, "PingFang SC", sans-serif; margin: 0 auto; max-width: 1040px; padding: 32px 24px 80px; color: #1a1a1a; }}
 h1 {{ font-size: 22px; margin-bottom: 4px; }}
 .meta {{ color: #666; margin-bottom: 32px; }}
 section {{ border-top: 1px solid #e5e5e5; padding-top: 24px; margin-top: 32px; }}
 h2 {{ font-size: 19px; }}
 .summary {{ color: #444; }}
 img {{ max-width: 100%; border: 1px solid #e5e5e5; border-radius: 6px; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }}
 th, td {{ border: 1px solid #e5e5e5; padding: 6px 8px; text-align: left; vertical-align: top; }}
 th {{ background: #fafafa; }}
 .delta {{ color: #555; margin-top: 6px; padding-left: 8px; border-left: 2px solid #ddd; }}
</style></head><body>
<h1>回放：{html.escape(run_id)}</h1>
<p class="meta">复现自 {html.escape(str(payload.get('replay_of')))}　·　引擎 {html.escape(str(record.get('engine') or ''))}　·　原始运行时间 {html.escape(str(record.get('created_at') or ''))}</p>
{source_block}{''.join(sections)}
</body></html>"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{run_id}.html"
    output.write_text(page, encoding="utf-8")
    print(f"\n网页已生成：{output}")
    try:
        webbrowser.open(output.as_uri())
    except Exception:  # noqa: BLE001 — 打不开浏览器不算失败，路径已经打印出来了
        print("（没能自动打开浏览器，双击上面这个文件即可）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        list_runs()
    else:
        replay(sys.argv[1], sys.argv[2:] or None)
