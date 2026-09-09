"""Frontend-compatible run orchestration for the clean-room v2 advisor.

The v2 design engine stays isolated in :mod:`service`; this module owns only the
existing HTTP run/polling contract so the frontend does not need an engine-specific
branch.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import settings
from ..core.persona import Persona, PersonaRegistry
from ..core.proposal_explainer import summarize_proposal
from ..core.semantic_composer import compact_primary_data, compose_component_slots
from ..core.specfacts import extract_facts
from ..llm import LLMClient
from ..llm_log import LLMRunLog, bind_llm_persona, bind_llm_run_log, ensure_log_and_record, reset_llm_persona, reset_llm_run_log
from .change_scope import SCOPE_PRIORITY as _SCOPE_PRIORITY
from .change_scope import scopes_for_path as _shared_scopes_for_path
from .service import AdvisorV2


STATUS_PROGRESS = {"pending": 0.05, "reading": 0.2, "detecting": 0.45, "adjudicating": 0.7, "compiling": 0.9, "done": 1.0, "error": 1.0}


class AdvisorStageTimeout(TimeoutError):
    """A visible four-beat stage failed to make progress within its budget."""


def _pointer(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


_WALKABLE_VIEW_ARRAYS = {"vconcat", "hconcat", "concat", "layer"}


def _spec_patches(before: object, after: object, path: tuple[str, ...] = ()) -> list[dict]:
    """JSON-pointer diff for composable presentation properties.

    View trees (vconcat / layer) are walked so a bar-colour change inside an
    existing concat is a colour leaf, not one atomic ``/vconcat`` replacement.
    Data tables, tick lists and title-line arrays stay atomic.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        patches: list[dict] = []
        for key in sorted(set(before) | set(after)):
            child = path + (str(key),)
            if key not in after:
                patches.append({"op": "remove", "path": _pointer(child)})
            elif key not in before:
                # Newly introduced config/encoding objects still contain
                # independently composable leaves (for example axis font and
                # grid settings).  A newly introduced view array is topology.
                if isinstance(after[key], dict):
                    patches.extend(_spec_patches({}, after[key], child))
                else:
                    patches.append({"op": "set", "path": _pointer(child), "value": copy.deepcopy(after[key])})
            else:
                patches.extend(_spec_patches(before[key], after[key], child))
        return patches
    key = path[-1] if path else ""
    if key in _WALKABLE_VIEW_ARRAYS and isinstance(before, list) and isinstance(after, list):
        patches = []
        for index in range(max(len(before), len(after))):
            child = path + (str(index),)
            if index >= len(after):
                patches.append({"op": "remove", "path": _pointer(child)})
            elif index >= len(before):
                patches.append({"op": "set", "path": _pointer(child), "value": copy.deepcopy(after[index])})
            else:
                patches.extend(_spec_patches(before[index], after[index], child))
        return patches
    if before != after:
        return [{"op": "set", "path": _pointer(path), "value": copy.deepcopy(after)}]
    return []


_STRUCTURAL_KEYS = {"data", "transform", "layer", "vconcat", "hconcat", "concat", "facet", "repeat", "resolve"}


def _is_new_structural_branch(original: object, path: str) -> bool:
    """True when the patch sits on a concat/layer/data branch the source did not have."""
    node: object = original
    for part in path.strip("/").split("/"):
        if isinstance(node, list):
            try:
                index = int(part)
            except ValueError:
                return True
            if index >= len(node):
                return True
            node = node[index]
            continue
        if not isinstance(node, dict) or part not in node:
            return part in _STRUCTURAL_KEYS or part.isdigit()
        node = node[part]
    return False


def _value_at_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return False, None
    current = document
    for raw in pointer.lstrip("/").split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return False, None
    return True, current


def _scopes_for_path(path: str) -> set[str]:
    """Compatibility wrapper for callers using the previous location."""
    return _shared_scopes_for_path(path)


def _scope_for_path(path: str) -> str:
    scopes = _scopes_for_path(path)
    return next(scope for scope in _SCOPE_PRIORITY if scope in scopes)


def _scopes_for_diff_path(path: str, original: dict, candidate: dict) -> set[str]:
    """Add semantic ownership knowable only from source/candidate context."""
    return _shared_scopes_for_path(path, original, candidate)


def _materialize_claimed_descendant_patches(
    original: dict, candidate: dict, patches: list[dict], rows: list[dict]
) -> None:
    """Prove exact claimed leaves covered by an atomic structural diff.

    A newly added layer stays atomic for safe composition, but Beat 3 may
    truthfully cite ``/layer/0/mark/type``. If that leaf exists only because an
    ancestor layer was added, record it as evidence-only instead of rejecting
    the claim for not being a top-level diff atom.
    """
    known = {str(patch.get("path") or "") for patch in patches}
    atomic = [
        patch for patch in patches
        if not patch.get("evidence_only") and patch.get("op") in {"set", "remove"}
    ]
    claimed = {
        path
        for row in rows
        for path in ((row.get("component_detail") or {}).get("spec_paths") or [])
        if isinstance(path, str) and path.startswith("/")
    }
    for path in sorted(claimed):
        if path in known:
            continue
        covering = [
            patch for patch in atomic
            if path.startswith(str(patch.get("path") or "").rstrip("/") + "/")
        ]
        if not covering:
            continue
        parent = max(covering, key=lambda patch: len(str(patch.get("path") or "")))
        op = str(parent.get("op") or "")
        source_exists, source_value = _value_at_pointer(original, path)
        candidate_exists, candidate_value = _value_at_pointer(candidate, path)
        if op == "set" and candidate_exists and (not source_exists or source_value != candidate_value):
            patches.append({"op": "set", "path": path, "value": copy.deepcopy(candidate_value), "evidence_only": True})
            known.add(path)
        elif op == "remove" and source_exists and not candidate_exists:
            patches.append({"op": "remove", "path": path, "evidence_only": True})
            known.add(path)


def _presentation_descendant_patches(patch: dict) -> list[dict]:
    """Inventory visual leaves inside an atomically added structural branch.

    The topology itself remains one structural patch for safe fallback, while
    component contracts gain exact evidence paths inside a new layer. These
    evidence-only atoms are never projected independently onto a foreign tree.
    """
    if patch.get("op") != "set" or not isinstance(patch.get("value"), (dict, list)):
        return []
    base = str(patch.get("path") or "")
    rows: list[dict] = []

    def walk(node: Any, parts: list[str]) -> None:
        pointer = base + "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in {"data", "transform"}:
                    continue
                walk(value, parts + [str(key)])
            return
        if isinstance(node, list):
            # Only style leaves are safe evidence inside a wholly new branch.
            # Axis/label fields may merely be the unchanged source view moved
            # under vconcat/layer and would create fictitious extra changes.
            if "color" in _scopes_for_path(pointer):
                rows.append({"op": "set", "path": pointer, "value": copy.deepcopy(node), "evidence_only": True})
                return
            for index, value in enumerate(node):
                walk(value, parts + [str(index)])
            return
        if "color" in _scopes_for_path(pointer):
            rows.append({"op": "set", "path": pointer, "value": copy.deepcopy(node), "evidence_only": True})

    walk(patch.get("value"), [])
    return rows


