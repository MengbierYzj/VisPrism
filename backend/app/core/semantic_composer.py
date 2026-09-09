"""Deterministic component-slot composition for Review Board selections.

Advisor candidates may have completely different Vega-Lite topology.  This
module therefore never tries to merge their raw layer indices.  It chooses a
single *plot scaffold* when requested, then projects explicitly selected
semantic components onto it in a fixed order.
"""
from __future__ import annotations

import copy
from typing import Any


SLOT_ORDER = ("structure", "frame", "layout", "title", "typography", "color", "axes", "labels")

# 每条 Review Board 卡片都要带上候选图作为取值证据。整份候选图内联主数据后，
# 一个 persona 的十几条卡片会把同一张数据表重复序列化十几遍，载荷从几十 KB
# 涨到 MB 级并拖垮前端轮询。卡片里改挂占位符，组装时再按源图还原。
PRIMARY_DATA_REF = "__vizguide_primary_data__"


def primary_data(spec: dict) -> dict | None:
    """Return the largest supplied data object: the analytic source table."""
    candidates: list[tuple[int, dict]] = []
    for node in _walk(spec):
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict) and ("values" in data or "url" in data):
            score = len(data.get("values")) if isinstance(data.get("values"), list) else 1
            candidates.append((score, data))
    return copy.deepcopy(max(candidates, key=lambda item: item[0])[1]) if candidates else None


def compact_primary_data(source: dict, candidate: Any) -> Any:
    """Replace the immutable analytic table in a transport copy with a reference."""
    if not isinstance(candidate, dict):
        return candidate
    table = primary_data(source)
    if not table:
        return copy.deepcopy(candidate)
    signature = _signature(table)
    result = copy.deepcopy(candidate)
    for node in _walk(result):
        if isinstance(node, dict) and isinstance(node.get("data"), dict) and _signature(node["data"]) == signature:
            node["data"] = {"$ref": PRIMARY_DATA_REF}
    return result


def restore_primary_data(source: dict, candidate: Any) -> Any:
    """Resolve the transport reference back to the exact source table."""
    if not isinstance(candidate, dict):
        return candidate
    table = primary_data(source)
    if not table:
        return candidate
    result = copy.deepcopy(candidate)
    for node in _walk(result):
        if isinstance(node, dict) and isinstance(node.get("data"), dict) and node["data"].get("$ref") == PRIMARY_DATA_REF:
            node["data"] = copy.deepcopy(table)
    return result


