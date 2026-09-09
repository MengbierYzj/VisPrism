"""LLM-backed cross-advisor composition with deterministic acceptance gates.

Advisor v2 candidates are complete Vega-Lite programs whose view trees may be
unrelated.  Cross-persona composition therefore treats Review Board choices as
design contracts, asks a model to reconstruct one coherent program, and uses
code to verify data preservation, decision traceability and renderability.

The old JSON-pointer projector remains the caller's deterministic fallback; it
is deliberately not used as the primary composition algorithm here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..llm import LLMError
from ..llm_log import LLMRunLog, bind_llm_run_log, bind_llm_stage, reset_llm_run_log, reset_llm_stage
from .semantic_composer import PRIMARY_DATA_REF, compact_primary_data, primary_data, restore_primary_data
from .spec_render import render_vl_to_png_data_url
from .specfacts import validate_spec


def _signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pointer_value(document: Any, pointer: str) -> tuple[bool, Any]:
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


def _path_scope(spec: dict, pointer: str) -> str:
    lower = pointer.lower()
    leaf = lower.rsplit("/", 1)[-1]
    if lower == "/background" or "/encoding/color/" in lower or any(
        token in leaf for token in ("color", "colour", "fill", "stroke", "range")
    ):
        return "color"
    if any(token in leaf for token in ("font", "fontsize", "fontweight", "fontstyle", "lineheight")):
        return "typography"
    if lower.startswith("/title") or lower.startswith("/config/title"):
        return "title"
    if "/axis/" in lower or "/scale/" in lower or lower.startswith("/config/axis/"):
        return "axes"
    if any(token in lower for token in ("/legend/", "/caption", "/annotation", "/source")):
        return "labels"
    if leaf in {"width", "height", "padding", "spacing", "autosize", "bounds", "align", "columns"}:
        return "layout"
    # Text marks are label/annotation decisions unless they are the top-level title.
    parts = pointer.lstrip("/").split("/")
    for index, part in enumerate(parts):
        if part not in {"layer", "vconcat", "hconcat", "concat"} or index + 1 >= len(parts):
            continue
        exists, node = _pointer_value(spec, "/" + "/".join(parts[: index + 2]))
        if exists and isinstance(node, dict):
            mark = node.get("mark")
            mark_type = str(mark.get("type") or "") if isinstance(mark, dict) else str(mark or "")
            if mark_type.lower() == "text":
                return "labels"
    return "structure"


def _candidate_spec(change: dict) -> dict | None:
    for op in change.get("ops") or []:
        if isinstance(op, dict) and isinstance(op.get("candidate_spec"), dict):
            return op["candidate_spec"]
    return None


def _decision_payload(source: dict, changes: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    decisions: list[dict] = []
    candidates: dict[str, dict] = {}
    for change in changes:
        cid = str(change.get("id") or change.get("rule_id") or "change")
        candidate = _candidate_spec(change)
        candidate_id = None
        if isinstance(candidate, dict):
            restored = restore_primary_data(source, candidate)
            compact = compact_primary_data(source, restored)
            digest = hashlib.sha256(_signature(compact).encode("utf-8")).hexdigest()[:12]
            candidate_id = f"candidate-{digest}"
            candidates.setdefault(candidate_id, compact)
        detail = change.get("component_detail") if isinstance(change.get("component_detail"), dict) else {}
        contract = change.get("contract") if isinstance(change.get("contract"), dict) else {}
        evidence_paths = list(contract.get("actual_paths") or detail.get("spec_paths") or [])
        expected_values: list[Any] = []
        if isinstance(candidate, dict):
            restored_candidate = restore_primary_data(source, candidate)
            for path in evidence_paths:
                exists, value = _pointer_value(restored_candidate, path)
                if exists and (not isinstance(value, (dict, list)) or (isinstance(value, list) and len(_signature(value)) <= 500)):
                    if _signature(value) not in {_signature(item) for item in expected_values}:
                        expected_values.append(value)
        knowledge = change.get("knowledge_layers") or ([change.get("knowledge")] if change.get("knowledge") else [])
        decisions.append(
            {
                "change_id": cid,
                "persona_id": cid.split(":", 1)[0] if ":" in cid else cid,
                "scope": str(change.get("scope") or contract.get("scope") or "structure"),
                "label": str(change.get("label") or change.get("rule_id") or cid),
                "decision": str(change.get("reason") or change.get("prompt") or change.get("label") or ""),
                "problem": str(change.get("problem") or ""),
                "before": detail.get("before"),
                "after": detail.get("after"),
                "advisor_paths": evidence_paths,
                "set_paths": list(contract.get("set_paths") or []),
                "removed_paths": list(contract.get("removed_paths") or []),
                "contract_verified": contract.get("verified"),
                "expected_values": expected_values,
                "knowledge": knowledge,
                "candidate_id": candidate_id,
            }
        )
    return decisions, candidates


def _data_contract(source: dict) -> dict:
    data = primary_data(source)
    values = data.get("values") if isinstance(data, dict) and isinstance(data.get("values"), list) else []
    fields: list[str] = []
    for row in values[:20]:
        if isinstance(row, dict):
            for key in row:
                if str(key) not in fields:
                    fields.append(str(key))
    return {
        "primary_data_reference": PRIMARY_DATA_REF,
        "row_count": len(values),
        "fields": fields,
        "sample_rows": values[:3],
        "rule": "The final spec must contain the primary data reference exactly; the server restores the immutable source table after generation.",
    }


def _normalise_response(raw: Any) -> tuple[dict | None, list[dict], list[dict]]:
    if not isinstance(raw, dict):
        return None, [], []
    final_spec = raw.get("final_spec")
    implementation = raw.get("implementation")
    conflicts = raw.get("conflicts")
    if not isinstance(final_spec, dict):
        return None, [], []
    return (
        final_spec,
        [row for row in implementation if isinstance(row, dict)] if isinstance(implementation, list) else [],
        [row for row in conflicts if isinstance(row, dict)] if isinstance(conflicts, list) else [],
    )


def _primary_data_preserved(source: dict, candidate: dict) -> bool:
    expected = primary_data(source)
    if expected is None:
        return True
    expected_sig = _signature(expected)

    def walk(node: Any):
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                yield data
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    return any(_signature(data) == expected_sig for data in walk(candidate))


def _implementation_errors(
    selected: list[dict], final_spec: dict, implementation: list[dict], conflicts: list[dict]
) -> tuple[list[str], list[str]]:
    by_id = {str(row.get("change_id") or ""): row for row in implementation if row.get("change_id")}
    errors: list[str] = []
    realized: list[str] = []
    selected_ids = {str(row.get("change_id") or "") for row in selected}
    conflicted_losers = {
        str(row.get("loser_change_id") or "")
        for row in conflicts
        if str(row.get("winner_change_id") or "") in selected_ids
        and str(row.get("loser_change_id") or "") in selected_ids
        and str(row.get("winner_change_id") or "") != str(row.get("loser_change_id") or "")
    }
    for decision in selected:
        cid = str(decision["change_id"])
        if cid in conflicted_losers:
            continue
        row = by_id.get(cid)
        if row is None:
            errors.append(f"selected decision has no implementation record: {cid}")
            continue
        paths = [p for p in (row.get("realized_paths") or []) if isinstance(p, str) and p.startswith("/")]
        if not paths:
            errors.append(f"selected decision has no realized_paths: {cid}")
            continue
        scope = str(decision.get("scope") or "structure")
        valid = True
        realized_values: list[Any] = []
        for path in paths:
            exists, value = _pointer_value(final_spec, path)
            if not exists:
                errors.append(f"implementation path is absent for {cid}: {path}")
                valid = False
                continue
            realized_values.append(value)
            owner = _path_scope(final_spec, path)
            if scope != "structure" and owner != scope:
                errors.append(f"implementation path belongs to {owner}, not {scope}, for {cid}: {path}")
                valid = False
        # For the portable visual scopes, code paths may move but the selected
        # advisor values (headline, palette token, type size, canvas geometry)
        # must remain observable. This catches an implementation record that
        # merely points at an unrelated property of the right category.
        if scope in {"title", "color", "typography", "layout"}:
            realized_blob = "\n".join(_signature(value) for value in realized_values)
            for expected in decision.get("expected_values") or []:
                if _signature(expected) not in realized_blob:
                    errors.append(f"selected {scope} value was not realized for {cid}: {_signature(expected)[:120]}")
                    valid = False
        if valid:
            realized.append(cid)
    return errors, realized


def _render_is_unavailable(meta: dict) -> bool:
    error = str(meta.get("error") or "")
    return error.startswith(("server_render_disabled", "unresolvable_data_url", "ModuleNotFoundError"))


def _validate_output(
    source: dict, selected: list[dict], final_spec: dict, implementation: list[dict], conflicts: list[dict]
) -> tuple[list[str], list[str], list[str], str | None, dict]:
    errors = list(validate_spec(final_spec))
    warnings: list[str] = []
    if not _primary_data_preserved(source, final_spec):
        errors.append("primary analytic data was not preserved exactly")
    implementation_errors, realized = _implementation_errors(selected, final_spec, implementation, conflicts)
    errors.extend(implementation_errors)
    image, render = render_vl_to_png_data_url(final_spec)
    if not render.get("ok"):
        message = f"Vega-Lite render failed: {render.get('error') or 'unknown error'}"
        if _render_is_unavailable(render):
            warnings.append(message)
        else:
            errors.append(message)
    return errors, warnings, realized, image, render


def _normalise_conflicts(raw: list[dict], by_id: dict[str, dict]) -> list[dict]:
    conflicts: list[dict] = []
    for index, item in enumerate(raw):
        winner_id = str(item.get("winner_change_id") or "")
        loser_id = str(item.get("loser_change_id") or "")
        if not winner_id or not loser_id or winner_id not in by_id or loser_id not in by_id:
            continue
        winner, loser = by_id[winner_id], by_id[loser_id]
        conflicts.append(
            {
                "node": str(item.get("node") or f"semantic-conflict-{index + 1}"),
                "winner_persona_id": str(winner.get("persona_id") or ""),
                "winner_change_id": winner_id,
                "winner_label": str(winner.get("label") or winner_id),
                "loser_persona_id": str(loser.get("persona_id") or ""),
                "loser_change_id": loser_id,
                "loser_label": str(loser.get("label") or loser_id),
                "winner_effect": str(item.get("winner_effect") or "implemented in the reconstructed chart"),
                "loser_effect": str(item.get("loser_effect") or "not implemented"),
                "reason": str(item.get("reason") or "The selected decisions could not both be satisfied."),
            }
        )
    return conflicts


async def _ask(llm: Any, stage: str, system: str, payload: dict) -> Any:
    token = bind_llm_stage(stage)
    try:
        return await llm.chat_json(system, json.dumps(payload, ensure_ascii=False))
    finally:
        reset_llm_stage(token)


async def _ask_vision(llm: Any, system: str, payload: dict, image: str) -> dict | None:
    if not hasattr(llm, "chat_json_vision") or settings.vision_mode == "off":
        return None
    token = bind_llm_stage("composer_visual_acceptance")
    try:
        raw = await llm.chat_json_vision(system, json.dumps(payload, ensure_ascii=False), [image])
        return raw if isinstance(raw, dict) else None
    except Exception:  # visual review is an acceptance signal, not an availability dependency
        return None
    finally:
        reset_llm_stage(token)


_COMPOSE_SYSTEM = """You are the final design composer for a Vega-Lite design exploration system.
The selected advisor decisions come from independently reconstructed charts with incompatible JSON trees.
Reconstruct ONE coherent complete Vega-Lite v5 program. Do not transplant JSON paths mechanically.