_COMPONENT_LABELS = {
    "title": "Title and narrative", "color": "Color and emphasis", "axes": "Axes and scales",
    "labels": "Labels and annotation", "typography": "Typography", "layout": "Layout and hierarchy",
    "structure": "Chart composition and marks",
}


def _commitment_scope(commitment: dict) -> str:
    """Use the persona's declared component before falling back to evidence paths."""
    declared = str(commitment.get("component") or "").lower().strip()
    aliases = {"colour": "color", "annotation": "labels", "legend": "labels", "mark": "structure", "marks": "structure", "narrative": "title"}
    # Beat 3 may name a compound component (for example ``axes / grid``).
    # The board needs one stable slot, while the original wording remains in
    # the human-readable claim.
    for part in re.split(r"[/:|,&]+", declared):
        part = aliases.get(part.strip(), part.strip())
        if part in _COMPONENT_LABELS:
            return part
    paths = commitment.get("spec_paths") if isinstance(commitment.get("spec_paths"), list) else []
    for path in paths:
        if isinstance(path, str) and path.startswith("/"):
            return _scope_for_path(path)
    claim = str(commitment.get("claim") or "").lower()
    # Colour words first: "title color" / "bar colors … takeaway" are colour
    # treatments, not narrative cards.
    if any(word in claim for word in ("colour", "color", "palette", "highlight", "background", "canvas")):
        return "color"
    if any(word in claim for word in ("title", "subtitle", "headline", "narrative")):
        return "title"
    if any(word in claim for word in ("axis", "tick", "grid", "scale")):
        return "axes"
    if any(word in claim for word in ("label", "annotation", "caption", "source", "legend")):
        return "labels"
    if any(word in claim for word in ("font", "type", "typograph")):
        return "typography"
    if any(word in claim for word in ("padding", "spacing", "layout", "width", "height")):
        return "layout"
    return "structure"


def _knowledge_index(persona: Persona) -> dict[str, dict]:
    """Index the persona's codified knowledge by the id a commitment may cite.

    Without this, every v2 change is flattened to ``L3-derived``/``should`` and
    the institution's own rule identifiers disappear from the record — which is
    precisely the provenance the fast/slow account depends on. A commitment
    that cites a real L1 rule must be recorded as L1, at that rule's declared
    strength, and one that cites nothing codified must stay honestly derived.
    """
    index: dict[str, dict] = {}
    # `story` 字段存的是叙事编号（"n-hierarchy"），正文在 persona.stories 里。
    # 直接把编号当依据展示，读者只会看到一截无意义的碎片，所以在这里解引用；
    # `quote` 取条文原句，`src` 保留它在指南中的位置。
    for rule in persona.rules:
        index[str(rule.id)] = {
            "layer": "L1", "strength": rule.strength or "must", "confidence": "high",
            "story": persona.story_text(rule.story) or rule.rule,
            "quote": rule.rule, "src": list(rule.src or []),
        }
    for adaptation in persona.adaptations:
        clause = _adaptation_clause(adaptation)
        index[str(adaptation.id)] = {
            "layer": "L2", "strength": adaptation.strength or "should", "confidence": "medium",
            "story": persona.story_text(adaptation.story) or clause,
            "quote": clause, "src": list(adaptation.src or []),
        }
    for item in persona.philosophy:
        index[str(item.id)] = {
            "layer": "L3", "strength": "may", "confidence": "medium",
            "story": item.quote or item.title,
            "quote": item.quote or item.title, "src": list(item.src or []),
        }
    return index


def _adaptation_clause(adaptation) -> str:
    """把 L2 的 when/then 结构还原成一句可读的条件条文。"""
    def phrase(value) -> str:
        if isinstance(value, dict):
            return ", ".join(f"{key.replace('_', ' ')} {phrase(item)}" for key, item in value.items())
        if isinstance(value, list):
            return ", ".join(phrase(item) for item in value)
        return str(value)

    condition = phrase(adaptation.when) if adaptation.when else ""
    action = phrase(adaptation.then) if adaptation.then else ""
    if condition and action:
        return f"When {condition}: {action}"
    return condition or action or str(adaptation.id)


# 研究问题 §L3：机构设计哲学的关键词。用机构自己声明的哲学来解释一条改动，
# 比抛出规则编号有用得多——"For clarity design identity" 是设计师读得懂的理由。
_PHILOSOPHY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "clarity": ("clarity", "clear", "simple", "concise", "readab", "understandab", "less is more",
                "essential", "reduction", "declutter", "clutter", "cognitive load", "restraint", "unobtrusive",
                "at a glance", "easier to read", "quicker to", "scan", "tidy", "uncluttered"),
    "accuracy": ("accurate", "accuracy", "truthful", "precise", "faithful", "mislead", "distort"),
    "integrity": ("integrity", "attribution", "source", "complete", "consisten", "standard", "reliab", "journalism"),
    "narrativity": ("story", "narrative", "message", "emphasis", "highlight", "annotat", "context", "takeaway"),
    "accessibility": ("accessib", "colour-vision", "color-vision", "colorblind", "contrast", "assistive",
                      "impair", "legibilit", "all audiences", "inclusive"),
    "effectiveness": ("effective", "insight", "purpose", "function", "wayfinding", "guide", "convey", "useful"),
}

# L2 触发条件按研究问题 §L2 的三类（数据 / 意图 / 受众）念成一句人话
_CONDITION_PHRASE: dict[str, str] = {
    "intent": "the goal is to {value}",
    "communication_goal": "the goal is to {value}",
    "audience": "the audience is {value}",
    "data_role": "the series is {value}",
    "series_count": "the chart has {value} data series",
    "viewport": "the canvas is {value} wide",
    "viewport_px": "the canvas is {value} wide",
    "chart_type": "the chart is a {value}",
}

_COMPARATORS: dict[str, str] = {
    "gt": "more than", "gte": "at least", "lt": "fewer than", "lte": "at most",
    "eq": "", "ne": "not", "in": "one of", "contains": "containing",
}

_POINTER = re.compile(r"/[A-Za-z0-9_][A-Za-z0-9_./\[\]-]*")

_HEX_VALUE = re.compile(r"#[0-9A-Fa-f]{6}\b")
# 研究问题 §L1：落到图上的具体令牌（色值、字号）才算气质签名；引擎自述不算。
_L1_APPLIED = re.compile(r"#[0-9A-Fa-f]{6}|\d+\s*(?:pt|px)\b", re.IGNORECASE)
_ENGINE_JARGON = re.compile(
    r"l1 signature|fast[- ]lane|re-verified|violated the institution|title\s*=\s*null|"
    r"orient\s*=|r\s*==\s*1|defaults applied|no explicit|authored_by|contract check",
    re.IGNORECASE,
)

_EVIDENCE_LISTS = ("findings", "acceptance_findings")


def _philosophy_keyword(text: str, among: set[str] | None = None, *, min_hits: int = 1) -> str:
    """把一段文字归到设计哲学关键词上；归不到就不硬归。

    `among` 限定候选范围。解释一条改动时只在**该机构宣示过**的哲学里挑。
    从改动理由里猜时要求至少两个词命中，避免 "consistent" 一词就套上 integrity。
    """
    blob = text.lower()
    best, best_hits = "", 0
    for keyword, lexicon in _PHILOSOPHY_KEYWORDS.items():
        if among is not None and keyword not in among:
            continue
        hits = sum(1 for term in lexicon if term in blob)
        if hits > best_hits:
            best, best_hits = keyword, hits
    return best if best_hits >= min_hits else ""


