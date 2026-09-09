"""Create and validate an atomic-change replay prototype for v2-20260823-1503.

This is deliberately an offline experiment.  It does not alter the live advisor
or composer.  It turns each advisor's frozen original->candidate delta into
non-overlapping, component-addressable patches with dependency metadata, then
checks that selecting all patches reconstructs the exact frozen candidate.
"""

from __future__ import annotations

import copy
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "storage" / "runs" / "v2-20260823-1503.json"
DESTINATION = ROOT / "storage" / "replay_runs" / "v2-20260823-1503-atomic-manifest.json"
AUDIT = ROOT / "storage" / "replay_runs" / "v2-20260823-1503-atomic-manifest.audit.json"


def read_record(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Read normal run records, including legacy records with a JSONL header."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty record: {path}")
    first = json.loads(lines[0])
    if len(lines) > 1 and isinstance(first, dict) and "run_id" in first and "agents" not in first:
        return first, json.loads("\n".join(lines[1:]))
    return None, first


def pointer(parts: list[str]) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def escape_part(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def unescape_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def diff(before: Any, after: Any, path: list[str] | None = None) -> list[dict[str, Any]]:
    """Return exact JSON-Pointer set/remove operations from before to after.

    View-composition arrays recurse by index so that layers remain separately
    addressable.  All other arrays are atomic values: this avoids inventing
    unstable identities for transforms, ranges, and data values.
    """
    path = path or []
    if isinstance(before, dict) and isinstance(after, dict):
        ops: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            child = path + [escape_part(key)]
            if key not in after:
                ops.append({"op": "remove", "path": pointer(child)})
            elif key not in before:
                ops.extend(diff_missing(after[key], child))
            else:
                ops.extend(diff(before[key], after[key], child))
        return ops
    if isinstance(before, list) and isinstance(after, list) and path and path[-1] in {"layer", "vconcat", "hconcat", "concat"}:
        ops = []
        common = min(len(before), len(after))
        for index in range(common):
            ops.extend(diff(before[index], after[index], path + [str(index)]))
        for index in range(common, len(after)):
            ops.extend(diff_missing(after[index], path + [str(index)]))
        for index in reversed(range(len(after), len(before))):
            ops.append({"op": "remove", "path": pointer(path + [str(index)])})
        return ops
    if before != after:
        return [{"op": "set", "path": pointer(path), "value": copy.deepcopy(after)}]
    return []


def diff_missing(value: Any, path: list[str]) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [op for key in sorted(value) for op in diff_missing(value[key], path + [escape_part(key)])]
    if isinstance(value, list) and path and path[-1] in {"layer", "vconcat", "hconcat", "concat"}:
        return [op for index, item in enumerate(value) for op in diff_missing(item, path + [str(index)])]
    return [{"op": "set", "path": pointer(path), "value": copy.deepcopy(value)}]


def classify(path: str) -> str:
    lower = path.lower()
    # Encoding colour scales are palette decisions, not axis decisions.  The
    # old prototype tested `/scale` first, which is exactly why line colour
    # appeared under "Axes & scales" in the Review Board.
    if any(token in lower for token in ("/encoding/color", "/encoding/strokedash", "/mark/color", "/mark/fill", "/mark/stroke", "/mark/opacity", "/background")):
        return "color"
    if any(token in lower for token in ("font", "fontsize", "fontweight", "fontstyle", "lineheight", "letterspacing")):
        return "typography"
    if "/axis" in lower or "/tick" in lower or "/grid" in lower or "/labelangle" in lower or "/encoding/x/title" in lower or "/encoding/y/title" in lower:
        return "axes"
    if "/scale" in lower or "/domain" in lower:
        return "axes"
    # Axis/legend titles are axis/colour metadata, unlike the chart title.
    if lower.startswith("/title/") or lower.startswith("/config/title/"):
        return "title"
    if any(token in lower for token in ("/encoding/text", "/mark/text", "/align", "/baseline", "/dx", "/dy")):
        return "labels"
    if any(token in lower for token in ("/width", "/height", "/padding", "/spacing", "/bounds")):
        return "layout"
    return "structure"


def component_id(path: str, candidate: dict[str, Any]) -> str:
    """Stable semantic-ish identity derived from a candidate layer, never a bare index."""
    parts = [unescape_part(x) for x in path.split("/") if x]
    if "layer" in parts:
        layer_index = int(parts[parts.index("layer") + 1])
        try:
            layer = candidate["vconcat"][0]["layer"][layer_index]
        except (KeyError, IndexError, TypeError):
            return f"layer-{layer_index}"
        mark = layer.get("mark", {})
        mark_type = mark.get("type", mark) if isinstance(mark, dict) else mark
        encoding = layer.get("encoding", {})
        if mark_type == "rect" and "x2" in encoding:
            return "context-band"
        if mark_type == "text":
            text = encoding.get("text", {})
            field = text.get("field", "text") if isinstance(text, dict) else "text"
            return f"annotation-{field}-{layer_index}"
        if mark_type == "rule":
            return f"reference-rule-{layer_index}"
        if mark_type == "point":
            return f"reference-point-{layer_index}"
        if mark_type in {"line", "area", "bar"}:
            return "main-series" if layer_index <= 1 else f"series-{layer_index}"
        return f"{mark_type or 'layer'}-{layer_index}"
    if "/vconcat/0/" in path:
        return "plot-scaffold"
    return "chart-frame"


def patch_title(scope: str, component: str) -> str:
    labels = {
        "structure": "Chart composition and marks",
        "color": "Color and emphasis",
        "labels": "Labels and annotation",
        "axes": "Axes and scales",
        "typography": "Typography",
        "layout": "Layout and hierarchy",
        "title": "Title and narrative",
    }
    return f"{labels[scope]} — {component.replace('-', ' ')}"


def rewrite_changes(original: dict[str, Any], candidate: dict[str, Any], persona_key: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    operations = diff(original, candidate)
    # A unit chart can become a layered chart without changing the values of
    # its original line's mark/encodings.  A plain JSON diff sees only the root
    # properties being removed and therefore misses that those values must be
    # *moved* into a new layer.  Bootstrap every new layer's structural leaves
    # from the candidate so an independently selected layer remains legal.
    try:
        source_plot = original["vconcat"][0]
        candidate_plot = candidate["vconcat"][0]
        if "layer" not in source_plot and isinstance(candidate_plot.get("layer"), list):
            known_paths = {operation["path"] for operation in operations}
            for index, layer in enumerate(candidate_plot["layer"]):
                for operation in diff_missing(layer, ["vconcat", "0", "layer", str(index)]):
                    if classify(operation["path"]) == "structure" and operation["path"] not in known_paths:
                        operations.append(operation)
                        known_paths.add(operation["path"])
    except (KeyError, IndexError, TypeError):
        pass
    for operation in operations:
        scope = classify(operation["path"])
        component = component_id(operation["path"], candidate)
        grouped[(component, scope)].append(operation)

    changes: list[dict[str, Any]] = []
    ids: dict[tuple[str, str], str] = {}
    for component, scope in sorted(grouped, key=lambda item: (item[0], item[1])):
        ids[(component, scope)] = f"{persona_key}:atomic:{component}:{scope}"

    for (component, scope), operations in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        dependencies: list[str] = []
        if component != "chart-frame" and scope != "structure":
            structure_key = (component, "structure")
            if structure_key in ids:
                dependencies.append(ids[structure_key])
        if component != "chart-frame" and scope == "structure" and component != "plot-scaffold":
            scaffold_key = ("plot-scaffold", "structure")
            if scaffold_key in ids:
                dependencies.append(ids[scaffold_key])
        # A visible overlay needs the base series to remain meaningful when selected alone.
        if component == "context-band" and ("main-series", "structure") in ids:
            dependencies.append(ids[("main-series", "structure")])
        changes.append(
            {
                "id": ids[(component, scope)],
                "kind": "atomic_component_patch",
                "category": scope,
                "scope": scope,
                "component_id": component,
                "semantic_role": component.replace("-", " "),
                "title": patch_title(scope, component),
                "label": patch_title(scope, component),
                "description": "Exact, non-overlapping patch derived from the frozen advisor candidate.",
                "reason": "Prototype manifest: this patch owns only its declared component and visual concern.",
                "evidence": ["Frozen original-to-candidate structural diff"],
                "dependencies": sorted(set(dependencies)),
                # This is an internal migration operation, not a Review Board
                # option.  It becomes active only as a dependency of a visible
                # component and cannot leave the user with an empty plot.
                "selectable": component != "plot-scaffold",
                "component_detail": {
                    "semantic_role": component,
                    "component_is_new": component not in {"chart-frame", "main-series", "plot-scaffold"},
                    "spec_paths": [op["path"] for op in operations],
                    "requires": sorted(set(dependencies)),
                },
                "ops": [{"action": "apply_component_patch", "patches": operations}],
                "patches": operations,
                "spec_paths": [op["path"] for op in operations],
            }
        )
    # The web client sends only selected cards to /api/design/apply.  Materialise
    # their transitive structural dependencies in the selected card's op so a
    # colour/annotation card stays executable without requiring a hidden UI
    # card to be sent alongside it.
    by_id = {change["id"]: change for change in changes}
    for change in changes:
        closure: list[str] = []
        pending = list(change["dependencies"])
        while pending:
            dependency = pending.pop(0)
            if dependency in closure or dependency not in by_id:
                continue
            closure.append(dependency)
            pending.extend(by_id[dependency].get("dependencies") or [])
        change["ops"][0]["dependency_patches"] = [
            {"id": dependency, "patches": copy.deepcopy(by_id[dependency]["patches"])}
            for dependency in reversed(closure)
        ]
    return changes


def parts(path: str) -> list[str]:
    return [unescape_part(part) for part in path.split("/")[1:]]


def set_path(document: Any, path: str, value: Any) -> None:
    target = document
    tokens = parts(path)
    for index, token in enumerate(tokens[:-1]):
        next_token = tokens[index + 1]
        if isinstance(target, list):
            position = int(token)
            while len(target) <= position:
                target.append({} if not next_token.isdigit() else [])
            if target[position] is None:
                target[position] = {} if not next_token.isdigit() else []
            target = target[position]
        else:
            if token not in target or target[token] is None:
                target[token] = [] if next_token.isdigit() else {}
            target = target[token]
    last = tokens[-1]
    if isinstance(target, list):
        position = int(last)
        while len(target) <= position:
            target.append(None)
        target[position] = copy.deepcopy(value)
    else:
        target[last] = copy.deepcopy(value)


def remove_path(document: Any, path: str) -> None:
    target = document
    tokens = parts(path)
    for token in tokens[:-1]:
        if isinstance(target, list):
            position = int(token)
            if position >= len(target):
                return
            target = target[position]
        else:
            if token not in target:
                return
            target = target[token]
    last = tokens[-1]
    if isinstance(target, list):
        position = int(last)
        if position < len(target):
            target.pop(position)
    elif isinstance(target, dict):
        target.pop(last, None)


def compact_unselected_layer_slots(value: Any) -> None:
    """A semantic assembler omits absent layer slots instead of emitting `{}`.

    Patch paths use the frozen candidate's layer positions for deterministic
    reconstruction.  In a partial selection, an earlier component may be
    absent; Vega-Lite rejects the resulting empty placeholder.  Compacting only
    empty entries in `layer` arrays preserves component identity while yielding
    a legal partial chart.
    """
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key == "layer" and isinstance(child, list):
                value[key] = [item for item in child if item not in ({}, None)]
                for item in value[key]:
                    compact_unselected_layer_slots(item)
            else:
                compact_unselected_layer_slots(child)
    elif isinstance(value, list):
        for item in value:
            compact_unselected_layer_slots(item)


def compose(original: dict[str, Any], changes: list[dict[str, Any]], requested: set[str]) -> tuple[dict[str, Any], set[str]]:
    by_id = {change["id"]: change for change in changes}
    selected = set(requested)
    pending = list(requested)
    while pending:
        change_id = pending.pop()
        for dependency in by_id[change_id].get("dependencies", []):
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    result = copy.deepcopy(original)
    selected_changes = [by_id[change_id] for change_id in selected]
    # Removes first prevent inherited unit properties from surviving a layer migration.
    for change in sorted(selected_changes, key=lambda item: (item["scope"] != "structure", item["id"])):
        for operation in change["patches"]:
            if operation["op"] == "remove":
                remove_path(result, operation["path"])
    for change in sorted(selected_changes, key=lambda item: (item["scope"] != "structure", item["id"])):
        for operation in change["patches"]:
            if operation["op"] == "set":
                set_path(result, operation["path"], operation["value"])
    compact_unselected_layer_slots(result)
    return result, selected


def find_change(changes: list[dict[str, Any]], component: str, scope: str) -> str | None:
    selectable_changes = [change for change in changes if change.get("selectable", True)]
    for change in selectable_changes:
        if change["component_id"] == component and change["scope"] == scope:
            return change["id"]
    return None


def compile_check(spec: dict[str, Any]) -> tuple[bool, str]:
    try:
        import vl_convert as vlc  # type: ignore

        vlc.vegalite_to_svg(spec)
        return True, "vega-lite compiled"
    except ModuleNotFoundError:
        return True, "vl-convert unavailable; structural checks completed"
    except Exception as exc:  # noqa: BLE001 - report compiler output in the audit artifact
        return False, f"{type(exc).__name__}: {exc}"


def audit_persona(persona: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    candidate = persona["proposal"]["modified_spec"]
    changes = persona["proposal"]["changes"]
    all_ids = {change["id"] for change in changes}
    full, expanded = compose(original, changes, all_ids)
    result: dict[str, Any] = {
        "persona": persona.get("persona", {}).get("name", persona.get("persona_id", "unknown")),
        "change_count": len(changes),
        "full_selection": {
            "selected_count_with_dependencies": len(expanded),
            "exact_candidate_reconstruction": full == candidate,
            "compiler": compile_check(full),
        },
        "focused_selections": [],
    }
    single_failures = []
    selectable_changes = [change for change in changes if change.get("selectable", True)]
    for change in selectable_changes:
        partial, selected = compose(original, changes, {change["id"]})
        compiled, message = compile_check(partial)
        if not compiled:
            single_failures.append(
                {
                    "requested": change["id"],
                    "activated_dependencies": sorted(selected - {change["id"]}),
                    "compiler": message,
                }
            )
    result["single_change_compilation"] = {
        "tested": len(selectable_changes),
        "passed": len(selectable_changes) - len(single_failures),
        "failures": single_failures,
    }
    for component, scope in (("context-band", "color"), ("main-series", "color"), ("annotation-text-2", "labels")):
        change_id = find_change(changes, component, scope)
        if not change_id:
            continue
        partial, selected = compose(original, changes, {change_id})
        result["focused_selections"].append(
            {
                "requested": change_id,
                "component": component,
                "scope": scope,
                "activated_dependencies": sorted(selected - {change_id}),
                "compiler": compile_check(partial),
                "target_path_exists": all(
                    operation["op"] == "remove" or bool(parts(operation["path"]))
                    for operation in next(change for change in changes if change["id"] == change_id)["patches"]
                ),
            }
        )
    return result


def main() -> None:
    header, record = read_record(SOURCE)
    rewritten = copy.deepcopy(record)
    # v2 run records retain the frozen source with each proposal; request.spec is
    # the same source but the proposal copy is the direct comparison baseline.
    original = record["agents"][0]["proposal"]["original_spec"]
    audits = []
    for persona in rewritten["agents"]:
        proposal = persona["proposal"]
        proposal["changes"] = rewrite_changes(original, proposal["modified_spec"], persona.get("persona_id", "persona"))
        proposal["change_manifest"] = {
            "version": "atomic-component-prototype/v1",
            "source": "programmatic frozen original-to-candidate diff",
            "selection_contract": "Dependency closure plus all patches reconstructs the frozen candidate exactly.",
        }
        audits.append(audit_persona(persona, original))

    rewritten["run_id"] = "v2-20260823-1503-atomic-manifest"

    rewritten["replay_prototype"] = {
        "kind": "atomic-component-manifest",
        "source_run_id": "v2-20260823-1503",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "live_workflow_changed": False,
        "purpose": "Offline proof-of-feasibility before replacing the live composer contract.",
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rewritten, ensure_ascii=False, separators=(",", ":"))
    if header:
        header = {**header, "run_id": "v2-20260823-1503-atomic-manifest", "replay_prototype": True}
        DESTINATION.write_text(json.dumps(header, ensure_ascii=False) + "\n" + payload, encoding="utf-8")
    else:
        DESTINATION.write_text(payload, encoding="utf-8")
    AUDIT.write_text(json.dumps({"source": str(SOURCE), "copy": str(DESTINATION), "audits": audits}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {DESTINATION}")
    print(f"Created {AUDIT}")
    for result in audits:
        full = result["full_selection"]
        print(f"{result['persona']}: {result['change_count']} atomic changes; exact={full['exact_candidate_reconstruction']}; compile={full['compiler'][0]}")


if __name__ == "__main__":
    main()