def _signature(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _deep_merge(target: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _encoding_field(node: dict, channel: str) -> str:
    enc = node.get("encoding") if isinstance(node.get("encoding"), dict) else {}
    value = enc.get(channel) if isinstance(enc, dict) else {}
    return str(value.get("field") or "") if isinstance(value, dict) else ""


def _mark_type(node: dict) -> str:
    mark = node.get("mark")
    return str(mark.get("type") or "") if isinstance(mark, dict) else str(mark or "")


def _analytic_marks(spec: dict) -> dict[tuple[str, str, str], dict]:
    """Stable mark roles: data field pair + mark type, never raw layer index."""
    result: dict[tuple[str, str, str], dict] = {}
    for node in _walk(spec):
        if not isinstance(node, dict) or "mark" not in node:
            continue
        x, y = _encoding_field(node, "x"), _encoding_field(node, "y")
        if not (x or y):
            continue
        result.setdefault((x, y, _mark_type(node)), node)
    return result


def _axis_views(spec: dict) -> dict[tuple[str, str], dict]:
    result: dict[tuple[str, str], dict] = {}
    for node in _walk(spec):
        if not isinstance(node, dict):
            continue
        enc = node.get("encoding") if isinstance(node.get("encoding"), dict) else {}
        for channel in ("x", "y"):
            value = enc.get(channel) if isinstance(enc, dict) else None
            if isinstance(value, dict) and (value.get("field") or value.get("axis") or value.get("scale")):
                result.setdefault((channel, str(value.get("field") or "__value__")), value)
    return result


def _text_nodes(spec: dict) -> list[dict]:
    rows: list[dict] = []
    for node in _walk(spec):
        if not isinstance(node, dict) or _mark_type(node) != "text":
            continue
        rows.append(node)
    return rows


def _text_value(node: dict) -> str:
    mark = node.get("mark") if isinstance(node.get("mark"), dict) else {}
    if isinstance(mark.get("text"), str):
        return mark["text"]
    enc = node.get("encoding") if isinstance(node.get("encoding"), dict) else {}
    text = enc.get("text") if isinstance(enc, dict) else {}
    if isinstance(text, dict):
        for key in ("value", "datum"):
            if isinstance(text.get(key), str):
                return text[key]
    return ""


def _text_role(node: dict) -> tuple[str, str, str]:
    """A portable text role without depending on a layer index or wording."""
    enc = node.get("encoding") if isinstance(node.get("encoding"), dict) else {}
    text = enc.get("text") if isinstance(enc, dict) else {}
    text_field = str(text.get("field") or "") if isinstance(text, dict) else ""
    return (_encoding_field(node, "x"), _encoding_field(node, "y"), text_field)


def _title_node(spec: dict) -> dict | None:
    # The largest explicit text mark is the most stable exported-chart title
    # signal.  A top-level title is handled separately.
    texts = _text_nodes(spec)
    if not texts:
        return None
    return max(texts, key=lambda node: float((node.get("mark") or {}).get("fontSize") or 0) if isinstance(node.get("mark"), dict) else 0)


def _copy_title(target: dict, candidate: dict) -> bool:
    if "title" in candidate:
        target["title"] = copy.deepcopy(candidate["title"])
        return True
    source_title, candidate_title = _title_node(target), _title_node(candidate)
    if source_title is None or candidate_title is None:
        return False
    source_mark = source_title.get("mark") if isinstance(source_title.get("mark"), dict) else {}
    candidate_mark = candidate_title.get("mark") if isinstance(candidate_title.get("mark"), dict) else {}
    if source_mark and candidate_mark:
        source_title["mark"] = copy.deepcopy(candidate_mark)
    source_enc = source_title.get("encoding") if isinstance(source_title.get("encoding"), dict) else {}
    candidate_enc = candidate_title.get("encoding") if isinstance(candidate_title.get("encoding"), dict) else {}
    if source_enc and candidate_enc and "text" in candidate_enc:
        source_enc["text"] = copy.deepcopy(candidate_enc["text"])
    return True


def _copy_mark_colours(target: dict, candidate: dict) -> bool:
    changed = False
    target_marks = _analytic_marks(target)
    candidate_marks = _analytic_marks(candidate)
    # First use identical semantic role; then same x/y field pair despite a
    # changed mark type (for example area → line).
    for key, target_node in target_marks.items():
        candidate_node = candidate_marks.get(key)
        if candidate_node is None:
            candidate_node = next((node for (x, y, _kind), node in candidate_marks.items() if (x, y) == key[:2]), None)
        if candidate_node is None:
            continue
        source_mark = target_node.get("mark") if isinstance(target_node.get("mark"), dict) else {}
        candidate_mark = candidate_node.get("mark") if isinstance(candidate_node.get("mark"), dict) else {}
        for prop in ("color", "fill", "stroke", "opacity", "strokeWidth", "filled"):
            if prop in candidate_mark and source_mark.get(prop) != candidate_mark[prop]:
                source_mark[prop] = copy.deepcopy(candidate_mark[prop]); changed = True
        if source_mark:
            target_node["mark"] = source_mark
    if candidate.get("background") is not None and target.get("background") != candidate.get("background"):
        target["background"] = copy.deepcopy(candidate["background"]); changed = True
    return changed


def _copy_axes(target: dict, candidate: dict) -> bool:
    changed = False
    candidate_views, target_views = _axis_views(candidate), _axis_views(target)
    for key, candidate_view in candidate_views.items():
        target_view = target_views.get(key)
        if target_view is None:
            # Same channel is a legitimate fallback when a reconstruction
            # renamed an intermediate field but preserved the axis role.
            target_view = next((view for (channel, _field), view in target_views.items() if channel == key[0]), None)
        if target_view is None:
            continue
        for prop in ("axis", "scale", "title"):
            if prop in candidate_view and target_view.get(prop) != candidate_view[prop]:
                target_view[prop] = copy.deepcopy(candidate_view[prop]); changed = True
    candidate_config = candidate.get("config") if isinstance(candidate.get("config"), dict) else {}
    if isinstance(candidate_config.get("axis"), dict):
        target.setdefault("config", {})
        target["config"].setdefault("axis", {})
        _deep_merge(target["config"]["axis"], candidate_config["axis"]); changed = True
    return changed


def _copy_typography(target: dict, candidate: dict) -> bool:
    changed = False
    candidate_config = candidate.get("config") if isinstance(candidate.get("config"), dict) else {}
    for section in ("title", "axis", "legend", "text"):
        patch = candidate_config.get(section)
        if isinstance(patch, dict):
            target.setdefault("config", {}).setdefault(section, {})
            _deep_merge(target["config"][section], patch); changed = True
    candidate_title = candidate.get("title")
    if isinstance(candidate_title, dict) and isinstance(target.get("title"), dict):
        for prop in ("font", "fontSize", "fontWeight", "color", "subtitleFont", "subtitleFontSize", "subtitleColor"):
            if prop in candidate_title:
                target["title"][prop] = copy.deepcopy(candidate_title[prop]); changed = True
    return changed


def _copy_layout(target: dict, candidate: dict) -> bool:
    changed = False
    for key in ("width", "height", "padding", "autosize", "spacing", "bounds", "align"):
        if key in candidate and target.get(key) != candidate[key]:
            target[key] = copy.deepcopy(candidate[key]); changed = True
    return changed


def _copy_labels(target: dict, candidate: dict) -> bool:
    """Copy title/caption config and annotation layers only when roles match.

    This intentionally avoids deleting arbitrary source text.  Structural
    scaffold selection already carries a candidate's complete annotation set;
    an overlay can safely enrich style and title/caption without guessing which
    unrelated text layer to remove.
    """
    changed = _copy_title(target, candidate)
    target_texts = {_text_role(node): node for node in _text_nodes(target)}
    for candidate_text in _text_nodes(candidate):
        target_text = target_texts.get(_text_role(candidate_text))
        if target_text is None:
            continue
        # Preserve the source's placement/container, but carry the selected
        # persona's annotation wording and typographic treatment into the
        # corresponding semantic text role.
        for key in ("mark", "encoding"):
            if isinstance(candidate_text.get(key), dict) and target_text.get(key) != candidate_text[key]:
                target_text[key] = copy.deepcopy(candidate_text[key]); changed = True
    candidate_config = candidate.get("config") if isinstance(candidate.get("config"), dict) else {}
    for section in ("legend", "title"):
        if isinstance(candidate_config.get(section), dict):
            target.setdefault("config", {}).setdefault(section, {})
            _deep_merge(target["config"][section], candidate_config[section]); changed = True
    return changed


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


def _set_pointer(document: dict, pointer: str, value: Any) -> bool:
    """Set one RFC-6901 pointer, creating only its required containers."""
    if not pointer.startswith("/"):
        return False
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.lstrip("/").split("/")]
    current: Any = document
    for index, key in enumerate(parts):
        last = index == len(parts) - 1
        next_is_list = not last and parts[index + 1].isdigit()
        if isinstance(current, dict):
            if last:
                current[key] = copy.deepcopy(value)
                return True
            expected = list if next_is_list else dict
            if not isinstance(current.get(key), expected):
                current[key] = [] if next_is_list else {}
            current = current[key]
        elif isinstance(current, list) and key.isdigit():
            item_index = int(key)
            while len(current) <= item_index:
                current.append([] if next_is_list else {})
            if last:
                current[item_index] = copy.deepcopy(value)
                return True
            expected = list if next_is_list else dict
            if not isinstance(current[item_index], expected):
                current[item_index] = [] if next_is_list else {}
            current = current[item_index]
        else:
            return False
    return False


def _set_pointer_with_candidate_context(target: dict, candidate: dict, pointer: str, value: Any) -> bool:
    """Write a declared leaf while retaining the smallest required VL context.

    A path such as ``encoding/color/condition/value`` is not executable on its
    own when the source has no ``encoding.color`` object: Vega-Lite also needs
    the condition test.  Copying the smallest missing candidate ancestor keeps
    that syntax context intact, without using the candidate as a whole-chart
    or whole-component replacement.
    """
    if not pointer.startswith("/"):
        return False
    parts = pointer.lstrip("/").split("/")
    for index in range(1, len(parts)):
        prefix = "/" + "/".join(parts[:index])
        candidate_exists, context = _pointer_value(candidate, prefix)
        exists, target_context = _pointer_value(target, prefix)
        # A scalar source mark ("bar") must become the candidate's mark
        # object before a declared nested property such as cornerRadius can be
        # written. The same applies to any required object/list ancestor.
        incompatible_container = isinstance(context, (dict, list)) and not isinstance(target_context, type(context))
        if candidate_exists and (not exists or incompatible_container):
            return _set_pointer(target, prefix, context)
    return _set_pointer(target, pointer, value)


def compose_component_slots(source: dict, selections: list[dict]) -> tuple[dict, list[str], list[dict], list[str]]:
    """Compose precisely the paths a Review Board card claims to modify.

    ``candidate_spec`` is evidence from which a selected path gets its value;
    it is never a whole-chart fallback.  This keeps a colour selection from
    also importing another persona's title, layout, or typography.
    """
    final_spec = copy.deepcopy(source)
    claims: dict[str, dict] = {}
    conflicts: list[dict] = []
    notes: list[str] = []

    for selection in selections:
        paths = [path for path in (selection.get("spec_paths") or []) if isinstance(path, str) and path.startswith("/")]
        if not paths:
            notes.append(f"{selection['id']} 缺少可执行的精确 spec_paths，未组装")
            continue
        candidate = restore_primary_data(source, selection.get("candidate_spec"))
        if not isinstance(candidate, dict):
            notes.append(f"{selection['id']} 缺少候选组件数据，未组装")
            continue
        for path in paths:
            exists, value = _pointer_value(candidate, path)
            if not exists:
                notes.append(f"{selection['id']} 的候选图不存在声明路径 {path}，未组装该路径")
                continue
            previous = claims.get(path)
            if previous is not None:
                conflicts.append({
                    "node": f"spec{path.replace('/', '.')}",
                    "winner_change_id": selection["id"], "loser_change_id": previous["id"],
                    "reason": f"同一精确 spec 路径 {path} 被重复选择；按 Review Board 最后选择项确定为 {selection['id']}。",
                })
            claims[path] = {"id": selection["id"], "value": value, "candidate": candidate}

    applied_paths: dict[str, int] = {}
    for path, claim in claims.items():
        if _set_pointer_with_candidate_context(final_spec, claim["candidate"], path, claim["value"]):
            applied_paths[claim["id"]] = applied_paths.get(claim["id"], 0) + 1
    applied = list(applied_paths)
    for selection in selections:
        if selection["id"] not in applied_paths and not any(conflict.get("loser_change_id") == selection["id"] for conflict in conflicts):
            notes.append(f"{selection['id']} 没有可写入当前图的声明路径")
    return final_spec, applied, conflicts, notes


def _atomic_pointer_parts(pointer: str) -> list[str]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.lstrip("/").split("/")]