_TOKEN_ACRONYMS = {"bbc", "cmu", "who", "ibm", "uk", "vat", "nhs"}


def _token_label(name: str) -> str:
    """bbc-blue → BBC Blue；london-10 → London 10。馆定色名比裸 hex 有解释力。"""
    return " ".join(
        part.upper() if part.lower() in _TOKEN_ACRONYMS else part.capitalize()
        for part in re.split(r"[-_]", name) if part
    )


def _token_names(persona: Persona) -> dict[str, str]:
    """色值 → 机构给它起的名字。

    研究问题 §L1 把「无条件适用的色板、品牌色」列为气质签名的一部分，而 persona 的
    `tokens` 正是这份命名色板。改后用到的具体色值若能回认成命名令牌，这本身就是
    可核验的 L1 知识——远比把 `#1A1A1A` 摆在一行灰字里有用。
    """
    names: dict[str, str] = {}
    for dotted, value in persona.token_index().items():
        if isinstance(value, str) and _HEX_VALUE.fullmatch(value.strip()):
            names.setdefault(value.strip().upper(), dotted.rsplit(".", 1)[-1])
    return names


def _explain_hex(text: str, names: dict[str, str]) -> str:
    """把裸 #333333 写成 BBC Gray (#333333)。已带括号的馆定写法不再套一层。"""
    def replace(match: re.Match) -> str:
        hex_value = match.group(0).upper()
        name = names.get(hex_value)
        return f"{_token_label(name)} ({hex_value})" if name else hex_value
    return re.sub(r"(?<!\()#[0-9A-Fa-f]{6}\b", replace, text)


def _applied_tokens(row: dict, names: dict[str, str]) -> list[dict[str, str]]:
    """这条改动落到图上的色值里，哪些是机构命名过的令牌。"""
    after = str((row.get("component_detail") or {}).get("after") or "")
    applied, seen = [], set()
    for value in _HEX_VALUE.findall(after):
        key = value.upper()
        if key in seen or key not in names:
            continue
        seen.add(key)
        applied.append({"name": names[key], "value": key})
    return applied[:4]


def _l1_applied_fact(row: dict, names: dict[str, str] | None = None) -> str:
    """改后状态若是具体的色值/字号，它本身就是 L1 气质签名。

    研究问题把 L1 定为无条件令牌：Color / Typography / Layout / Anatomy。
    色值要写成馆定色名，否则 Knowledge 就只剩一排没有理由的色块。
    """
    after = re.sub(r"\s+", " ", str((row.get("component_detail") or {}).get("after") or "")).strip()
    if not after or _ENGINE_JARGON.search(after) or not _L1_APPLIED.search(after):
        return ""
    return _explain_hex(after.rstrip("."), names or {})


def _persona_identity(persona: Persona) -> dict[str, str]:
    """机构声明过的设计哲学：philosophy id → 关键词。"""
    identity: dict[str, str] = {}
    for item in persona.philosophy:
        keyword = _philosophy_keyword(f"{item.title} {item.quote}")
        if keyword:
            identity[str(item.id)] = keyword
    return identity


def _condition_value(value) -> str:
    """比较式条件（`{gt: 600px}`）要念成 "more than 600px"，不能把字典摊在界面上。"""
    if isinstance(value, dict):
        return " and ".join(
            f"{_COMPARATORS.get(str(key), str(key))} {_condition_value(item)}".strip()
            for key, item in value.items()
        )
    if isinstance(value, list):
        return ", ".join(_condition_value(item) for item in value)
    return str(value).strip()


def _condition_text(when: dict) -> str:
    """把 L2 的 when 结构念成 "the goal is to …" 这样的条件从句。"""
    parts = []
    for key, value in (when or {}).items():
        phrase = _CONDITION_PHRASE.get(str(key))
        text = _condition_value(value)
        if not text:
            continue
        parts.append(phrase.format(value=text) if phrase else f"{str(key).replace('_', ' ')} is {text}")
    return " and ".join(parts)


def _implementation_index(layer_implementation: dict | None) -> dict[str, dict]:
    """索引拍3 的层级兑现自评：哪一层的哪条知识、落在了哪些 spec 节点上。

    这份自评一直在 facts 里，却从未与改动记录关联，因此界面上一条 L2 都看不到 ——
    机构的条件化适应恰恰是最值得展示的推理。以 spec 路径作证据把两边接起来。
    """
    index: dict[str, dict] = {}
    if not isinstance(layer_implementation, dict):
        return index
    for level in ("l1", "l2", "l3"):
        for entry in layer_implementation.get(level) or []:
            if not isinstance(entry, dict) or str(entry.get("status") or "") != "implemented":
                continue
            rule_id = str(entry.get("rule_id") or entry.get("id") or "").strip()
            if not rule_id:
                continue
            evidence = f"{entry.get('spec_evidence') or ''} {entry.get('trigger') or ''}"
            paths = {match.group(0).split("=")[0].rstrip(".,;") for match in _POINTER.finditer(evidence)}
            index[rule_id] = {"layer": level.upper(), "paths": {p for p in paths if len(p) > 1}}
    return index


def _realized_knowledge(paths: list[str], implementation: dict[str, dict]) -> list[tuple[str, dict]]:
    """按 spec 路径找出这条改动兑现的各层知识。一层只留一条，避免路径重叠误伤。

    一条改动常常同时兑现气质签名（L1）和条件适应（L2），再由叙事认同（L3）解释
    为什么值得这么做。只留一层会把其余知识藏起来。
    """
    owned = {path for path in paths if isinstance(path, str) and path.startswith("/")}
    if not owned:
        return []
    matches = [
        (rule_id, entry) for rule_id, entry in implementation.items()
        if any(p == q or p.startswith(f"{q}/") or q.startswith(f"{p}/") for p in owned for q in entry["paths"])
    ]
    order = {"L2": 0, "L1": 1, "L3": 2}
    matches.sort(key=lambda item: order.get(item[1]["layer"], 3))
    seen, unique = set(), []
    for rule_id, entry in matches:
        layer = entry["layer"]
        if layer in seen:
            continue
        seen.add(layer)
        unique.append((rule_id, entry))
    return unique


def _evidence_index(visual_review: dict | None) -> dict[str, dict[str, str]]:
    """Index the visual critic's findings by the id a commitment cites.

    A commitment records what the advisor *did*; the finding it answers records
    what was *wrong* and which guideline said so. Only the former survived into
    the change record, so the board could show the treatment but never the
    problem it treated. Commitments cite findings as ``acceptance_findings[2]``,
    which is exactly this index's key.
    """
    index: dict[str, dict[str, str]] = {}
    if not isinstance(visual_review, dict):
        return index
    sources = {"findings": visual_review.get("findings")}
    acceptance = visual_review.get("acceptance")
    if isinstance(acceptance, dict):
        sources["acceptance_findings"] = acceptance.get("findings")
    for name, findings in sources.items():
        if name not in _EVIDENCE_LISTS or not isinstance(findings, list):
            continue
        for position, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            problem = str(finding.get("issue") or "").strip()
            if not problem:
                continue
            entry = {
                "problem": problem,
                "observed": str(finding.get("image_evidence") or "").strip(),
                "severity": str(finding.get("severity") or "").strip(),
                # 审阅拍会给出 L1/L2/L3 出处，验收拍不给；取到就是逐字的指南依据。
                "guideline": str(finding.get("l3_ref") or "").strip(),
            }
            index[f"{name}[{position}]"] = entry
            # 同一条 finding 会被不同 persona 用不同写法引用（AF-1、finding 2…）。
            # 简写按 1 起计，越界就不认，宁可缺出处也不要张冠李戴。
            short = "AF" if name == "acceptance_findings" else "F"
            index.setdefault(f"{short}-{position + 1}", entry)
            index.setdefault(f"{short}{position + 1}", entry)
    return index