Hard requirements:
1. Implement every selected decision unless it is logically incompatible with another selected decision. If incompatible, choose one explicitly in conflicts; never silently omit a selection.
2. A decision's scope is binding: title, axes, color, labels, typography, layout, or structure. Preserve the intended design outcome even when its final JSON path differs from the advisor candidate.
3. Preserve the immutable primary analytic data. Use {"data":{"$ref":"__vizguide_primary_data__"}} wherever that table is needed. Do not copy sample rows into the final spec and do not invent or alter values, fields, dates, labels, sources or claims.
4. You may rebuild layer/concat/transform structure when necessary. Keep all Vega-Lite dependencies together: transforms, fields, scales, conditions, annotations and layout containers.
5. The communication goal is the primary reading objective. Additional instructions are binding unless they contradict data integrity.
6. Output JSON only with this exact envelope:
{"final_spec":{...complete Vega-Lite...},"implementation":[{"change_id":"exact selected id","realized_paths":["/RFC6901/path"],"note":"how it is realized"}],"conflicts":[{"winner_change_id":"id","loser_change_id":"id","node":"semantic area","reason":"why both cannot coexist"}]}
Every non-conflicted selected change_id must appear exactly once in implementation, and every realized path must exist in final_spec."""


_REPAIR_SYSTEM = """Repair a rejected final Vega-Lite composition. Preserve the selected design decisions and immutable data contract. Resolve every listed validation or visual finding. Return the same JSON envelope with final_spec, implementation and conflicts. Do not explain outside JSON."""


_VISION_SYSTEM = """You are the final visual acceptance gate for a composed Vega-Lite chart. Inspect the rendered chart, not just the code. Check clipping, overlap, empty canvas, unreadable text, contradictory hierarchy, incoherent cross-institution styling, and whether the communication goal and selected decisions are visibly realized. Return JSON only: {"verdict":"pass|revise","findings":[{"severity":"high|medium|low","issue":"specific visible problem"}],"summary":"short assessment"}."""


async def compose_with_llm(
    source: dict,
    changes: list[dict],
    instructions: str,
    context: dict,
    deterministic_fallback: dict,
    llm: Any,
) -> dict:
    """Reconstruct and verify a final spec; never throw away the safe fallback."""
    decisions, candidates = _decision_payload(source, changes)
    by_id = {str(item["change_id"]): item for item in decisions}
    payload = {
        "source_spec": compact_primary_data(source, source),
        "deterministic_projection_for_reference_only": compact_primary_data(source, deterministic_fallback),
        "communication_goal": str((context or {}).get("communication_goal") or ""),
        "additional_instructions": instructions,
        "selected_decisions": decisions,
        "advisor_candidates": candidates,
        "data_contract": _data_contract(source),
    }
    log_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    log = LLMRunLog(run_id=log_id, kind="composer")
    log_token = bind_llm_run_log(log)
    notes: list[str] = []
    try:
        unverified = [str(row["change_id"]) for row in decisions if row.get("contract_verified") is False]
        if unverified:
            raise LLMError("Selected advisor changes failed source→candidate contract verification: " + ", ".join(unverified))
        raw = await _ask(llm, "composer_reconstruct", _COMPOSE_SYSTEM, payload)
        final_transport, implementation, raw_conflicts = _normalise_response(raw)
        if final_transport is None:
            raise LLMError("Composer did not return the required final_spec envelope")
        final_spec = restore_primary_data(source, final_transport)
        errors, warnings, realized, image, render = _validate_output(source, decisions, final_spec, implementation, raw_conflicts)

        # One text repair pass covers malformed code, missing decision records and
        # deterministic renderer failures without silently shipping the first draft.
        if errors:
            repair_payload = {
                **payload,
                "rejected_output": {"final_spec": compact_primary_data(source, final_spec), "implementation": implementation, "conflicts": raw_conflicts},
                "validation_errors": errors,
            }
            raw = await _ask(llm, "composer_repair", _REPAIR_SYSTEM, repair_payload)
            final_transport, implementation, raw_conflicts = _normalise_response(raw)
            if final_transport is None:
                raise LLMError("Composer repair did not return final_spec")
            final_spec = restore_primary_data(source, final_transport)
            errors, warnings, realized, image, render = _validate_output(source, decisions, final_spec, implementation, raw_conflicts)
        if errors:
            raise LLMError("; ".join(errors))

        visual_review = None
        if image:
            visual_review = await _ask_vision(
                llm,
                _VISION_SYSTEM,
                {
                    "communication_goal": payload["communication_goal"],
                    "selected_decisions": [{k: row.get(k) for k in ("change_id", "scope", "label", "decision")} for row in decisions],
                },
                image,
            )
            if isinstance(visual_review, dict) and str(visual_review.get("verdict") or "").lower() == "revise":
                repair_payload = {
                    **payload,
                    "rejected_output": {"final_spec": compact_primary_data(source, final_spec), "implementation": implementation, "conflicts": raw_conflicts},
                    "visual_findings": visual_review.get("findings") or [],
                }
                raw = await _ask(llm, "composer_visual_repair", _REPAIR_SYSTEM, repair_payload)
                repaired_transport, repaired_implementation, repaired_conflicts = _normalise_response(raw)
                if repaired_transport is not None:
                    repaired = restore_primary_data(source, repaired_transport)
                    repair_errors, repair_warnings, repair_realized, repair_image, repair_render = _validate_output(
                        source, decisions, repaired, repaired_implementation, repaired_conflicts
                    )
                    if not repair_errors:
                        final_spec, implementation, raw_conflicts = repaired, repaired_implementation, repaired_conflicts
                        warnings, realized, image, render = repair_warnings, repair_realized, repair_image, repair_render
                        visual_review = await _ask_vision(
                            llm,
                            _VISION_SYSTEM,
                            {"communication_goal": payload["communication_goal"], "selected_decisions": decisions},
                            image,
                        ) if image else visual_review
                    else:
                        notes.append("视觉返工未通过程序核验，保留返工前的安全版本")

        notes.extend(warnings)
        notes.append("Composer 已根据采纳的设计契约重构完整 Vega-Lite，并完成数据、决策路径与渲染核验")
        return {
            "ok": True,
            "final_spec": final_spec,
            "realized_ids": realized,
            "conflicts": _normalise_conflicts(raw_conflicts, by_id),
            "notes": notes,
            "composition": {
                "mode": "llm_reconstruction",
                "llm_called": True,
                "decision_count": len(decisions),
                "realized_count": len(realized),
                "implementation": implementation,
                "render": render,
                "visual_review": visual_review,
            },
        }
    except Exception as exc:  # a composition failure must not destroy deterministic availability
        return {
            "ok": False,
            "final_spec": deterministic_fallback,
            "realized_ids": [],
            "conflicts": [],
            "notes": [f"LLM 全量重构未通过验收，已回退确定性组合：{type(exc).__name__}: {exc}"],
            "composition": {
                "mode": "deterministic_fallback",
                "llm_called": True,
                "decision_count": len(decisions),
                "realized_count": 0,
                "fallback_reason": f"{type(exc).__name__}: {exc}",
            },
        }
    finally:
        reset_llm_run_log(log_token)
        log.flush()
