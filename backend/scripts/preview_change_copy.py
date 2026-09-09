"""预览议题卡将呈现给设计师的三行说明（问题 / 处理 / 机构知识）。

前端 treatmentSummary 的等价实现，用于在不开浏览器的情况下检查文案质量：
关键词化、空依据、重复句都会在这里直接暴露出来。

    python scripts/preview_change_copy.py v2-20260815-1431
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.advisor_v2.replay import _backfill_evidence, load_record  # noqa: E402
from app.config import settings  # noqa: E402
from app.core.persona import PersonaRegistry  # noqa: E402

APPLIED_PREFIX = re.compile(r"^(applied|proposed|suggested|change)\s*[:：—–]\s*", re.IGNORECASE)
HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}\b")
LAYER_RANK = {"L2": 0, "L1": 1, "L3": 2}

CATEGORY = [
    ("title", r"(title|headline|subtitle|takeaway|narrative|story)"),
    ("color", r"(color|colour|palette|contrast|hue|highlight|emphasis)"),
    ("labels", r"(label|annotation|callout|legend|tooltip|source|caption)"),
    ("axes", r"(axis|axes|scale|grid|tick|baseline|zero)"),
    ("layout", r"(layout|spacing|position|align|margin|padding|size|hierarchy)"),
    ("typography", r"(font|typeface|typography|weight|text size)"),
]


def clean(text) -> str:
    trimmed = re.sub(r"\s+", " ", APPLIED_PREFIX.sub("", str(text or ""))).strip()
    return trimmed[:1].upper() + trimmed[1:] if trimmed else ""


ACRONYMS = {"bbc", "cmu", "who", "ibm", "uk", "vat", "nhs"}


def token_label(name: str) -> str:
    return " ".join(part.upper() if part.lower() in ACRONYMS else part.capitalize()
                    for part in re.split(r"[-_]", name) if part)


def knowledge_text(knowledge: dict | None) -> str:
    """把改动兑现的那层机构知识念成一句话，与前端 knowledgeText 保持一致。"""
    if not knowledge:
        return ""
    if knowledge.get("layer") == "L3" and knowledge.get("philosophy"):
        quote = clean(knowledge.get("quote"))
        return f"For {knowledge['philosophy']}: {quote}" if quote else f"For {knowledge['philosophy']} design identity."
    if knowledge.get("layer") == "L2" and knowledge.get("condition"):
        lead = f"When {knowledge['condition']}."
        story = clean(knowledge.get("quote"))
        return f"{lead} {story}" if story else lead
    bits = []
    if knowledge.get("applied"):
        bits.append(clean(knowledge["applied"]))
    tokens = knowledge.get("tokens") or []
    if not bits and tokens:
        bits.append("House colors: " + ", ".join(f"{token_label(t['name'])} ({t['value']})" for t in tokens) + ".")
    if knowledge.get("rule"):
        bits.append(clean(knowledge["rule"]))
    return " ".join(bits)


def distinct(values, limit):
    seen, out = set(), []
    for raw in values:
        value = clean(raw)
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        out.append(value)
    return out[:limit]


def classify(change: dict) -> str:
    blob = " ".join(str(change.get(k) or "") for k in ("id", "rule_id", "label", "reason", "prompt")).lower()
    for name, pattern in CATEGORY:
        if re.search(pattern, blob):
            return name
    return "other"


def summarize(bundle: list[dict]) -> dict:
    threads: dict[str, list[dict]] = defaultdict(list)
    for change in bundle:
        threads[str(change.get("rule_id") or change.get("id"))].append(change)
    primary = sorted(threads.values(), key=len, reverse=True)[0]

    details = [c.get("component_detail") or {} for c in primary]
    details = [d for d in details if clean(d.get("after"))]
    after_text = " ".join(str(d.get("after") or "") for d in details)
    # 知识必须出自贡献了展示说明的那几条改动，否则会出现说明与依据对不上号的卡片
    spoken, said = [], set()
    for change in primary:
        line = clean(change.get("reason")).lower()
        if not line or line in said or len(spoken) >= 2:
            continue
        said.add(line)
        spoken.append(change)
    treatment = " ".join(clean(c.get("reason")) for c in spoken) or clean(primary[0].get("label"))
    normalize = lambda text: re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()  # noqa: E731
    lines, seen = [], set()
    for change in (spoken or primary):
        items = change.get("knowledge_layers") or ([change["knowledge"]] if change.get("knowledge") else [])
        for item in items:
            text = knowledge_text(item)
            key = f"{item.get('layer')}:{normalize(text)}"
            if not text or key in seen or normalize(text) in normalize(treatment):
                continue
            seen.add(key)
            lines.append({"layer": item.get("layer"), "text": text})
    return {
        "problem": (distinct([c.get("problem") for c in primary], 1) or [""])[0],
        "treatment": treatment,
        "knowledge": lines,
        "layer": (lines[0]["layer"] if lines else ""),
        "colors": list(dict.fromkeys(HEX_COLOR.findall(after_text)))[:5],
    }


def main() -> int:
    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    document, error = load_record(run_id)
    if document is None:
        print(error or "用法: python scripts/preview_change_copy.py <run_id>")
        return 1

    registry = PersonaRegistry(data_dir=settings.data_dir, custom_dir=settings.storage_dir / "personas")
    missing_knowledge = total = 0
    layers: dict[str, int] = defaultdict(int)
    for agent in document["agents"]:
        proposal = agent.get("proposal")
        if not isinstance(proposal, dict):
            continue
        _backfill_evidence(proposal, registry.get(str(agent["persona_id"])))
        buckets: dict[str, list[dict]] = defaultdict(list)
        for change in proposal.get("changes") or []:
            buckets[classify(change)].append(change)
        print(f"\n{'=' * 78}\n{agent['persona_id']}\n{'=' * 78}")
        for category, bundle in buckets.items():
            summary = summarize(bundle)
            total += 1
            missing_knowledge += not summary["knowledge"]
            layers[summary["layer"] or "(未归因)"] += 1
            print(f"\n  ── {category}  ({len(bundle)} change{'s' if len(bundle) > 1 else ''})")
            print(f"     CHANGE    {summary['treatment']}")
            for line in summary["knowledge"]:
                print(f"     KNOWLEDGE [{line['layer']}] {line['text']}")

    print(f"\n{'=' * 78}")
    print(f"议题卡 {total} 张：缺机构知识 {missing_knowledge}")
    print("层级归因： " + "  ".join(f"{k}={v}" for k, v in sorted(layers.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