_EVIDENCE_ALIAS = re.compile(r"^(acceptance[\s_-]*finding|finding|af|f)s?[\s_\-\[]*(\d+)\]?$", re.IGNORECASE)


def _evidence_for(evidence_id: str, evidence: dict[str, dict[str, str]]) -> dict[str, str]:
    """Resolve a commitment's citation to the finding it answers, if any."""
    if evidence_id in evidence:
        return evidence[evidence_id]
    match = _EVIDENCE_ALIAS.match(evidence_id.strip())
    if not match:
        return {}
    prefix, number = match.group(1).lower(), int(match.group(2))
    acceptance = prefix.startswith("a") or prefix == "af"
    short = "AF" if acceptance else "F"
    return evidence.get(f"{short}-{number}", {})


def _l2_payload(persona: Persona, rule_id: str) -> dict | None:
    adaptation = next((item for item in persona.adaptations if str(item.id) == rule_id), None)
    if adaptation is None:
        return None
    condition = _condition_text(adaptation.when)
    if not condition:
        return None
    payload = {"layer": "L2", "condition": condition}
    story = persona.story_text(adaptation.story)
    if story:
        payload["quote"] = story
    return payload


def _l1_payload(row: dict, cited: dict | None, tokens: dict[str, str]) -> dict | None:
    applied_fact = _l1_applied_fact(row, tokens)
    applied_tokens = _applied_tokens(row, tokens)
    quote = (cited or {}).get("quote") or ""
    if not applied_fact and not applied_tokens and not quote:
        return None
    payload: dict = {"layer": "L1"}
    if applied_fact:
        payload["applied"] = applied_fact
    if applied_tokens:
        payload["tokens"] = applied_tokens
    if quote:
        payload["rule"] = quote
    return payload


def _l3_payload(persona: Persona, identity: dict[str, str], keyword: str) -> dict | None:
    if not keyword:
        return None
    payload = {"layer": "L3", "philosophy": keyword}
    item = next((entry for entry in persona.philosophy if identity.get(str(entry.id)) == keyword), None)
    if item is not None:
        if item.title:
            payload["title"] = item.title
        if item.quote:
            payload["quote"] = item.quote
    return payload


def _attach_knowledge(
    persona: Persona,
    row: dict,
    knowledge: dict[str, dict],
    implementation: dict[str, dict],
    identity: dict[str, str],
    tokens: dict[str, str],
) -> None:
    """给一条改动配上它兑现的各层机构知识。

    一条改动很少只碰一层：馆定色是 L1 Traits，在这张图上启用它的条件是 L2
    Adaptations，而「为了清晰」是 L3 Identity。只留一层会把其余推理藏起来。
    """
    cited_id = str(row.get("rule_id") or "")
    cited = knowledge.get(cited_id)
    paths = (row.get("component_detail") or {}).get("spec_paths") or []
    realized = [] if cited is not None else _realized_knowledge(paths, implementation)

    if realized:
        rule_id, entry = realized[0]
        row["layer"] = entry["layer"]
        cited = knowledge.get(rule_id) or cited
        row["warrant"]["story_id"] = rule_id
        if cited:
            row["warrant"]["quote"] = cited.get("quote") or row["warrant"].get("quote") or ""
            row["warrant"]["story"] = cited.get("story") or row["warrant"].get("story") or ""
            row["warrant"]["src"] = list(cited.get("src") or row["warrant"].get("src") or [])
            row["warrant"]["derived"] = False

    layers: list[dict] = []
    seen: set[str] = set()

    def add(payload: dict | None) -> None:
        if not payload or payload["layer"] in seen:
            return
        seen.add(payload["layer"])
        layers.append(payload)

    for rule_id, _entry in realized:
        info = knowledge.get(rule_id) or {}
        level = str(info.get("layer") or _entry["layer"])
        if level == "L2":
            add(_l2_payload(persona, rule_id))
        elif level == "L1":
            add(_l1_payload(row, info, tokens))
        elif level == "L3":
            add(_l3_payload(persona, identity, identity.get(rule_id) or _philosophy_keyword(
                f"{info.get('quote') or ''} {info.get('story') or ''}", among=set(identity.values()), min_hits=2,
            )))

    if cited is not None:
        level = str(cited.get("layer") or "")
        if level == "L2":
            add(_l2_payload(persona, cited_id) or _l2_payload(persona, str(row["warrant"].get("story_id") or "")))
        elif level == "L1":
            add(_l1_payload(row, cited, tokens))
        elif level == "L3":
            add(_l3_payload(persona, identity, identity.get(cited_id) or identity.get(str(row["warrant"].get("story_id") or ""))))

    # 路径没对上时，落到图上的馆定令牌仍是 L1；理由里的哲学仍是 L3
    add(_l1_payload(row, cited if cited and cited.get("layer") == "L1" else None, tokens))
    spoken = f"{row.get('label') or ''} {row.get('reason') or ''} {(row.get('component_detail') or {}).get('after') or ''}"
    add(_l3_payload(persona, identity, identity.get(str(row["warrant"].get("story_id") or ""))
                    or _philosophy_keyword(spoken, among=set(identity.values()), min_hits=2)))

    if not layers:
        return
    order = {"L2": 0, "L1": 1, "L3": 2}
    layers.sort(key=lambda item: order.get(item["layer"], 3))
    row["knowledge"] = layers[0]
    row["knowledge_layers"] = layers
    row["layer"] = "L3-derived" if layers[0]["layer"] == "L3" and cited is None and not realized else layers[0]["layer"]


