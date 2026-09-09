"""Composer：用户跨机构选择性采纳 → 确定性合成终稿（+ 可选对话式微调）。

被采纳修改自带 ops（快道编译期产出的令牌直注记录），按采纳顺序确定性重放，
不经 LLM；自由文本指令仅在 live 模式交 LLM 微调，且校验输出仍是合法 spec。

合成前检测跨机构对同一 spec 节点的冲突修改：采纳项更多的 agent 胜出。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..llm import LLMClient, LLMError
from .actions import apply_ops_with_effect
from .semantic_composer import compose_atomic_component_patches, compose_component_slots
from .specfacts import validate_spec


def _persona_id_from_change(ch: dict) -> str:
    cid = str(ch.get("id") or ch.get("rule_id") or "change")
    if ":" in cid:
        return cid.split(":", 1)[0]
    return cid


def _flatten_config(node: Any, prefix: str = "config") -> list[tuple[str, str]]:
    """merge_config / set_font 等嵌套 config → (leaf_path, value_sig)。"""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten_config(v, path))
    else:
        out.append((prefix, json.dumps(node, sort_keys=True, ensure_ascii=False)))
    return out


def _op_effects(op: dict) -> list[tuple[str, str]]:
    """单个 op 影响的 spec 节点与效果签名（用于冲突检测）。"""
    action = op.get("action")
    if action == "set_mark_color":
        return [("mark.color", str(op.get("color", "")))]
    if action == "set_mark_type":
        effects = [("mark.type", str(op.get("mark_type", "")))]
        if op.get("chart_type") == "pie":
            effects.extend(
                [
                    ("encoding.theta", str(op.get("value_field", ""))),
                    ("encoding.color", str(op.get("category_field", ""))),
                ]
            )
        return effects
    if action == "remove_encoding_channel":
        return [(f"encoding.{op.get('channel', '')}", "__removed__")]
    if action == "set_color_range":
        colors = op.get("colors") or []
        return [("encoding.color.scale.range", json.dumps(colors, ensure_ascii=False))]
    if action == "highlight_category":
        sig = json.dumps(
            {k: op.get(k) for k in ("field", "value", "color", "base_color")},
            sort_keys=True,
            ensure_ascii=False,
        )
        return [("encoding.color", sig)]
    if action == "set_legend":
        parts = []
        if "orient" in op:
            parts.append(("encoding.color.legend.orient", str(op["orient"])))
        if "title" in op:
            parts.append(("encoding.color.legend.title", json.dumps(op["title"], ensure_ascii=False)))
        return parts or [("encoding.color.legend", json.dumps(op, sort_keys=True, ensure_ascii=False))]
    if action == "merge_config":
        return _flatten_config(op.get("config") or {})
    if action == "set_size":
        out = []
        if op.get("width") is not None:
            out.append(("width", str(op["width"])))
        if op.get("height") is not None:
            out.append(("height", str(op["height"])))
        return out
    if action == "set_background":
        return [("background", str(op.get("color", "")))]
    if action == "set_title_anchor":
        anchor = str(op.get("anchor", "start"))
        return [("title.anchor", anchor), ("config.title.anchor", anchor)]
    if action == "set_title_text":
        return [("title.text", str(op.get("text", "")))]
    if action == "set_source_note":
        return [("title.source", str(op.get("text", "")))]
    if action == "set_subtitle":
        out = [("title.subtitle", str(op.get("text", "")))]
        if op.get("font_size") is not None:
            out.append(("title.subtitleFontSize", str(op["font_size"])))
        if op.get("color") is not None:
            out.append(("title.subtitleColor", str(op["color"])))
        return out
    if action == "set_font":
        fam = str(op.get("family", ""))
        return [
            ("config.font", fam),
            ("config.title.font", fam),
            ("config.title.subtitleFont", fam),
            ("config.axis.labelFont", fam),
            ("config.axis.titleFont", fam),
            ("config.legend.labelFont", fam),
            ("config.legend.titleFont", fam),
        ]
    if action == "set_font_sizes":
        mapping = {
            "title": "config.title.fontSize",
            "subtitle": "config.title.subtitleFontSize",
            "axis_label": "config.axis.labelFontSize",
            "axis_title": "config.axis.titleFontSize",
            "legend_label": "config.legend.labelFontSize",
        }
        return [(path, str(op[key])) for key, path in mapping.items() if op.get(key) is not None]
    if action == "sort_categories":
        return [("encoding.sort", str(op.get("order", "desc")))]
    if action == "set_orientation":
        return [("encoding.orientation", str(op.get("to", "horizontal")))]
    if action in ("add_value_labels", "remove_value_labels"):
        # 同一节点：一方加数值标注、另一方要求移除 → 视为冲突
        return [("layer.value_labels", "on" if action == "add_value_labels" else "off")]
    if action == "direct_label":
        # 摘图例与挪图例（set_legend orient）落同一节点，能被判冲突
        return [("encoding.color.legend.orient", "__direct_label__")]
    if action == "set_axis_zero":
        return [("encoding.scale.zero", "true")]
    if action == "set_grid_style":
        return [("axis.gridDash", str(op.get("style", "dotted")))]
    if action == "set_band_padding":
        sig = json.dumps({k: op.get(k) for k in ("inner", "outer")}, sort_keys=True)
        return [("encoding.scale.bandPadding", sig)]
    if action == "compose_component":
        # Path-level nodes — never the whole candidate spec, or every v2
        # adoption would collide on a single fake "op.compose_component" node.
        paths = [p for p in (op.get("spec_paths") or []) if isinstance(p, str) and p.startswith("/")]
        if paths:
            cand = op.get("candidate_spec")
            blob = json.dumps(cand, sort_keys=True, ensure_ascii=False) if cand is not None else str(op.get("component") or "component")
            sig = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
            return [("spec" + path.replace("/", "."), sig) for path in paths]
        component = str(op.get("component") or "component")
        return [(f"component.{component}", component)]
    return [(f"op.{action}", json.dumps(op, sort_keys=True, ensure_ascii=False))]


def _compose_ops(change: dict) -> list[dict]:
    return [
        op for op in (change.get("ops") or [])
        if isinstance(op, dict) and op.get("action") == "compose_component"
    ]


def _atomic_patch_ops(change: dict) -> list[dict]:
    """Experimental replay manifest: exact set/remove component patches."""
    return [
        op for op in (change.get("ops") or [])
        if isinstance(op, dict) and op.get("action") == "apply_component_patch"
    ]


def _compose_selection(change: dict, op: dict) -> dict:
    detail = change.get("component_detail") if isinstance(change.get("component_detail"), dict) else {}
    paths = [p for p in (op.get("spec_paths") or detail.get("spec_paths") or []) if isinstance(p, str) and p.startswith("/")]
    return {
        "id": str(change.get("id") or change.get("rule_id") or "change"),
        "component": op.get("component") or change.get("scope") or "component",
        "candidate_spec": op.get("candidate_spec"),
        "spec_paths": paths,
    }


def _normalize_compose_conflict(conflict: dict, by_id: dict[str, dict]) -> dict:
    winner_id = str(conflict.get("winner_change_id") or "")
    loser_id = str(conflict.get("loser_change_id") or "")
    winner = by_id.get(winner_id) or {"id": winner_id}
    loser = by_id.get(loser_id) or {"id": loser_id}
    return {
        "node": conflict.get("node"),
        "winner_persona_id": _persona_id_from_change(winner),
        "winner_change_id": winner_id,
        "winner_label": str(winner.get("label") or winner_id),
        "loser_persona_id": _persona_id_from_change(loser),
        "loser_change_id": loser_id,
        "loser_label": str(loser.get("label") or loser_id),
        "winner_effect": str(conflict.get("winner_effect") or ""),
        "loser_effect": str(conflict.get("loser_effect") or ""),
        "reason": str(conflict.get("reason") or ""),
    }


def _persona_counts(changes: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ch in changes:
        if not ch.get("ops"):
            continue
        pid = _persona_id_from_change(ch)
        counts[pid] = counts.get(pid, 0) + 1
    return counts


def _persona_first_index(changes: list[dict]) -> dict[str, int]:
    order: dict[str, int] = {}
    for i, ch in enumerate(changes):
        if not ch.get("ops"):
            continue
        pid = _persona_id_from_change(ch)
        order.setdefault(pid, i)
    return order


def resolve_change_conflicts(changes: list[dict]) -> tuple[list[dict], list[dict]]:
    """跨机构同节点冲突检测与消解：采纳项更多的 persona 胜出。

    返回 (resolved_changes, conflicts)。
    conflicts 每项含 node、winner/loser persona 与 change、reason 等，供前端展示。
    """
    executable = [ch for ch in changes if ch.get("ops")]
    if len(executable) < 2:
        return changes, []

    counts = _persona_counts(changes)
    first_idx = _persona_first_index(changes)
    # (change_id, op_index) → 是否在冲突中落败
    suppressed: set[tuple[str, int]] = set()
    conflicts: list[dict] = []
    seen_conflict_pairs: set[tuple[str, str, str]] = set()

    # node → [{persona_id, change_id, op_index, effect, label}]
    by_node: dict[str, list[dict]] = {}
    for ch in executable:
        cid = str(ch.get("id") or ch.get("rule_id") or "change")
        pid = _persona_id_from_change(ch)
        label = str(ch.get("label") or ch.get("rule_id") or cid)
        for opi, op in enumerate(ch.get("ops") or []):
            for node, effect in _op_effects(op):
                by_node.setdefault(node, []).append(
                    {
                        "persona_id": pid,
                        "change_id": cid,
                        "op_index": opi,
                        "effect": effect,
                        "label": label,
                    }
                )

    for node, entries in by_node.items():
        sigs_by_persona: dict[str, list[dict]] = {}
        for e in entries:
            sigs_by_persona.setdefault(e["persona_id"], []).append(e)
        personas = list(sigs_by_persona.keys())
        if len(personas) < 2:
            continue
        distinct_effects = {e["effect"] for e in entries}
        if len(distinct_effects) <= 1:
            continue

        winner = max(personas, key=lambda p: (counts.get(p, 0), -first_idx.get(p, 9999)))
        winner_entries = sigs_by_persona[winner]
        winner_effect = winner_entries[0]["effect"]

        for persona in personas:
            if persona == winner:
                continue
            for entry in sigs_by_persona[persona]:
                pair_key = (node, winner, persona)
                if pair_key in seen_conflict_pairs:
                    pass
                else:
                    seen_conflict_pairs.add(pair_key)
                    win_count = counts.get(winner, 0)
                    lose_count = counts.get(persona, 0)
                    conflicts.append(
                        {
                            "node": node,
                            "winner_persona_id": winner,
                            "winner_change_id": winner_entries[0]["change_id"],
                            "winner_label": winner_entries[0]["label"],
                            "loser_persona_id": persona,
                            "loser_change_id": entry["change_id"],
                            "loser_label": entry["label"],
                            "winner_effect": winner_effect,
                            "loser_effect": entry["effect"],
                            "reason": (
                                f"修改冲突（节点 {node}）：{persona} 与 {winner} 意见不一致，"
                                f"已采用采纳项更多的 {winner}（{win_count} 项 vs {lose_count} 项）"
                            ),
                        }
                    )
                suppressed.add((entry["change_id"], entry["op_index"]))

    if not suppressed:
        return changes, []

    resolved: list[dict] = []
    for ch in changes:
        cid = str(ch.get("id") or ch.get("rule_id") or "change")
        ops = ch.get("ops") or []
        kept = [op for i, op in enumerate(ops) if (cid, i) not in suppressed]
        if ops and not kept:
            # 整条 change 的 ops 均被冲突消解 → 留给 apply 阶段 skipped
            resolved.append({**ch, "ops": [], "_conflict_dropped": True})
        elif kept != ops:
            resolved.append({**ch, "ops": kept})
        else:
            resolved.append(ch)
    return resolved, conflicts


async def apply_design(
    spec: dict, changes: list[dict], instructions: str, llm: LLMClient
) -> dict:
    final_spec = spec
    applied: list[str] = []
    skipped: list[dict] = []
    notes: list[str] = []
    conflicts: list[dict] = []

    compose_changes = [ch for ch in changes if _compose_ops(ch)]
    atomic_changes = [ch for ch in changes if _atomic_patch_ops(ch)]
    legacy_changes = [ch for ch in changes if not _compose_ops(ch) and not _atomic_patch_ops(ch)]

    if compose_changes:
        by_id = {str(ch.get("id") or ch.get("rule_id") or ""): ch for ch in compose_changes}
        selections = [
            _compose_selection(ch, op)
            for ch in compose_changes
            for op in _compose_ops(ch)
        ]
        final_spec, composed_ids, slot_conflicts, slot_notes = compose_component_slots(spec, selections)
        applied.extend(composed_ids)
        conflicts.extend(_normalize_compose_conflict(item, by_id) for item in slot_conflicts)
        notes.extend(slot_notes)
        composed_set = set(composed_ids)
        loser_ids = {str(item.get("loser_change_id") or "") for item in slot_conflicts}
        for ch in compose_changes:
            cid = str(ch.get("id") or ch.get("rule_id") or "change")
            if cid in composed_set:
                continue
            if cid in loser_ids:
                related = [c for c in conflicts if c.get("loser_change_id") == cid]
                reason = related[0]["reason"] if related else "冲突消解后无可执行路径"
                skipped.append({"id": cid, "reason": reason})
            else:
                skipped.append({"id": cid, "reason": "无可写入当前图的声明路径"})

    if atomic_changes:
        final_spec, atomic_applied, atomic_notes = compose_atomic_component_patches(final_spec, atomic_changes)
        applied.extend(atomic_applied)
        notes.extend(atomic_notes)

    resolved_changes, legacy_conflicts = resolve_change_conflicts(legacy_changes)
    if legacy_conflicts:
        conflicts.extend(legacy_conflicts)
        notes.append(f"检测到 {len(legacy_conflicts)} 处跨机构修改冲突，已按采纳项数量消解")

    for ch in resolved_changes:
        ops = ch.get("ops") or []
        cid = str(ch.get("id") or ch.get("rule_id") or "change")
        if not ops:
            if ch.get("_conflict_dropped"):
                related = [c for c in conflicts if c["loser_change_id"] == cid]
                reason = related[0]["reason"] if related else "冲突消解后无可执行 ops"
                skipped.append({"id": cid, "reason": reason})
            else:
                skipped.append({"id": cid, "reason": "建议类修改（无可执行 ops），需人工或对话微调落实"})
            continue
        try:
            next_spec, report = apply_ops_with_effect(final_spec, ops)
            if report.changed:
                final_spec = next_spec
                applied.append(cid)
            else:
                skipped.append(
                    {
                        "id": cid,
                        "reason": (
                            "ops 重放无写入（无落点或已是目标态）"
                            + (
                                f"；noop={','.join(report.noop_actions)}"
                                if report.noop_actions
                                else ""
                            )
                        ),
                    }
                )
        except Exception as exc:  # noqa: BLE001 — 单条失败不拖垮合成
            skipped.append({"id": cid, "reason": f"ops 重放失败: {exc}"})

    instructions = (instructions or "").strip()
    if instructions:
        if llm.mode == "live":
            system = (
                "你是 Vega-Lite 图表编辑器。按用户指令修改给定 spec。"
                "只输出修改后的完整 Vega-Lite JSON，不要输出解释。保留 data 不变。"
            )
            user = json.dumps({"spec": final_spec, "instructions": instructions}, ensure_ascii=False)
            try:
                refined = await llm.chat_json(system, user)
                if isinstance(refined, dict) and not validate_spec(refined):
                    final_spec = refined
                    notes.append("已按自由文本指令做 LLM 微调")
                else:
                    notes.append("LLM 微调输出不是合法 spec，已忽略")
            except LLMError as exc:
                notes.append(f"LLM 微调失败已忽略：{exc}")
        else:
            notes.append("mock 模式不执行自由文本指令（已完成 ops 确定性重放）")

    return {
        "final_spec": final_spec,
        "applied": applied,
        "skipped": skipped,
        "conflicts": conflicts,
        "notes": notes,
    }