def _atomic_remove(document: Any, pointer: str) -> bool:
    """Remove an RFC-6901 location. Missing paths are harmless no-ops."""
    parts = _atomic_pointer_parts(pointer)
    if not parts:
        return False
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    last = parts[-1]
    if isinstance(current, dict):
        return current.pop(last, None) is not None
    if isinstance(current, list) and last.isdigit() and int(last) < len(current):
        current.pop(int(last))
        return True
    return False


def _compact_absent_layer_slots(node: Any) -> None:
    """Do not leave `{}` in a partial layer selection (Vega-Lite rejects it)."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key == "layer" and isinstance(value, list):
                node[key] = [item for item in value if item not in ({}, None)]
                for item in node[key]:
                    _compact_absent_layer_slots(item)
            else:
                _compact_absent_layer_slots(value)
    elif isinstance(node, list):
        for value in node:
            _compact_absent_layer_slots(value)


def compose_atomic_component_patches(source: dict, changes: list[dict]) -> tuple[dict, list[str], list[str]]:
    """Replay experimental atomic manifests without falling back to candidates.

    Each selected card owns exact JSON-Pointer `set`/`remove` patches.  Any
    invisible structural dependencies are embedded with the card as
    `dependency_patches`, so the API may still receive only the cards selected
    by the frontend.  This path is intentionally isolated from the legacy
    `compose_component` contract.
    """
    final_spec = copy.deepcopy(source)
    patch_sets: list[tuple[str, list[dict]]] = []
    notes: list[str] = []
    for change in changes:
        cid = str(change.get("id") or change.get("rule_id") or "change")
        atomic = next((op for op in (change.get("ops") or []) if isinstance(op, dict) and op.get("action") == "apply_component_patch"), None)
        if atomic is None:
            continue
        dependency_patches = atomic.get("dependency_patches") if isinstance(atomic.get("dependency_patches"), list) else []
        for dependency in dependency_patches:
            if isinstance(dependency, dict) and isinstance(dependency.get("patches"), list):
                patch_sets.append((str(dependency.get("id") or "dependency"), dependency["patches"]))
        patches = atomic.get("patches") if isinstance(atomic.get("patches"), list) else []
        if not patches:
            notes.append(f"{cid} 缺少原子 patches，未组装")
            continue
        patch_sets.append((cid, patches))

    # Remove before set: a unit → layer migration must not retain root mark,
    # encoding, or transform properties beside its new layer container.
    for _owner, patches in patch_sets:
        for patch in patches:
            if isinstance(patch, dict) and patch.get("op") == "remove":
                _atomic_remove(final_spec, str(patch.get("path") or ""))
    wrote: dict[str, int] = {}
    for owner, patches in patch_sets:
        for patch in patches:
            if not isinstance(patch, dict) or patch.get("op") != "set":
                continue
            if _set_pointer(final_spec, str(patch.get("path") or ""), patch.get("value")):
                wrote[owner] = wrote.get(owner, 0) + 1
    _compact_absent_layer_slots(final_spec)
    selected_ids = [str(change.get("id") or change.get("rule_id") or "change") for change in changes]
    applied = [cid for cid in selected_ids if wrote.get(cid)]
    for cid in selected_ids:
        if cid not in applied:
            notes.append(f"{cid} 的原子 patches 未写入当前 spec")
    return final_spec, applied, notes