def _manifest_rows(
    persona: Persona,
    commitments: list[dict],
    candidate: dict,
    evidence: dict[str, dict[str, str]] | None = None,
    implementation: dict[str, dict] | None = None,
) -> list[dict]:
    """Expose every Beat-3 commitment as an independently composable slot.

    ``candidate`` is retained as a private source of the selected component,
    not as an instruction to replace the whole chart.  The composer chooses a
    structural scaffold once and then overlays the other selected slots.
    """
    knowledge = _knowledge_index(persona)
    identity = _persona_identity(persona)
    tokens = _token_names(persona)
    rows: list[dict] = []
    for index, commitment in enumerate(commitments):
        if not isinstance(commitment, dict):
            continue
        # 快道补丁的自述（"L1 signature re-verified"）不是给设计师看的改动说明
        if commitment.get("authored_by") == "fast_lane_contract_enforcement":
            continue
        claim = str(commitment.get("claim") or "").strip()
        if not claim or _ENGINE_JARGON.search(claim):
            continue
        scope = _commitment_scope(commitment)
        cid = str(commitment.get("id") or f"component-{index + 1}")
        evidence_id = str(commitment.get("evidence_id") or "advisor-v2")
        paths = [path for path in (commitment.get("spec_paths") or []) if isinstance(path, str) and path.startswith("/")]
        # 引用了机构真实规则 id 就按该规则的层级与强度记录；引用不到就如实标为
        # 由 L3 推导，而不是把两种来源混成同一个标签。
        cited = knowledge.get(evidence_id)
        provenance = cited or {"layer": "L3-derived", "strength": "should", "confidence": "medium", "story": claim, "src": [evidence_id]}
        # 引用视觉审阅结论时，把「当初看到的问题」与它援引的指南一并带上；引用机构
        # 规则时，规则自身就是依据。两者都填进 warrant.quote —— 这个字段本就是留给
        # 指南原文的，此前一直空着。
        finding = _evidence_for(evidence_id, evidence or {})
        row = {
            "id": f"{persona.id}:v2:component:{cid}", "rule_id": evidence_id, "scope": scope,
            "label": _COMPONENT_LABELS[scope], "reason": claim, "prompt": claim,
            "layer": provenance["layer"], "strength": provenance["strength"], "confidence": provenance["confidence"], "status": "applied",
            "component_detail": {"before": commitment.get("before"), "after": commitment.get("after"), "spec_paths": paths, "execution": "semantic_component_composition"},
            "warrant": {
                "src": provenance["src"] or [evidence_id], "story_id": evidence_id,
                "story": provenance["story"] or claim,
                "quote": (cited or {}).get("quote") or finding.get("guideline") or "",
                "source_file": persona.source_file or "persona knowledge base",
                "derived": cited is None,
            },
            "ops": [{"action": "compose_component", "component": scope, "candidate_spec": candidate, "spec_paths": paths}],
        }
        if finding.get("problem"):
            row["problem"] = finding["problem"]
            if finding.get("observed"):
                row["problem_evidence"] = finding["observed"]
            if finding.get("severity"):
                row["severity"] = finding["severity"]
        _attach_knowledge(persona, row, knowledge, implementation or {}, identity, tokens)
        rows.append(row)
    return rows


def _component_changes(
    persona: Persona,
    original: dict,
    candidate: dict,
    commitments: list[dict],
    visual_review: dict | None = None,
    layer_implementation: dict | None = None,
) -> list[dict]:
    """Expose truthful component contracts, including non-portable structure.

    Portable presentation leaves retain a deterministic fallback op. New
    topology is represented as a first-class structure decision whose complete
    candidate is evidence for the LLM composer, not a whole-spec copy command.
    """
    patches = _spec_patches(original, candidate)
    # Keep structural container patches for topology, and add exact visual
    # leaves as evidence so a Color/Labels/Axes card can truthfully point into
    # a newly introduced layer without making that leaf independently portable.
    known_paths = {str(patch.get("path") or "") for patch in patches}
    for patch in list(patches):
        for evidence_patch in _presentation_descendant_patches(patch):
            evidence_path = str(evidence_patch.get("path") or "")
            if evidence_path and evidence_path not in known_paths:
                patches.append(evidence_patch)
                known_paths.add(evidence_path)
    # 卡片里携带的候选图只作取值证据，主数据由组装时按源图还原，避免同一张
    # 数据表在一个 persona 的十几条卡片里被重复序列化。diff 仍用完整候选图。
    transport = compact_primary_data(original, candidate)
    groups: dict[str, list[dict]] = {}
    structural_patches: list[dict] = []
    for patch in patches:
        path = str(patch.get("path") or "")
        scope = _scope_for_path(path)
        # Nested colour/type/axis leaves under vconcat/layer are portable enough
        # for the deterministic fallback. Structural changes are not portable,
        # but they are first-class design decisions for the LLM composer and
        # must not disappear from the Review Board.
        if patch.get("evidence_only"):
            groups.setdefault(scope, []).append(patch)
        elif scope == "structure" or _is_new_structural_branch(original, path):
            structural_patches.append(patch)
        else:
            groups.setdefault(scope, []).append(patch)

    rows = _manifest_rows(
        persona, commitments, transport,
        _evidence_index(visual_review), _implementation_index(layer_implementation),
    )
    # A structural diff deliberately keeps a newly created/removed layer as
    # one atomic patch.  When the advisor explicitly claims an exact leaf
    # inside that branch, materialize the leaf as evidence so the claim can be
    # checked without making it independently portable.
    _materialize_claimed_descendant_patches(original, candidate, patches, rows)
    covered_paths: set[str] = set()
    first_by_scope: dict[str, dict] = {}
    for row in rows:
        scope = str(row.get("scope") or "")
        first_by_scope.setdefault(scope, row)
        detail = row.get("component_detail") if isinstance(row.get("component_detail"), dict) else {}
        for path in detail.get("spec_paths") or []:
            if isinstance(path, str) and path.startswith("/"):
                covered_paths.add(path)
        for op in row.get("ops") or []:
            if isinstance(op, dict) and op.get("action") == "compose_component" and "spec_paths" not in op:
                op["spec_paths"] = [path for path in (detail.get("spec_paths") or []) if isinstance(path, str)]

    claims = [str(item.get("claim") or "") for item in commitments if isinstance(item, dict)]
    labels = {
        "title": "Title and narrative", "color": "Color and emphasis", "axes": "Axes and scales",
        "labels": "Labels and annotation", "typography": "Typography", "layout": "Layout and hierarchy",
        "structure": "Overall approach",
    }
    knowledge = _knowledge_index(persona)
    identity = _persona_identity(persona)
    tokens = _token_names(persona)
    implementation = _implementation_index(layer_implementation)

    for scope, scoped_patches in groups.items():
        leftover = [patch for patch in scoped_patches if patch.get("path") not in covered_paths]
        if not leftover:
            continue
        leftover_paths = [str(patch["path"]) for patch in leftover if isinstance(patch.get("path"), str)]
        if scope in first_by_scope:
            host = first_by_scope[scope]
            detail = host.setdefault("component_detail", {})
            if not isinstance(detail, dict):
                detail = {}
                host["component_detail"] = detail
            existing = [path for path in (detail.get("spec_paths") or []) if isinstance(path, str)]
            detail["spec_paths"] = list(dict.fromkeys(existing + leftover_paths))
            continue
        samples = []
        for patch in leftover:
            value = patch.get("value")
            if isinstance(value, str) and value.startswith("#"):
                samples.append(value.upper())
        sample_text = ", ".join(list(dict.fromkeys(samples))[:4])
        related = [claim for claim in claims if scope in claim.lower()]
        reason = related[0] if related else (
            f"Applied: the {labels[scope].lower()} now follows {persona.name}'s redesign"
            + (f" ({sample_text})" if sample_text else ".")
        )
        row = {
            "id": f"{persona.id}:v2:{scope}", "rule_id": f"v2-{scope}", "scope": scope,
            "label": labels[scope], "reason": reason, "prompt": reason, "layer": "L3-derived",
            "strength": "should", "confidence": "medium", "status": "applied",
            "warrant": {"src": ["advisor-v2"], "story_id": "advisor-v2", "story": reason, "quote": "", "source_file": "persona knowledge base", "derived": True},
            "component_detail": {
                "before": "",
                "after": sample_text,
                "spec_paths": leftover_paths,
                "execution": "semantic_component_composition",
            },
            "ops": [{"action": "compose_component", "component": scope, "candidate_spec": transport, "spec_paths": leftover_paths}],
            "contract": {
                "verified": True,
                "source": "programmatic_diff_inventory",
                "scope": scope,
                "actual_paths": leftover_paths,
                "removed_paths": [],
            },
        }
        _attach_knowledge(persona, row, knowledge, implementation, identity, tokens)
        rows.append(row)

    # Structural topology is intentionally not projected leaf-by-leaf, but it
    # must remain selectable and visible. The LLM composer receives the whole
    # candidate plus these exact added/changed/removed paths and reconstructs a
    # coherent final tree; mock/failure fallback applies only surviving paths.
    structural_leftover = [
        patch for patch in structural_patches
        if str(patch.get("path") or "") not in covered_paths
    ]
    if structural_leftover:
        set_paths = [
            str(patch["path"]) for patch in structural_leftover
            if patch.get("op") == "set" and isinstance(patch.get("path"), str)
        ]
        removed_paths = [
            str(patch["path"]) for patch in structural_leftover
            if patch.get("op") == "remove" and isinstance(patch.get("path"), str)
        ]
        structure_reason = (
            f"Rebuild the chart composition and mark structure using {persona.name}'s complete design, "
            "including the containers, transforms and annotation branches required by that approach."
        )
        row = {
            "id": f"{persona.id}:v2:structure",
            "rule_id": "v2-structure",
            "scope": "structure",
            "label": _COMPONENT_LABELS["structure"],
            "reason": structure_reason,
            "prompt": structure_reason,
            "layer": "L3-derived",
            "strength": "should",
            "confidence": "high",
            "status": "applied",
            "warrant": {
                "src": ["advisor-v2-diff"],
                "story_id": "advisor-v2-structure",
                "story": structure_reason,
                "quote": "",
                "source_file": "source→candidate diff inventory",
                "derived": True,
            },
            "component_detail": {
                "before": "Original chart topology",
                "after": f"{persona.name} chart topology",
                "spec_paths": set_paths,
                "execution": "llm_full_spec_reconstruction",
            },
            "ops": [{
                "action": "compose_component",
                "component": "structure",
                "candidate_spec": transport,
                "spec_paths": set_paths,
            }],
            "contract": {
                "verified": True,
                "source": "programmatic_diff_inventory",
                "scope": "structure",
                "actual_paths": [str(patch.get("path") or "") for patch in structural_leftover],
                "removed_paths": removed_paths,
            },
        }
        _attach_knowledge(persona, row, knowledge, implementation, identity, tokens)
        rows.append(row)

    # Attach a machine-verifiable source→candidate contract after fallback
    # diff paths have been merged into manifest rows. A Beat-3 sentence is not
    # trusted merely because it sounds right: every displayed component must
    # point to real diff atoms owned by that component.
    patch_by_path = {str(patch.get("path") or ""): patch for patch in patches}
    for row in rows:
        detail = row.get("component_detail") if isinstance(row.get("component_detail"), dict) else {}
        claimed = [path for path in (detail.get("spec_paths") or []) if isinstance(path, str) and path.startswith("/")]
        scope = str(row.get("scope") or "structure")
        existing = row.get("contract") if isinstance(row.get("contract"), dict) else {}
        actual_paths = list(dict.fromkeys(existing.get("actual_paths") or claimed))
        set_paths = [path for path in actual_paths if patch_by_path.get(path, {}).get("op") == "set"]
        removed_paths = [path for path in actual_paths if patch_by_path.get(path, {}).get("op") == "remove"]
        portable_set_paths = [path for path in set_paths if not patch_by_path[path].get("evidence_only")]
        portable_removed_paths = [path for path in removed_paths if not patch_by_path[path].get("evidence_only")]
        verification_errors: list[str] = []
        if not actual_paths:
            verification_errors.append("no_actual_diff_paths")
        for path in actual_paths:
            patch = patch_by_path.get(path)
            if patch is None:
                verification_errors.append(f"path_not_in_source_candidate_diff:{path}")
                continue
            compatible = _scopes_for_diff_path(path, original, candidate)
            if scope != "structure" and scope not in compatible:
                verification_errors.append(
                    f"scope_mismatch:{path}:expected={scope}:compatible={','.join(sorted(compatible))}"
                )
        verified = not verification_errors
        for op in row.get("ops") or []:
            if isinstance(op, dict) and op.get("action") == "compose_component":
                op["spec_paths"] = portable_set_paths
                op["removed_paths"] = portable_removed_paths
                op["evidence_paths"] = actual_paths
                if actual_paths and not (portable_set_paths or portable_removed_paths):
                    op["requires_llm_reconstruction"] = True
        row["contract"] = {
            "verified": verified,
            "source": str(existing.get("source") or "source_candidate_diff"),
            "scope": scope,
            "actual_paths": actual_paths,
            "set_paths": set_paths,
            "removed_paths": removed_paths,
            "compatible_scopes": {
                path: sorted(_scopes_for_diff_path(path, original, candidate))
                for path in actual_paths if path in patch_by_path
            },
            "verification_errors": verification_errors,
        }
    return rows


def _attach_bundle_contract(original: dict, candidate: dict, rows: list[dict]) -> list[dict]:
    """Declare that selecting one advisor's full manifest reproduces its spec.

    A candidate may contain nested layers that cannot be losslessly projected
    from an isolated component onto a different scaffold.  That is acceptable
    for cross-persona composition, but selecting *all* records from one advisor
    must be an identity operation.  The contract is machine metadata, never a
    user-facing whole-chart change or rationale.
    """
    executable = [row for row in rows if any(op.get("action") == "compose_component" for op in (row.get("ops") or []))]
    if not executable:
        return rows
    change_ids = [str(row.get("id")) for row in executable]
    fingerprint = hashlib.sha256(json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    bundle_id = f"advisor-bundle:{fingerprint}"
    selections = [
        {"id": str(row.get("id")), "component": op.get("component") or row.get("scope"), "candidate_spec": candidate,
         "spec_paths": list(op.get("spec_paths") or []), "removed_paths": list(op.get("removed_paths") or [])}
        for row in executable for op in (row.get("ops") or []) if isinstance(op, dict) and op.get("action") == "compose_component"
    ]
    projected, _applied, _conflicts, _notes = compose_component_slots(original, selections)
    contract = {"id": bundle_id, "change_ids": change_ids, "self_composition_verified": projected == candidate}
    for row in executable:
        for op in row.get("ops") or []:
            if isinstance(op, dict) and op.get("action") == "compose_component":
                op["bundle"] = contract
    return rows


@dataclass
class V2AgentState:
    persona_id: str
    status: str = "pending"
    proposal: dict | None = None
    error: str = ""

    def payload(self) -> dict:
        return {
            "persona_id": self.persona_id,
            "status": self.status,
            "progress": STATUS_PROGRESS.get(self.status, 0),
            "proposal": self.proposal,
            "error": self.error or None,
        }


@dataclass
class V2RunState:
    run_id: str
    spec: dict
    context: dict
    agents: dict[str, V2AgentState]
    order: list[str]
    created_at: str
    status: str = "running"
    replay_of: str | None = None
    llm_log: LLMRunLog | None = field(default=None, repr=False)
    _supervisor: asyncio.Task | None = field(default=None, repr=False)

    def payload(self) -> dict:
        payload = {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            "agents": [self.agents[pid].payload() for pid in self.order],
        }
        if self.replay_of:
            # 让前端与留痕都能分辨这是复现而非新的一次咨询。复现时前端手里没有当初
            # 那张原图，随 payload 一并带上，省去为取一个 spec 而下载整份快照。
            payload["replay_of"] = self.replay_of
            payload["spec"] = self.spec
            payload["context"] = self.context
        return payload


class V2RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, V2RunState] = {}

    def get(self, run_id: str) -> V2RunState | None:
        return self._runs.get(run_id)

    def add(self, run: V2RunState) -> None:
        self._runs[run.run_id] = run

    def snapshot(self, run: V2RunState) -> None:
        try:
            runs_dir = Path(settings.storage_dir) / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            document = {
                "engine": "advisor-v2",
                "request": {"spec": run.spec, "persona_ids": run.order, "context": run.context},
                **run.payload(),
            }
            path = runs_dir / f"{run.run_id}.json"
            with path.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps({"engine": "advisor-v2", "run_id": run.run_id}) + "\n")
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except OSError as exc:
            print(f"[advisor-v2] 快照写入失败: {exc}")


def _allocate_run_id(store: V2RunStore) -> str:
    stamp = datetime.now().strftime("v2-%Y%m%d-%H%M")
    runs_dir = Path(settings.storage_dir) / "runs"
    suffix = 1
    while True:
        run_id = stamp if suffix == 1 else f"{stamp}-{suffix}"
        if store.get(run_id) is None and not (runs_dir / f"{run_id}.json").exists():
            return run_id
        suffix += 1


def _trace(result: dict) -> list[dict]:
    beats = result.get("beats") if isinstance(result.get("beats"), dict) else {}
    return [
        {"beat": 1, "lane": "slow", "name": "Read chart", "ms": 0, "summary": str((beats.get("beat1") or {}).get("story") or "Persona chart reading")},
        {"beat": 2, "lane": "fast", "name": "Collect evidence", "ms": 0, "summary": "Persona L1/L2/L3 evidence was made available to the independent contract."},
        {"beat": 3, "lane": "slow", "name": "Design contract", "ms": 0, "summary": str((beats.get("beat3") or {}).get("story") or "Persona design commitments")},
        {"beat": 4, "lane": "fast", "name": "Safety validation", "ms": 0, "summary": "The reconstructed spec was checked for Vega-Lite validity, source-data preservation and protected text."},
    ]


def _proposal(persona: Persona, original_spec: dict, result: dict, elapsed_ms: float) -> dict:
    beats = result.get("beats") if isinstance(result.get("beats"), dict) else {}
    contract = beats.get("beat3") if isinstance(beats.get("beat3"), dict) else {}
    audit = beats.get("beat4") if isinstance(beats.get("beat4"), dict) else {}
    applied_ids = {str(item) for item in result.get("applied_commitment_ids", [])}
    safety = audit.get("safety") if isinstance(audit.get("safety"), dict) else {}
    delivery_state = str(audit.get("delivery_state") or "ready")
    safety_reason = "; ".join(str(item) for item in safety.get("errors", []) if item) or "The full reconstructed specification did not pass the safety gate."
    changes, rejected = [], []
    commitments = contract.get("commitments") if isinstance(contract.get("commitments"), list) else []
    for commitment in commitments:
        if not isinstance(commitment, dict):
            continue
        commitment_id = str(commitment.get("id") or f"v2-{len(changes) + len(rejected) + 1}")
        warrant = {
            "src": [str(commitment.get("evidence_id") or "advisor-v2")],
            "story_id": str(commitment.get("evidence_id") or "advisor-v2"),
            "story": str(commitment.get("claim") or "Institutional guidance supports this decision."),
            "quote": "",
            "source_file": "persona knowledge base",
            "derived": True,
        }
        if commitment_id not in applied_ids:
            rejected.append({"rule_id": str(commitment.get("evidence_id") or "advisor-v2"), "layer": "L3-derived" if str(commitment.get("evidence_id", "")).startswith("L3") else "L2", "label": str(commitment.get("claim") or "Persona design commitment"), "reason": str(commitment.get("claim") or safety_reason), "src": warrant["src"]})
    # Commitments describe the persona's reasoning, but v2 used to attach the
    # same full replacement spec to every one.  Replace that presentation-only
    # list with actual composable deltas from source → accepted candidate.
    candidate_spec = result.get("spec") if isinstance(result.get("spec"), dict) else original_spec
    realized_commitments = [
        item for item in commitments
        if isinstance(item, dict) and str(item.get("id") or "") in applied_ids
    ]
    visual_review = audit.get("visual_review") if isinstance(audit.get("visual_review"), dict) else None
    implementation = contract.get("layer_implementation") if isinstance(contract.get("layer_implementation"), dict) else None
    granular_changes = _component_changes(
        persona, original_spec, candidate_spec, realized_commitments, visual_review, implementation,
    )
    if granular_changes:
        changes = granular_changes
    if not changes and safety.get("accepted") and result.get("spec") != original_spec:
        rejected.append({
            "rule_id": "advisor-v2-manifest", "layer": "L3-derived",
            "label": "Component manifest unavailable",
            "reason": "The candidate differs from the source, but its advisor did not return a truthful component-level manifest. It is intentionally not presented as a generic structure change.",
            "src": ["advisor-v2"],
        })
    if not changes and candidate_spec == original_spec:
        for commitment in commitments:
            if isinstance(commitment, dict) and str(commitment.get("id") or "") in applied_ids:
                rejected.append({"rule_id": str(commitment.get("evidence_id") or "advisor-v2"), "layer": "L3-derived" if str(commitment.get("evidence_id", "")).startswith("L3") else "L2", "label": str(commitment.get("claim") or "Persona design commitment"), "reason": "The candidate contained no executable visual delta, so this commitment was not presented as an applied change.", "src": [str(commitment.get("evidence_id") or "advisor-v2")]})
    if delivery_state == "needs_vega_lite_repair":
        # Preserve the old permissive workflow: the proposal and its component
        # explanations stay visible. Mark its operations as repair-required so
        # users can inspect the design without treating the code as validated.
        for change in changes:
            change["status"] = "suggested"
            detail = change.setdefault("component_detail", {})
            detail["execution"] = "requires_vega_lite_repair"
            for op in change.get("ops") or []:
                if isinstance(op, dict):
                    op["requires_vega_lite_repair"] = True
        errors = [str(item) for item in safety.get("errors", []) if item]
        changes.append({
            "id": f"{persona.id}:v2:vega_lite_repair", "rule_id": "v2-vega-lite-repair", "scope": "structure",
            "layer": "implementation", "status": "suggested", "label": "Vega-Lite implementation repair required",
            "reason": "The advisor's design candidate is retained for review, but its code must be repaired before it can be applied: " + (errors[0] if errors else "compiler validation failed."),
            "prompt": "Repair the listed Vega-Lite compiler error without changing the accepted design decisions.", "strength": "must", "confidence": "high",
            "component_detail": {"before": "candidate failed compiler validation", "after": "candidate requires an LLM Vega-Lite code repair", "spec_paths": [], "execution": "requires_vega_lite_repair"},
            "warrant": {"src": ["advisor-v2-safety"], "story_id": "advisor-v2-safety", "story": "The candidate needs a code repair before execution.", "quote": "", "source_file": "Vega-Lite compiler", "derived": True}, "ops": [],
        })
    changes = _attach_bundle_contract(original_spec, candidate_spec, changes)
    facts = (beats.get("beat2") or {}).get("facts") if isinstance(beats.get("beat2"), dict) else None
    facts_out = dict(facts) if isinstance(facts, dict) else extract_facts(original_spec)
    if visual_review is not None:
        # Kept in the existing facts envelope so the frontend contract stays unchanged.
        facts_out["visual_review"] = visual_review
    layer_implementation = contract.get("layer_implementation") if isinstance(contract.get("layer_implementation"), dict) else None
    if layer_implementation is not None:
        facts_out["layer_implementation"] = layer_implementation
    goal_implementation = contract.get("goal_implementation") if isinstance(contract.get("goal_implementation"), dict) else None
    if goal_implementation is not None:
        facts_out["goal_implementation"] = goal_implementation
    # Beat 4's L1 verification is the audit trail for the whole contract, so it
    # must survive into the stored run rather than staying inside the engine.
    verification = audit.get("l1_contract_verification") if isinstance(audit.get("l1_contract_verification"), dict) else {}
    if verification:
        facts_out["l1_contract_verification"] = verification
    # 程序做的确定性代码/版式纠错同样要留痕：它们改动了交付图，必须可追溯到程序
    # 而不是被默认算在 persona 的设计决策里。
    structural_repairs = safety.get("structural_repairs")
    if isinstance(structural_repairs, list) and structural_repairs:
        facts_out["structural_repairs"] = structural_repairs
    applied_count = len(changes)
    return {
        "persona_id": persona.id,
        "persona_name": persona.name,
        "facts": facts_out,
        "original_spec": original_spec,
        "prepared_spec": None,
        "modified_spec": result.get("spec") if isinstance(result.get("spec"), dict) else original_spec,
        "changes": changes,
        "rejected": rejected,
        # Same field and shape as the v1 engine: the post-generation verdict of
        # the institution's programmatic L1 rules on the delivered chart.
        "invariants": verification.get("after") or [],
        "trace": _trace(result),
        "summary": f"{contract.get('story') or 'The persona produced an independent four-beat design contract.'} ({applied_count} changes applied.)",
        "elapsed_ms": round(elapsed_ms, 1),
        "engine": "advisor-v2",
        "llm_errors": result.get("llm_errors") or [],
        "delivery_state": delivery_state,
        "delivery_reason": None,
    }


async def _agent_task(run: V2RunState, persona: Persona, llm: LLMClient) -> None:
    state = run.agents[persona.id]
    started = time.perf_counter()
    stage_started = time.monotonic()
    log_token = bind_llm_run_log(run.llm_log) if run.llm_log is not None else None
    persona_token = bind_llm_persona(persona.id)

    async def await_current_stage(awaitable: Any) -> Any:
        """Cancel a hung LLM/render step instead of leaving the UI polling forever.

        The budget measures time since the last observed progress, not since the
        beat began. A visible stage may contain many model round trips, so
        budgeting the whole chain at once would cancel a healthy persona.
        """
        nonlocal stage_started
        task = asyncio.create_task(awaitable)
        budget = settings.advisor_stage_timeout_seconds
        try:
            while not task.done():
                remaining = budget - (time.monotonic() - stage_started)
                if remaining <= 0:
                    raise AdvisorStageTimeout(
                        f"{state.status} 阶段超过 {budget} 秒没有任何进展，已停止该 persona 运行"
                    )
                await asyncio.wait({task}, timeout=min(remaining, 1.0))
            return task.result()
        except BaseException:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    try:
        async def on_stage(status: str) -> None:
            nonlocal stage_started
            state.status = status
            stage_started = time.monotonic()

        async def on_progress() -> None:
            nonlocal stage_started
            stage_started = time.monotonic()

        result = await await_current_stage(
            AdvisorV2(llm).advise(persona, run.spec, run.context, on_stage=on_stage, on_progress=on_progress)
        )
        proposal = _proposal(persona, run.spec, result, (time.perf_counter() - started) * 1000)
        # Keep the established frontend contract: replace code-like rule labels
        # with a grounded, user-facing explanation after the four beats finish.
        explanation = await await_current_stage(summarize_proposal(persona, proposal["facts"], proposal["changes"], proposal["trace"], llm))
        for change in proposal["changes"]:
            text = explanation.get("change_explanations", {}).get(str(change.get("id")))
            if text:
                change["reason"] = text
                change["prompt"] = text
        applied_count = sum(1 for change in proposal["changes"] if change.get("status") == "applied")
        proposal["summary"] = f"{explanation.get('goal_summary') or proposal['summary']} ({applied_count} changes applied.)"
        state.proposal = proposal
        state.status = "done"
    except asyncio.CancelledError as exc:
        failed_stage = state.status
        state.status = "error"
        state.error = f"CancelledError: {failed_stage} 阶段被中断"
        await ensure_log_and_record({
            "kind": "advisor_stage_error",
            "stage": failed_stage,
            "ok": False,
            "cancelled": True,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": state.error,
        })
        raise
    except Exception as exc:  # one persona must not fail the whole run
        failed_stage = state.status
        state.status = "error"
        state.error = f"{type(exc).__name__}: {exc}"
        await ensure_log_and_record({
            "kind": "advisor_stage_error",
            "stage": failed_stage,
            "ok": False,
            "cancelled": isinstance(exc, asyncio.CancelledError),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": state.error,
        })
    finally:
        reset_llm_persona(persona_token)
        if log_token is not None:
            reset_llm_run_log(log_token)


async def _supervise(run: V2RunState, personas: list[Persona], llm: LLMClient, store: V2RunStore) -> None:
    await asyncio.gather(*(_agent_task(run, persona, llm) for persona in personas))
    run.status = "done"
    if run.llm_log is not None:
        run.llm_log.flush()
    store.snapshot(run)


def start_run_v2(store: V2RunStore, registry: PersonaRegistry, llm: LLMClient, spec: dict, persona_ids: list[str], context: dict | None = None) -> tuple[V2RunState | None, str]:
    personas: list[Persona] = []
    for persona_id in persona_ids:
        persona = registry.get(persona_id)
        if persona is None:
            return None, f"未知 persona: {persona_id}"
        personas.append(persona)
    if not personas:
        return None, "persona_ids 不能为空"
    run_id = _allocate_run_id(store)
    run = V2RunState(run_id, spec, context or {}, {p.id: V2AgentState(p.id) for p in personas}, [p.id for p in personas], datetime.now(timezone.utc).isoformat(), llm_log=LLMRunLog(run_id=run_id, kind="advisor"))
    store.add(run)
    run._supervisor = asyncio.create_task(_supervise(run, personas, llm, store))
    return run, ""


async def wait_run_v2(run: V2RunState) -> None:
    if run._supervisor is not None:
        await run._supervisor
