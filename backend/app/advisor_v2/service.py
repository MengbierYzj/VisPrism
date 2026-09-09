"""Clean-room four-beat advisor with LLM-owned Vega-Lite reconstruction.

Unlike the legacy operation compiler, this engine never makes an aesthetic choice.
The LLM proposes a complete spec in Beat 3; Beat 4 is a safety gate only.
"""
from __future__ import annotations

import base64
import copy
import io
import inspect
import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from ..config import settings
from ..llm_log import bind_llm_stage, reset_llm_stage
from ..core.actions import apply_ops_with_effect
from ..core.conditions import MATCH, NO_MATCH, eval_when
from ..core.detectors import detect_rule, run_invariants
from ..core.persona import Persona
from ..core.spec_render import render_vl_to_png_data_url
from ..core.specfacts import extract_facts, validate_spec


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _data_signatures(spec: dict) -> set[str]:
    """Return only the primary source dataset, not mutable annotation data.

    A layered chart often has tiny local ``data.values`` tables solely to position a
    note or a rule. Protecting every one of those tables would prevent legitimate
    LLM layout reconstruction. The largest supplied data table (or a data URL) is
    the analytic source whose fields and values must remain available.
    """
    candidates: list[tuple[int, str]] = []
    for node in _walk(spec):
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict) and ("values" in data or "url" in data):
            score = len(data.get("values")) if isinstance(data.get("values"), list) else 1
            candidates.append((score, json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    return {max(candidates, key=lambda item: item[0])[1]} if candidates else set()


_PRIMARY_DATA_REF = "__vizguide_primary_data__"


def _primary_data(spec: dict) -> dict | None:
    """Return the largest analytic data object, excluding annotation tables."""
    candidates: list[tuple[int, dict]] = []
    for node in _walk(spec):
        data = node.get("data") if isinstance(node, dict) else None
        if isinstance(data, dict) and ("values" in data or "url" in data):
            score = len(data.get("values")) if isinstance(data.get("values"), list) else 1
            candidates.append((score, data))
    return copy.deepcopy(max(candidates, key=lambda item: item[0])[1]) if candidates else None


def _compact_for_llm(spec: Any) -> Any:
    """Replace only the immutable primary data table in an LLM-facing spec.

    The model still sees field names, representative rows and facts, but does
    not need to copy tens of thousands of data characters every time it repairs
    layout or code.  Restoring this reference is data conservation, not a
    visual/design decision.
    """
    if not isinstance(spec, dict):
        return spec
    source_data = _primary_data(spec)
    if not source_data:
        return copy.deepcopy(spec)
    source_signature = json.dumps(source_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result = copy.deepcopy(spec)
    for node in _walk(result):
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        data = node["data"]
        if json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) != source_signature:
            continue
        values = source_data.get("values")
        fields = sorted({str(key) for row in values if isinstance(row, dict) for key in row}) if isinstance(values, list) and values else []
        node["data"] = {
            "$ref": _PRIMARY_DATA_REF,
            "fields": fields,
            "row_count": len(values) if isinstance(values, list) else None,
            "sample": values[:3] if isinstance(values, list) else None,
        }
    return result


def _restore_primary_data(source: dict, candidate: Any) -> Any:
    """Resolve the compact LLM data reference back to the exact source data."""
    if not isinstance(candidate, dict):
        return candidate
    primary = _primary_data(source)
    if not primary:
        return candidate
    result = copy.deepcopy(candidate)
    for node in _walk(result):
        if isinstance(node, dict) and isinstance(node.get("data"), dict) and node["data"].get("$ref") == _PRIMARY_DATA_REF:
            node["data"] = copy.deepcopy(primary)
    return result


def _as_json_object(answer: Any, list_key: str | None = None) -> Any:
    """Recover the requested object from the two array shapes models emit.

    Rejecting these wastes a whole beat, and on a repair stage it discards the
    persona's work entirely, so the two unambiguous cases are recovered:
    a lone `[{...}]` wrapper, and a bare list of items for a stage whose reply
    is dominated by one list field (e.g. the critic returning only `findings`).
    Anything else passes through and is still rejected upstream.
    """
    if isinstance(answer, list):
        objects = [item for item in answer if isinstance(item, dict)]
        if len(objects) == 1 and not list_key:
            return objects[0]
        if objects and list_key and len(objects) == len(answer):
            return {list_key: objects}
        if len(objects) == 1:
            return objects[0]
    return answer


_PROTOCOL_KEYS = ("primary_data_reference", "protected_static_texts", "source_spec")
_SECONDARY_CHANNELS = {"x2": "x", "y2": "y", "latitude2": "latitude", "longitude2": "longitude"}


def _infer_field_type(source: dict, field: str) -> str:
    """Infer a Vega-Lite type for a field from the source table's own values."""
    primary = _primary_data(source) or {}
    values = primary.get("values")
    if isinstance(values, list):
        for row in values:
            if isinstance(row, dict) and row.get(field) is not None:
                sample = row[field]
                if isinstance(sample, bool):
                    return "nominal"
                if isinstance(sample, (int, float)):
                    return "quantitative"
                return "nominal"
    return "quantitative"


_POSITIONAL_CHANNELS = {"x": "x", "x2": "x", "y": "y", "y2": "y"}


def _channel_domains(source: dict, spec: dict) -> dict[str, tuple[float, float]]:
    """Data range of each positional channel, from declared scales or the data."""
    domains: dict[str, tuple[float, float]] = {}
    table = _primary_data(source) or _primary_data(spec) or {}
    rows = table.get("values") if isinstance(table.get("values"), list) else []
    for node in _walk(spec):
        if not isinstance(node, dict):
            continue
        for channel in ("x", "y"):
            definition = node.get(channel)
            if not isinstance(definition, dict) or not isinstance(definition.get("field"), str):
                continue
            scale = definition.get("scale")
            declared = scale.get("domain") if isinstance(scale, dict) else None
            if isinstance(declared, list) and len(declared) == 2 and all(isinstance(v, (int, float)) for v in declared):
                low, high = float(declared[0]), float(declared[1])
            else:
                field = definition["field"]
                values = [row[field] for row in rows if isinstance(row, dict) and isinstance(row.get(field), (int, float))]
                if not values:
                    continue
                low, high = float(min(values)), float(max(values))
            existing = domains.get(channel)
            domains[channel] = (min(low, existing[0]), max(high, existing[1])) if existing else (low, high)
    return domains


def _repair_datum_value_confusion(source: dict, candidate: dict) -> tuple[dict, list[str]]:
    """Rewrite positional ``value`` constants that are really data values.

    In Vega-Lite ``{"value": 2016}`` is 2016 *pixels* from the plot edge, while
    ``{"datum": 2016}`` is the year 2016 on the scale. An annotation written the
    first way is pushed far outside the plot and drags the whole canvas with it.
    Two signals make the confusion unambiguous: the constant carries a ``type``
    (which ``value`` has no use for), or it falls inside that channel's own data
    domain. The caller keeps the rewrite only if the rendered canvas actually
    comes back toward its declared size.
    """
    domains = _channel_domains(source, candidate)
    result = copy.deepcopy(candidate)
    converted: list[str] = []
    for node in _walk(result):
        if not isinstance(node, dict):
            continue
        for channel, base in _POSITIONAL_CHANNELS.items():
            definition = node.get(channel)
            if not isinstance(definition, dict) or not isinstance(definition.get("value"), (int, float)):
                continue
            constant = float(definition["value"])
            domain = domains.get(base)
            typed = isinstance(definition.get("type"), str)
            if not typed and not (domain and domain[0] <= constant <= domain[1]):
                continue
            definition["datum"] = definition.pop("value")
            definition.pop("type", None)
            converted.append(f"{channel}={constant:g}")
    return result, converted


# 标题、坐标轴与留白本来就会让画布比绘图区大一些，1.6 倍以上才算失控。
_CANVAS_OVERFLOW_LIMIT = 1.6


def _canvas_overflow_ratio(spec: dict, render: dict) -> float:
    """How far the rendered canvas exceeds the plot size the spec asked for."""
    ratio = 0.0
    for dimension, declared in (("width", _view_width(spec, 0)), ("height", spec.get("height"))):
        rendered = render.get(dimension)
        if isinstance(rendered, (int, float)) and isinstance(declared, (int, float)) and declared > 0:
            ratio = max(ratio, float(rendered) / float(declared))
    return ratio


def _canvas_overflows(spec: dict, render: dict) -> bool:
    return _canvas_overflow_ratio(spec, render) > _CANVAS_OVERFLOW_LIMIT


_INSIDE_LEGEND_ORIENTS = {"top-left", "top-right", "bottom-left", "bottom-right"}
# 机构规范要求署名，而原图往往没有来源可抄，模型就会留下「[Add source]」这类占位
# 符并当作已满足规则交付。
_PLACEHOLDER_TEXT = re.compile(r"\[[^\]]*\b(?:add|insert|your|tbd|todo|source name|placeholder)\b[^\]]*\]|\bTBD\b|\bTODO\b|\bXXX\b|<[^>]{2,40}>", re.IGNORECASE)


def _new_layout_risks(source: dict, candidate: dict) -> list[dict[str, str]]:
    """Flag the candidate's layout hazards, marking which the original already had.

    An inherited pattern is the institution's existing context rather than
    something this persona introduced, and the source chart's own dual axis
    renders correctly — so the two are reported separately instead of
    suppressing either one.
    """
    inherited = {risk["kind"] for risk in _layout_risks(source)}
    return [{**risk, "inherited_from_original": "yes" if risk["kind"] in inherited else "no"} for risk in _layout_risks(candidate)]


def _layout_risks(spec: dict) -> list[dict[str, str]]:
    """Report structural layout hazards for the visual gate to judge on pixels.

    The program deliberately stops at detection. Whether a legend inside the
    plot actually covers data, or whether a second axis is worth its cost, is a
    judgment about the rendered image and about this institution's conventions
    — so it stays with the persona's critic. What the program can do reliably
    is say *where to look*, which a vision model reading a whole chart at once
    routinely misses.
    """
    risks: list[dict[str, str]] = []
    for text in _static_texts(spec):
        placeholder = _PLACEHOLDER_TEXT.search(text)
        if placeholder:
            risks.append({
                "kind": "unfilled_placeholder_text",
                "where": f"static text: {text[:90]}",
                "check": (
                    f"`{placeholder.group(0)}` reads as an authoring placeholder rather than real copy. "
                    "If the fact is not available in the supplied chart, drop the line instead of shipping the placeholder."
                ),
            })
    for node in _walk(spec):
        if not isinstance(node, dict):
            continue

        for channel, definition in node.items():
            if not isinstance(definition, dict):
                continue
            legend = definition.get("legend")
            if isinstance(legend, dict) and str(legend.get("orient", "")) in _INSIDE_LEGEND_ORIENTS:
                risks.append({
                    "kind": "legend_inside_plot",
                    "where": f"encoding.{channel}.legend.orient = {legend['orient']}",
                    "check": "The legend sits inside the plotting area. Confirm on the image that it covers no marks; move it outside if it does.",
                })

        layers = node.get("layer")
        if not isinstance(layers, list):
            continue
        resolve = node.get("resolve") if isinstance(node.get("resolve"), dict) else {}
        for channel in ("x", "y"):
            axes = []
            for layer in layers:
                definition = (layer.get("encoding") or {}).get(channel) if isinstance(layer, dict) else None
                if isinstance(definition, dict) and isinstance(definition.get("axis"), dict):
                    axes.append((definition.get("field"), definition["axis"].get("title")))
            if len(axes) < 2:
                continue
            scale_mode = str((resolve.get("scale") or {}).get(channel, ""))
            axis_mode = str((resolve.get("axis") or {}).get(channel, ""))
            titles = " / ".join(str(title) for _field, title in axes if title)
            if scale_mode == "independent":
                risks.append({
                    "kind": "dual_axis_independent_scales",
                    "where": f"resolve.scale.{channel} = independent, axis titles: {titles}",
                    "check": "Two layers draw a "
                    f"{channel} axis on independent scales, so their marks are not on a common footing and cannot be read against each other. Verify this is intended and readable.",
                })
            elif axis_mode == "independent":
                risks.append({
                    "kind": "dual_axis_shared_scale",
                    "where": f"resolve.axis.{channel} = independent with a shared scale, axis titles: {titles}",
                    "check": "Two axes share one scale, so the second axis prints the first axis's numbers under its own title. Check the tick labels actually match its stated unit.",
                })
    return risks


def _strip_interactive_params(spec: dict) -> tuple[dict, list[str]]:
    """Remove selection declarations *and every reference to them*.

    Dropping only the declaration turns a duplicate-signal failure into an
    unrecognised-signal failure. A filter bound to a removed selection is
    dropped with it, which leaves the view showing the same rows it shows
    before anyone brushes — the chart's own initial state.
    """
    result = copy.deepcopy(spec)
    dropped: list[str] = []
    for node in _walk(result):
        if not isinstance(node, dict):
            continue
        for key in ("params", "selection"):
            value = node.get(key)
            if isinstance(value, list) and value:
                dropped.extend(str(item.get("name")) for item in value if isinstance(item, dict) and item.get("name"))
                node.pop(key, None)
            elif isinstance(value, dict) and value:
                dropped.extend(str(name) for name in value)
                node.pop(key, None)
    if not dropped:
        return result, dropped

    names = set(dropped)

    def _references_dropped(item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        for key in ("param", "selection"):
            target = item.get(key)
            if isinstance(target, str) and target in names:
                return True
        condition = item.get("filter") if isinstance(item.get("filter"), dict) else None
        return _references_dropped(condition) if condition else False

    for node in _walk(result):
        if not isinstance(node, dict):
            continue
        transforms = node.get("transform")
        if isinstance(transforms, list):
            kept = [item for item in transforms if not _references_dropped(item)]
            if kept:
                node["transform"] = kept
            else:
                node.pop("transform", None)
        for channel, definition in list(node.items()):
            if not isinstance(definition, dict):
                continue
            condition = definition.get("condition")
            if isinstance(condition, dict) and _references_dropped(condition):
                definition.pop("condition", None)
            elif isinstance(condition, list):
                remaining = [item for item in condition if not _references_dropped(item)]
                if remaining:
                    definition["condition"] = remaining
                else:
                    definition.pop("condition", None)
    return result, dropped


def _view_width(node: dict, fallback: int) -> int:
    """Effective plot width of a view, looking into its composition children."""
    width = node.get("width")
    if isinstance(width, (int, float)) and width > 0:
        return int(width)
    widths: list[int] = []
    for key in ("layer", "vconcat", "hconcat", "concat"):
        children = node.get(key)
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    child_width = child.get("width")
                    if isinstance(child_width, (int, float)) and child_width > 0:
                        widths.append(int(child_width))
    return max(widths) if widths else fallback


def _wrap_overflowing_titles(source: dict, candidate: dict) -> list[str]:
    """Wrap a title/subtitle that is wider than its own plot, in place.

    Vega-Lite never wraps a title string, so one long editorial sentence
    stretches the whole canvas far past the plot and leaves the chart stranded
    in a corner — the "abnormal empty canvas" the visual gate rejects. Breaking
    the same words across lines preserves the text exactly and changes no
    editorial wording, colour or mark.
    """
    repairs: list[str] = []
    source_width = source.get("width")
    fallback = int(source_width) if isinstance(source_width, (int, float)) and source_width > 0 else 640
    root_title_config = ((candidate.get("config") or {}).get("title") or {}) if isinstance(candidate.get("config"), dict) else {}

    for node in _walk(candidate):
        if not isinstance(node, dict):
            continue
        title = node.get("title")
        if not isinstance(title, dict):
            continue
        width = _view_width(node, fallback)
        # 字号常写在 config.title 而非 title 自身，漏读会把换行预算算大一倍。
        node_title_config = ((node.get("config") or {}).get("title") or {}) if isinstance(node.get("config"), dict) else {}
        for key, size_key, default_size in (("text", "fontSize", 16), ("subtitle", "subtitleFontSize", 11)):
            value = title.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            size = title.get(size_key) or node_title_config.get(size_key) or root_title_config.get(size_key)
            font_size = float(size) if isinstance(size, (int, float)) and size > 0 else default_size
            # 半个字号是常见无衬线/衬线字体的平均字宽，足够判断「明显溢出」。
            budget = max(24, int(width / (font_size * 0.5)))
            if len(value) <= budget * 1.15:
                continue
            lines = textwrap.wrap(value, budget)
            if len(lines) > 1:
                title[key] = lines
                repairs.append(f"wrapped overlong title `{key}` into {len(lines)} lines to fit the {width}px plot")
    return repairs


def _repair_structural_defects(source: dict, candidate: dict) -> tuple[dict, list[str]]:
    """Deterministic Vega-Lite correctness repairs that carry no design choice.

    These two defect classes stop the chart from compiling at all, which costs a
    whole LLM repair pass and often ends with the persona's work discarded:

    - protocol keys the model copied out of its own input envelope, which are
      not Vega-Lite properties;
    - a secondary channel (``x2``/``y2``) bound to a field but missing ``type``
      while its primary channel carries a constant ``value`` and therefore has
      no type to inherit.

    Neither repair alters marks, encodings, colour, text or layout, so the
    persona keeps authorship of every visible decision.
    """
    result = copy.deepcopy(candidate)
    repairs: list[str] = []

    for key in _PROTOCOL_KEYS:
        if key in result:
            result.pop(key, None)
            repairs.append(f"removed stray protocol key `{key}`")

    for node in _walk(result):
        if not isinstance(node, dict):
            continue
        encoding = node.get("encoding")
        if not isinstance(encoding, dict):
            continue
        for channel, primary_channel in _SECONDARY_CHANNELS.items():
            definition = encoding.get(channel)
            if not isinstance(definition, dict) or "type" in definition:
                continue
            field = definition.get("field")
            if not isinstance(field, str) or not field:
                continue
            primary = encoding.get(primary_channel)
            inherited = primary.get("type") if isinstance(primary, dict) else None
            definition["type"] = inherited if isinstance(inherited, str) and inherited else _infer_field_type(source, field)
            repairs.append(f"typed `{channel}` on field `{field}` as {definition['type']}")

    repairs.extend(_wrap_overflowing_titles(source, result))
    return result, repairs


def _static_texts(spec: dict) -> set[str]:
    """Static editorial text; field-bound labels are protected by source data."""
    found: set[str] = set()
    for node in _walk(spec):
        if not isinstance(node, dict):
            continue
        title = node.get("title")
        if isinstance(title, str) and title.strip():
            found.add(title.strip())
        elif isinstance(title, dict):
            for key in ("text", "subtitle"):
                value = title.get(key)
                if isinstance(value, str) and value.strip():
                    found.add(value.strip())
                elif isinstance(value, list):
                    found.update(str(v).strip() for v in value if isinstance(v, str) and v.strip())
        mark = node.get("mark")
        if isinstance(mark, dict) and str(mark.get("type", "")).lower() == "text":
            value = mark.get("text")
            if isinstance(value, str) and value.strip():
                found.add(value.strip())
        # Both forms are legal Vega-Lite. A reconstruction may use encoding.text
        # value/datum instead of mark.text, especially inside layered charts.
        encoding = node.get("encoding")
        text_encoding = encoding.get("text") if isinstance(encoding, dict) else None
        if isinstance(text_encoding, dict):
            for key in ("value", "datum"):
                value = text_encoding.get(key)
                if isinstance(value, str) and value.strip():
                    found.add(value.strip())
        mark_type = str(mark.get("type", "")).lower() if isinstance(mark, dict) else str(mark or "").lower()
        data = node.get("data")
        if mark_type == "text" and isinstance(data, dict) and isinstance(data.get("values"), list):
            for row in data["values"]:
                if isinstance(row, dict):
                    found.update(value.strip() for value in row.values() if isinstance(value, str) and value.strip())
    # Numeric tick labels are often exported as text layers by chart tools. They
    # are generated scale chrome, not editorial copy: a valid reconstruction may
    # replace them with a proper Vega-Lite axis and different tick values.
    return {text for text in found if re.search(r"[A-Za-z]{2,}|[\u4e00-\u9fff]", text)}


def _normalise_text_changes(value: Any) -> list[dict[str, str]]:
    """Accept one model-produced mapping as well as the requested JSON array."""
    raw_items = [value] if isinstance(value, dict) else value if isinstance(value, list) else []
    return [
        {"before": item["before"].strip(), "after": item["after"].strip(), "reason": str(item.get("reason") or "").strip()}
        for item in raw_items
        if isinstance(item, dict)
        and isinstance(item.get("before"), str) and item["before"].strip()
        and isinstance(item.get("after"), str) and item["after"].strip()
    ]


def _merge_text_changes(*values: Any) -> list[dict[str, str]]:
    """Later repairs override the same source text but never erase valid maps."""
    merged: dict[str, dict[str, str]] = {}
    for value in values:
        for item in _normalise_text_changes(value):
            merged[item["before"]] = item
    return list(merged.values())


_COMMITMENT_COMPONENTS = frozenset({"title", "color", "axes", "labels", "typography", "layout", "structure"})


def _pointer_value(document: Any, pointer: str) -> tuple[bool, Any]:
    """Read an RFC-6901-style pointer without treating a missing path as None."""
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


def _is_preservation_claim(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:preserv\w*|confirm\w*|unchanged|same|still|retain\w*)\b", lowered)
        or any(word in text for word in ("保留", "保持", "确认", "不变"))
    )


def _is_text_layer_path(candidate: dict, pointer: str) -> bool:
    """Whether a pointer is inside a candidate text-mark layer."""
    parts = pointer.lstrip("/").split("/")
    for index, part in enumerate(parts):
        if part not in {"layer", "hconcat", "vconcat", "concat"} or index + 1 >= len(parts):
            continue
        prefix = "/" + "/".join(parts[:index + 2])
        exists, node = _pointer_value(candidate, prefix)
        if not exists or not isinstance(node, dict):
            continue
        mark = node.get("mark")
        mark_type = str(mark.get("type") or "") if isinstance(mark, dict) else str(mark or "")
        if mark_type.lower() == "text":
            return True
    return False


def _path_owner(candidate: dict, pointer: str) -> str:
    """Assign exactly one visual-property leaf to one advisor component.

    The order deliberately makes colour and typography global ownership
    classes. A label can move or change words, but it cannot also claim its
    font/colour; those belong to their respective commitments.
    """
    lower = pointer.lower()
    leaf = lower.rsplit("/", 1)[-1]
    # Inspect the full path, not just its final token.  For example the
    # payload leaf of ``encoding.color.datum`` is named ``datum``, but it is
    # still a colour assignment rather than a label property.
    if lower == "/background" or "/encoding/color/" in lower or "/encoding/colour/" in lower or any(token in leaf for token in ("color", "colour", "fill", "stroke", "range")):
        return "color"
    if any(token in leaf for token in ("font", "fontsize", "fontweight", "fontstyle", "lineheight")):
        return "typography"
    if lower.startswith("/title") or lower.startswith("/config/title"):
        return "title"
    if "/axis/" in lower or "/scale/" in lower or lower.startswith("/config/axis/"):
        return "axes"
    if leaf in {"width", "height", "padding", "spacing", "autosize", "bounds", "align", "columns"}:
        return "layout"
    if _is_text_layer_path(candidate, pointer) or "/legend/" in lower or lower.startswith("/config/legend/"):
        return "labels"
    return "structure"


def _is_commitment_atom(candidate: dict, pointer: str, value: Any) -> bool:
    """Permit indivisible semantic values in addition to scalar JSON leaves.

    Vega-Lite represents a palette, categorical domain and explicit tick list
    as arrays.  Those arrays are one intentional design value, not a vague
    container, so a colour/axis commitment must be allowed to cite them.
    """
    if not isinstance(value, (dict, list)):
        return True
    lower = pointer.lower()
    if isinstance(value, list) and lower.endswith(("/range", "/domain", "/values")):
        return True
    return False


def _pointer_part(key: str) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _manifest_diff_inventory(source: Any, candidate: Any, pointer: str = "") -> list[dict[str, Any]]:
    """Describe real source→candidate design differences for the manifest LLM.

    This is evidence, not a design policy.  It gives the advisor exact paths
    it must account for, so a reconstructed chart cannot be documented as one
    vague ``structure`` change merely because its JSON tree was reorganised.
    Primary analytic rows are intentionally omitted: their conservation is a
    safety invariant, not an editorial modification the user selected.
    """
    rows: list[dict[str, Any]] = []

    def compact(value: Any) -> Any:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return value if len(encoded) <= 240 else f"<{type(value).__name__} {len(encoded)} chars>"

    def add(path: str, before: Any, after: Any) -> None:
        # Do not ask the model to narrate preserved source rows or the compact
        # primary-data reference as a visual decision.
        if "/data/values" in path or path.startswith("/primary_data_reference"):
            return
        if len(rows) >= 180:
            return
        rows.append({
            "path": path or "/",
            "expected_component": _path_owner(candidate if isinstance(candidate, dict) else {}, path or "/"),
            "before": compact(before),
            "after": compact(after),
        })

    def walk(before: Any, after: Any, path: str) -> None:
        if before == after:
            return
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after), key=str):
                child = f"{path}/{_pointer_part(key)}"
                if key not in before:
                    walk(None, after[key], child)
                elif key not in after:
                    # A removed path cannot be cited in candidate_spec.  Its
                    # nearest surviving parent will still be represented by
                    # another changed candidate leaf when one exists.
                    continue
                else:
                    walk(before[key], after[key], child)
            return
        if isinstance(before, list) and isinstance(after, list):
            # Palette/domain/tick arrays are one legal manifest atom.  For
            # composition arrays, recurse so each real candidate leaf remains
            # available to the advisor instead of treating a whole layer as
            # an opaque structure blob.
            lower = path.lower()
            if lower.endswith(("/range", "/domain", "/values")):
                add(path, before, after)
                return
            for index, value in enumerate(after):
                walk(before[index] if index < len(before) else None, value, f"{path}/{index}")
            return
        add(path, before, after)

    walk(source, candidate, pointer)
    return rows


def _missing_manifest_components(inventory: list[dict[str, Any]], commitments: list[dict]) -> list[str]:
    """Return component classes evidenced by the final artifact but undocumented."""
    expected = {str(row.get("expected_component")) for row in inventory if row.get("expected_component") in _COMMITMENT_COMPONENTS}
    present = {str(item.get("component") or "").lower() for item in commitments if isinstance(item, dict)}
    return sorted(expected - present)


def _check_commitments(source: dict, candidate: dict, commitments: Any) -> tuple[list[dict], list[dict]]:
    """Keep only a truthful, executable advisor-facing change manifest.

    This is documentation integrity, not a design compiler: it does not add or
    rewrite a decision.  It verifies that every sentence claims a visible
    source→candidate difference and names at least one real candidate path.
    """
    valid: list[dict] = []
    rejected: list[dict] = []
    claimed_paths: dict[str, str] = {}
    for index, item in enumerate(commitments if isinstance(commitments, list) else []):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "commitment is not an object"})
            continue
        component = str(item.get("component") or "").strip().lower()
        claim = str(item.get("claim") or "").strip()
        before, after = str(item.get("before") or "").strip(), str(item.get("after") or "").strip()
        paths = [path for path in (item.get("spec_paths") or []) if isinstance(path, str) and path.startswith("/")]
        reasons: list[str] = []
        if component not in _COMMITMENT_COMPONENTS:
            reasons.append("invalid component")
        if not claim or not before or not after:
            reasons.append("claim/before/after must all be non-empty")
        if not paths:
            reasons.append("no candidate_spec paths")
        if _is_preservation_claim(f"{claim} {after}"):
            reasons.append("preservation/confirmation is not an applied visible change")
        changed_path = False
        for path in paths:
            exists, value = _pointer_value(candidate, path)
            if not exists:
                reasons.append(f"candidate path missing: {path}")
                continue
            if not _is_commitment_atom(candidate, path, value):
                reasons.append(f"path must identify one leaf property or atomic palette/domain/tick list: {path}")
                continue
            owner = _path_owner(candidate, path)
            if owner != component:
                reasons.append(f"path belongs to {owner}, not {component}: {path}")
                continue
            if path in claimed_paths:
                reasons.append(f"path already claimed by {claimed_paths[path]}: {path}")
                continue
            source_exists, source_value = _pointer_value(source, path)
            if not source_exists or source_value != value:
                changed_path = True
        if paths and not changed_path:
            reasons.append("all cited paths are unchanged from source")
        if reasons:
            rejected.append({"id": str(item.get("id") or f"commitment-{index + 1}"), "reason": "; ".join(dict.fromkeys(reasons))})
            continue
        valid.append({**item, "component": component, "spec_paths": paths})
        for path in paths:
            claimed_paths[path] = str(item.get("id") or f"commitment-{index + 1}")
    return valid, rejected


def _render_integrity_error(image: str | None) -> str | None:
    """Recognise a renderer-produced blank canvas as a render failure.

    Vega can sometimes report a JavaScript runtime error to stderr while
    ``vl-convert`` still returns a syntactically valid, single-colour PNG.  A
    PNG existing is therefore not sufficient evidence that a Vega-Lite spec
    actually executed.  This is deliberately an execution-integrity check,
    not a judgement about a chart's design or layout.
    """
    if not isinstance(image, str) or not image.startswith("data:image/png;base64,"):
        return None
    try:
        from PIL import Image

        encoded = image.split(",", 1)[1]
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as png:
            # ``getcolors(2)`` returns a list only for one or two exact pixel
            # colours; returning a single colour means no chart primitive was
            # painted at all.  Two or more colours are left to the LLM visual
            # review—this check must not impose an aesthetic policy.
            colors = png.convert("RGBA").getcolors(maxcolors=2)
        if colors is not None and len(colors) == 1:
            return "Vega-Lite rendered a uniform blank canvas (possible runtime transform/expression error)"
    except Exception:  # optional image inspection must never mask compilation
        return None
    return None


def _review_score(review: dict[str, Any]) -> int:
    """Use the visual critic's own judgement to rank safe generated specs.

    This deliberately makes no visual decision from Vega-Lite properties.  The
    score is supplied by the persona's pixel review; the fallback only gives a
    deterministic ordering when an older/failing model response omits it.
    """
    raw = review.get("delivery_score") if isinstance(review, dict) else None
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    assessment = review.get("intent_assessment") if isinstance(review, dict) else {}
    comparison = str(assessment.get("comparison", "")).lower() if isinstance(assessment, dict) else ""
    base = {"better": 60, "unchanged": 35, "worse": 10}.get(comparison, 0)
    high = sum(1 for item in (review.get("findings") or []) if isinstance(item, dict) and str(item.get("severity", "")).lower() == "high")
    return max(0, base - high * 10)


def _safe_candidate(source: dict, candidate: Any, text_changes: Any) -> tuple[dict, dict]:
    """Validate only integrity and renderability; never edit the LLM design."""
    report: dict[str, Any] = {"accepted": False, "errors": [], "render": {}}
    candidate = _restore_primary_data(source, candidate)
    if not isinstance(candidate, dict):
        report["errors"].append("candidate_spec is not a JSON object")
        return source, report
    # 编译前的确定性纠错：只修「图根本编译不出来」的代码缺陷，不触碰任何设计选择。
    candidate, structural_repairs = _repair_structural_defects(source, candidate)
    if structural_repairs:
        report["structural_repairs"] = structural_repairs
    report["errors"].extend(validate_spec(candidate))
    source_data = _data_signatures(source)
    candidate_data = _data_signatures(candidate)
    if not source_data.issubset(candidate_data):
        report["errors"].append("candidate does not preserve every original data source")

    declared = {
        str(item.get("before")): str(item.get("after"))
        for item in _normalise_text_changes(text_changes)
        if isinstance(item, dict) and isinstance(item.get("before"), str) and isinstance(item.get("after"), str)
    }
    candidate_text = _static_texts(candidate)
    for text in _static_texts(source):
        if text in candidate_text:
            continue
        replacement = declared.get(text)
        if not replacement or replacement not in candidate_text:
            report["errors"].append(f"required text missing or undeclared rewrite: {text[:90]}")

    # vl-convert performs real Vega-Lite compilation. It is a validator, not a
    # layout policy: a failure rejects the candidate unchanged.
    image, render = render_vl_to_png_data_url(candidate)
    # 编译驱动的最小修复：只有当图确实编译不出来时才试着去掉交互选择，且仅在去掉
    # 后能编译成功时才保留这一改动。一张本来正常的图不会被程序动到，而一个让整张
    # 图报废的选择器（如组合视图上的顶层 interval 会展开成重名信号）也不该让
    # persona 的全部工作一起作废。
    if render.get("error") and not str(render.get("error", "")).startswith(("ModuleNotFoundError:", "server_render_disabled")):
        stripped, dropped = _strip_interactive_params(candidate)
        if dropped:
            retry_image, retry_render = render_vl_to_png_data_url(stripped)
            if retry_image:
                candidate, image, render = stripped, retry_image, retry_render
                report.setdefault("structural_repairs", []).append(
                    f"dropped interactive selection {', '.join(sorted(set(dropped)))}: the chart did not compile with it"
                )
    # 版式证据驱动的修复：图能渲染，但画布远宽/高于自己声明的尺寸，说明有常量被
    # 当成像素坐标推到了画布外。改成数据值后重渲，只有画布确实向声明尺寸收敛才
    # 保留——否则原样退回，程序不替 persona 做版式决定。
    if image and _canvas_overflows(candidate, render):
        adjusted, converted = _repair_datum_value_confusion(source, candidate)
        if converted:
            retry_image, retry_render = render_vl_to_png_data_url(adjusted)
            if retry_image and _canvas_overflow_ratio(candidate, retry_render) < _canvas_overflow_ratio(candidate, render):
                candidate, image, render = adjusted, retry_image, retry_render
                report.setdefault("structural_repairs", []).append(
                    "read positional constants as data values rather than pixels "
                    f"({', '.join(converted)}): the canvas had been stretched far past its declared size"
                )

    report["render"] = render
    render_error = str(render.get("error") or "")
    # Development/test installations may not ship vl-convert. The structural
    # safety checks still run; production with vl-convert treats real compiler
    # failures as a hard rejection.
    if render_error.startswith("ModuleNotFoundError:"):
        report["render_unverified"] = render_error
    elif render.get("error") not in (None, "server_render_disabled"):
        report["errors"].append(f"Vega-Lite render failed: {render['error']}")
    render_integrity_error = _render_integrity_error(image)
    if render_integrity_error:
        report["image_integrity"] = render_integrity_error
        report["errors"].append(render_integrity_error)
    report["accepted"] = not report["errors"]
    return (candidate if report["accepted"] else source), report


def _mark_sequence(spec: dict) -> list[str]:
    """A structural manifest used only by the layout-only repair gate."""
    result: list[str] = []
    for node in _walk(spec):
        if not isinstance(node, dict) or "mark" not in node:
            continue
        mark = node["mark"]
        result.append(str(mark.get("type", "")).lower() if isinstance(mark, dict) else str(mark).lower())
    return result


def _safe_layout_repair(source: dict, candidate: Any) -> tuple[dict, dict]:
    """Accept an LLM layout repair only when it preserves all components.

    This is an integrity boundary, not a design policy: it prohibits adding or
    deleting marks, editing data, and changing editorial strings while allowing
    the LLM to reposition the existing components and resize their containers.
    """
    checked, report = _safe_candidate(source, candidate, [])
    if isinstance(candidate, dict) and _mark_sequence(source) != _mark_sequence(candidate):
        report["errors"].append("layout repair added, removed, or changed a visual component")
    if isinstance(candidate, dict) and _static_texts(source) != _static_texts(candidate):
        report["errors"].append("layout repair changed editorial text content")
    report["accepted"] = not report["errors"]
    return (candidate if report["accepted"] else source), report


def _l1_contract(persona: Persona, spec: dict, facts: dict) -> list[dict[str, Any]]:
    """L1 is an unconditional institutional signature, not optional evidence.

    The fast lane additionally judges each programmatic rule against the source
    chart, so the contract states not only what the institution requires but
    which requirements the supplied chart already breaks. A rule carrying a
    detected violation is evidence, not a hint: Beat 4 re-checks the very same
    detectors against the generated chart.
    """
    contract: list[dict[str, Any]] = []
    for rule in persona.rules:
        entry: dict[str, Any] = {
            "rule_id": rule.id,
            "requirement": rule.rule,
            "strength": rule.strength,
            "check": rule.check,
            "quote": persona.story_text(rule.story) or rule.rule,
            "source": rule.src,
        }
        detection = detect_rule(persona, rule, spec, facts) if rule.check == "programmatic" else None
        if detection is None or not detection.applicable:
            entry["source_compliance"] = "not_machine_checkable"
        elif detection.violated:
            entry["source_compliance"] = "violated_by_source_chart"
            entry["violation_detail"] = detection.detail
        else:
            entry["source_compliance"] = "already_satisfied"
        contract.append(entry)
    return contract


def _programmatic_repairs(persona: Persona, candidate: dict, context: dict | None) -> list[dict[str, Any]]:
    """L1 rules still violated by the generated chart, with compiled repair ops."""
    facts_after = extract_facts(candidate, context)
    pending: list[dict[str, Any]] = []
    for rule in persona.rules:
        if rule.check != "programmatic":
            continue
        detection = detect_rule(persona, rule, candidate, facts_after)
        if detection is None or not detection.applicable or detection.verify_only or not detection.violated:
            continue
        if detection.ops:
            pending.append({"rule_id": rule.id, "ops": detection.ops, "detail": detection.detail})
    return pending


def _enforcement_commitments(persona: Persona, before: dict, after: dict, rule_ids: list[str]) -> list[dict[str, Any]]:
    """Attribute fast-lane repairs to the program, never to the persona's prose.

    The manifest must stay honest about authorship: these entries describe
    edits the deterministic contract check made after the LLM finished, so the
    advisor is not asked to narrate a change it did not write.
    """
    by_component: dict[str, list[str]] = {}
    for row in _manifest_diff_inventory(before, after):
        path = str(row.get("path") or "")
        if path.startswith("/"):
            by_component.setdefault(_path_owner(after, path), []).append(path)
    evidence = ", ".join(rule_ids) or "L1"
    return [
        {
            "id": f"l1-contract-{component}",
            "evidence_id": rule_ids[0] if rule_ids else "L1",
            "component": component,
            "claim": f"Fast-lane contract check restored {persona.name}'s unconditional L1 requirements ({evidence}) that the generated chart had left unmet.",
            "before": "generated chart violated the institution's L1 signature",
            "after": "L1 signature re-verified by the fast-lane detectors",
            "spec_paths": paths,
            "authored_by": "fast_lane_contract_enforcement",
        }
        for component, paths in by_component.items()
    ]


def _verify_l1_contract(
    persona: Persona,
    source: dict,
    candidate: dict,
    text_changes: Any,
    context: dict | None,
) -> tuple[dict, dict[str, Any]]:
    """Beat 4 fast lane: re-run L1 detectors against the LLM-authored chart.

    ``report`` mode records compliance only; ``patch`` mode additionally
    applies the rule's own compiled token operations and keeps the result only
    when it still passes the safety gate. Either way the institution's
    invariants are machine-verified rather than taken on the model's word.
    """
    mode = settings.v2_l1_enforcement
    report: dict[str, Any] = {"ran": mode != "off", "mode": mode, "patched": [], "patch_rejected": []}
    report["before"] = run_invariants(persona, candidate, context)
    if mode == "off":
        report["after"] = report["before"]
        report["unmet"] = [item["rule_id"] for item in report["before"] if not item["ok"]]
        return candidate, report

    final = candidate
    if mode == "patch":
        pending = _programmatic_repairs(persona, candidate, context)
        if pending:
            batch = [op for item in pending for op in item["ops"]]
            rule_ids = [item["rule_id"] for item in pending]
            patched, effect = apply_ops_with_effect(final, batch)
            safe, safety = _safe_candidate(source, patched, text_changes) if effect.changed else (final, {"accepted": False, "errors": ["no operation changed the chart"]})
            if effect.changed and safety["accepted"]:
                final, report["patched"] = safe, rule_ids
            else:
                # One incompatible repair must not discard the others; retry
                # each rule on its own before giving up on the whole batch.
                report["batch_rejected"] = "; ".join(safety.get("errors") or [])[:300]
                for item in pending:
                    step, step_effect = apply_ops_with_effect(final, item["ops"])
                    if not step_effect.changed:
                        report["patch_rejected"].append({"rule_id": item["rule_id"], "reason": "operations produced no change"})
                        continue
                    step_safe, step_safety = _safe_candidate(source, step, text_changes)
                    if step_safety["accepted"]:
                        final = step_safe
                        report["patched"].append(item["rule_id"])
                    else:
                        report["patch_rejected"].append({"rule_id": item["rule_id"], "reason": "; ".join(step_safety["errors"])[:200]})

    report["after"] = run_invariants(persona, final, context)
    report["unmet"] = [item["rule_id"] for item in report["after"] if not item["ok"]]
    return final, report


def _l2_contract(persona: Persona, facts: dict) -> dict[str, list[dict[str, Any]]]:
    """Evaluate L2 conditions fast; semantic cases remain for this persona to decide."""
    triggered, adjudicate, inactive = [], [], []
    for adaptation in persona.adaptations:
        verdict, details = eval_when(adaptation.when, facts)
        item = {
            "rule_id": adaptation.id,
            "when": adaptation.when,
            "then": adaptation.then,
            "strength": adaptation.strength,
            "quote": str(adaptation.raw.get("evidence_quote") or persona.story_text(adaptation.story) or adaptation.then or ""),
            "source": adaptation.src,
            "when_details": details,
        }
        if verdict == MATCH:
            triggered.append(item)
        elif verdict == NO_MATCH:
            inactive.append(item)
        else:
            adjudicate.append(item)
    return {"triggered": triggered, "requires_persona_judgment": adjudicate, "inactive": inactive}


@dataclass
class AdvisorV2:
    llm: Any

    async def advise(self, persona: Persona, spec: dict, context: dict | None = None, on_stage: Any = None, on_progress: Any = None) -> dict:
        async def stage(name: str) -> None:
            if callable(on_stage):
                result = on_stage(name)
                if inspect.isawaitable(result):
                    await result

        async def progress() -> None:
            """Report liveness between LLM round trips.

            Beat 3 is one visible stage but many model calls. Without this the
            caller's watchdog would have to budget for the whole chain at once
            and would kill a healthy persona mid-redesign.
            """
            if callable(on_progress):
                result = on_progress()
                if inspect.isawaitable(result):
                    await result

        context = context or {}
        llm_errors: list[dict[str, str]] = []

        async def ask(stage_name: str, system: str, user: str, fallback: dict, list_key: str | None = None) -> dict:
            token = bind_llm_stage(stage_name)
            try:
                answer = _as_json_object(await self.llm.chat_json(system, user), list_key)
                if not isinstance(answer, dict):
                    raise TypeError(f"expected JSON object, got {type(answer).__name__}")
                return answer
            except Exception as exc:  # transient LLM failures must not lose a run
                llm_errors.append({"stage": stage_name, "error": f"{type(exc).__name__}: {exc}"})
                return fallback
            finally:
                reset_llm_stage(token)
                await progress()

        async def ask_vision(stage_name: str, system: str, user: str, images: list[str], fallback: dict, list_key: str | None = None) -> dict:
            method = getattr(self.llm, "chat_json_vision", None)
            if not callable(method):
                llm_errors.append({"stage": stage_name, "error": "LLM client has no chat_json_vision method"})
                return fallback
            token = bind_llm_stage(stage_name)
            try:
                answer = _as_json_object(await method(system, user, images, detail="high"), list_key)
                if not isinstance(answer, dict):
                    raise TypeError(f"expected JSON object, got {type(answer).__name__}")
                return answer
            except Exception as exc:  # visual critique is advisory; safety gate still protects output
                llm_errors.append({"stage": stage_name, "error": f"{type(exc).__name__}: {exc}"})
                return fallback
            finally:
                reset_llm_stage(token)
                await progress()

        # Beat 1 (slow): the persona reads the actual chart before proposing anything.
        await stage("reading")
        facts = extract_facts(spec, context)
        communication_goal = str(context.get("communication_goal") or "").strip()
        user_goal_contract = (
            f"The user explicitly requires this communication goal: {communication_goal}"
            if communication_goal
            else "No explicit user communication goal was supplied. Infer the chart's intended message from the source chart."
        )
        b1 = await ask(
            "beat1",
            f"You are {persona.name}. Beat 1: read the supplied chart as an editorial designer. Do not propose a solution. {user_goal_contract} If the user supplied a goal, restate its visual implication faithfully and identify what evidence the chart must foreground. JSON only: {{\"story\":str,\"audience\":str,\"data_roles\":[],\"risks\":[],\"goal_interpretation\":str}}",
            json.dumps({"facts": facts, "communication_goal": communication_goal or None, "persona_l3": persona.philosophy_text()}, ensure_ascii=False),
            {"story": "Live chart reading failed; retain the supplied chart.", "audience": "unspecified", "data_roles": [], "risks": []},
        )

        # Beat 2 (fast): deterministic evidence collection, deliberately no decision.
        await stage("detecting")
        l1_contract = _l1_contract(persona, spec, facts)
        l2_contract = _l2_contract(persona, facts)
        evidence = {"facts": facts, "l1": l1_contract, "l1_tokens": persona.tokens, "l2": l2_contract, "l3": persona.philosophy_text()}
        persona_core = (
            f"You are not a generic chart improver. You are the {persona.name} design persona.\n"
            f"Task contract: {user_goal_contract}\n"
            "When the user supplied a communication goal, it is the required message and evaluation target. L1/L2/L3 determine how this persona expresses that goal; they must never substitute a different message.\n\n"
            "Your L1 institutional signature is binding across every chart. Apply its tokens and rules unless explicitly inapplicable; do not silently retain the source chart's colours, font, background, grid, hierarchy or legend merely because they already exist:\n"
            + json.dumps({"tokens": persona.tokens, "rules": l1_contract}, ensure_ascii=False)
            + "\n\n"
            "Your full L2 guideline catalogue has been evaluated provisionally against this chart. Every `triggered` rule is binding. Reconsider every `requires_persona_judgment` rule from the chart reading; use each applicable L2 rule as design evidence rather than decorative reference material:\n"
            + json.dumps(l2_contract, ensure_ascii=False)
            + "\n\n"
            "Your governing design philosophy (L3) is the highest-priority source of style, hierarchy, narrative and composition decisions:\n"
            f"{persona.philosophy_text()}\n\n"
            "L3 decides how to express the persona; it never cancels L1 or a triggered L2 requirement."
        )

        # Beat 3 (slow): the LLM has complete design authority inside data/text safety bounds.
        await stage("adjudicating")
        b3 = await ask(
            "beat3",
            f"""{persona_core}

Beat 3: completely redesign the supplied Vega-Lite chart according to this persona, the Beat 1 reading and the task contract. When a user goal is supplied, make that goal the chart's primary reading outcome, not a secondary annotation.

You have full authority over the Vega-Lite presentation: mark and same-family chart form, encodings, scales, axes, ticks, grid, order, transforms, layers, annotations, titles, typography, palette, backgrounds, legends, spacing, padding, width and height. Diagnose visible problems such as collisions, weak hierarchy, poor annotation placement, colour ambiguity and wasted space. Reconstruct the chart rather than patching its old code when useful. Preserve the broad analytic chart family unless the evidence makes a different form clearly necessary.

Non-negotiable integrity rules: preserve the original primary analytic `data` object exactly (including values/url); do not invent analytic data fields or values. You may rebuild small local annotation/rule data tables when needed for correct placement. Retain every static title/subtitle/text-mark string unless `text_changes` explicitly maps its exact old text to the replacement and gives a reason. Keep source and meaningful annotations. The result must be legal Vega-Lite v5 JSON.

Never ship authoring placeholders such as `[Add source]`, `TBD` or `<name>`. If a guideline asks for a caption whose fact the supplied chart does not provide, either attribute only what the chart genuinely states or omit that line; a placeholder does not satisfy the rule.

To place a reference line, highlight band or annotation at a position on the scale, write `{{"datum": 2016}}` on the x/y channel. `{{"value": 2016}}` on a positional channel means 2016 *pixels* from the plot edge, which pushes the mark off the plot and stretches the canvas; `value` also never takes a `type`. Use `value` only for non-positional constants such as colour, size or opacity.

For compact input, the immutable analytic table is represented by `data: {{"$ref":"__vizguide_primary_data__", ...}}`. Keep that exact `$ref` data object in every analytic layer that uses the source table; it will be restored to the exact original values after your response. Do not replace it with invented or sampled data.

Deliberately consider the full L1, L2 and L3 knowledge base before answering. Apply as many compatible guidelines as can produce a coherent, visibly improved chart, but record a commitment only for a real visible effect in the final spec. Do not pad the answer with rule names or preservation claims. Then self-audit the candidate for text overlap, clipping, missing data layers, invalid field references and violations of binding L1/L2 requirements. Do not use generic house-style defaults. At least one non-colour/non-font structural decision must be justified by this persona's L3 philosophy, not merely by generic readability.

Your commitments are the user-visible component change record. They must be an exhaustive, strict non-overlapping partition of the final source→candidate visual differences: if you change palette, fonts, axes, labels, title, spacing or chart structure, output separate commitments for each affected component. Never use an umbrella commitment such as "redesigned the chart" or "whole-chart reconstruction"; never use `structure` as a container for unrelated presentation changes. Cite leaf JSON-pointer locations only—not a whole mark, encoding, layer, data table, config object, or composition container.

Ownership contract: `color` owns only background/palette and color/fill/stroke/range leaves; `typography` owns only font, size, weight, style and line-height leaves; `title` owns only title/subtitle wording and non-typographic title placement leaves; `axes` owns only axis/scale/grid/tick/domain leaves (not font/color); `labels` owns only text/legend wording, text binding, and placement leaves (not font/color); `layout` owns only width/height/padding/spacing/autosize/bounds/alignment/composition placement leaves; `structure` owns only mark type, analytic encoding/data binding, transforms and non-text layers (not any property owned above). Do not claim a preservation, confirmation, or unchanged value as a modification. Every sentence must describe only its own component and must name the actual old and final value; do not mention effects owned by another component.

JSON only: {{
  \"story\": \"user-readable design rationale\",
  \"persona_stance\": [{{\"l3_ref\":\"philosophy id/title\",\"consequence\":\"specific compositional consequence\"}}],
  \"goal_implementation\": {{\"goal\":\"exact user goal or inferred chart message\",\"status\":\"implemented|unmet\",\"primary_reading_outcome\":\"what a reader sees first\",\"spec_evidence\":\"specific marks/title/annotations/layout that carry the goal\"}},
  \"layer_implementation\": {{\"l1\":[{{\"rule_id\":\"L1 id\",\"status\":\"implemented|inapplicable|unmet\",\"spec_evidence\":\"specific visible/spec location\",\"quote\":\"persona quote\"}}],\"l2\":[{{\"rule_id\":\"L2 id\",\"status\":\"implemented|not_applicable|unmet\",\"trigger\":\"Beat 2 fact or persona judgment\",\"spec_evidence\":\"specific visible/spec location\",\"quote\":\"persona quote\"}}],\"l3\":[{{\"rule_id\":\"L3 id\",\"status\":\"implemented|unmet\",\"spec_evidence\":\"specific visible consequence\",\"quote\":\"persona quote\"}}]}},
  \"commitments\": [{{\"id\":\"...\",\"evidence_id\":\"persona rule/story id\",\"component\":\"title|color|axes|labels|typography|layout|structure\",\"claim\":\"one specific completed visible before→after component change\",\"before\":\"concise original state\",\"after\":\"concise final state\",\"spec_paths\":[\"/exact/path/in/candidate_spec\"]}}],
  \"text_changes\": [{{\"before\":\"exact original static text\",\"after\":\"replacement text\",\"reason\":\"persona-grounded reason\"}}],
  \"candidate_spec\": {{...complete Vega-Lite spec...}}
}}""",
            json.dumps({"beat1": b1, "evidence": evidence, "protected_static_texts": sorted(_static_texts(spec)), "source_spec": _compact_for_llm(spec), "primary_data_reference": _PRIMARY_DATA_REF}, ensure_ascii=False),
            {"story": "No redesign was produced because the live model was unavailable.", "commitments": [], "text_changes": [], "candidate_spec": spec},
        )
        b3 = {**b3, "text_changes": _normalise_text_changes(b3.get("text_changes"))}

        # Still within Beat 3: return actual compiler failures to the same
        # persona for code repair.  Do not replace a failed draft with the
        # source spec while this loop is running: the next repair must inspect
        # the exact failed program rather than a silent rollback.
        preview_spec, preview_safety = _safe_candidate(spec, b3.get("candidate_spec"), b3.get("text_changes"))
        code_repairs: list[dict[str, Any]] = []
        for repair_attempt in range(1, 3):
            if preview_safety["accepted"]:
                break
            repaired_b3 = await ask(
                f"beat3_repair_{repair_attempt}",
                f"""{persona_core}

Your Beat 3 Vega-Lite reconstruction failed a structural/compiler check (repair attempt {repair_attempt} of 2). Return a corrected COMPLETE candidate_spec, not a patch and not an explanation. Preserve every binding L1 and triggered L2 implementation as well as your persona-specific visual design wherever possible.

You must preserve the primary analytic data exactly. You must also include every protected static text exactly, unless you put its exact old/new pair in text_changes. In particular, source/credit text must remain visible as a text mark or legal title/subtitle text. Generated tick labels do not need copying.

When the candidate contains `data: {{"$ref":"__vizguide_primary_data__", ...}}`, retain that exact data reference; the service restores its immutable full table after your response.

Treat every reported render failure as a Vega-Lite code defect, not as a design preference. Inspect the complete previous_candidate_spec and correct the actual invalid transform, expression, field reference, layer, scale or composition that caused it. Vega expressions are not JavaScript: never use `undefined`, member calls such as `.indexOf(...)`, or browser globals; use Vega expression functions such as `isValid(...)`, `indexof(...)`, and explicit `null` tests. A "uniform blank canvas" means compilation returned a PNG but Vega did not successfully paint the chart; do not return the same construct or merely change colours/text. Self-check that the repaired spec paints its analytic marks, axes and required text.

JSON only: {{\"story\":str,\"commitments\":[{{\"id\":str,\"evidence_id\":str,\"component\":\"title|color|axes|labels|typography|layout|structure\",\"claim\":str,\"before\":str,\"after\":str,\"spec_paths\":[str]}}],\"text_changes\":[{{\"before\":str,\"after\":str,\"reason\":str}}],\"candidate_spec\":{{...}}}}""",
                json.dumps({"safety_errors": preview_safety["errors"], "render_report": preview_safety.get("render") or {}, "image_integrity": preview_safety.get("image_integrity"), "protected_static_texts": sorted(_static_texts(spec)), "previous_candidate_spec": _compact_for_llm(b3.get("candidate_spec")), "source_spec": _compact_for_llm(spec), "primary_data_reference": _PRIMARY_DATA_REF}, ensure_ascii=False),
                b3,
                list_key="commitments",
            )
            # A repair response may concentrate on the spec and omit the
            # coverage ledger; preserve the original persona decisions unless
            # it deliberately returns a refreshed ledger.
            b3 = {
                **b3,
                **repaired_b3,
                "text_changes": _merge_text_changes(b3.get("text_changes"), repaired_b3.get("text_changes")),
                "layer_implementation": repaired_b3.get("layer_implementation") if isinstance(repaired_b3.get("layer_implementation"), dict) else b3.get("layer_implementation"),
                "goal_implementation": repaired_b3.get("goal_implementation") if isinstance(repaired_b3.get("goal_implementation"), dict) else b3.get("goal_implementation"),
            }
            preview_spec, preview_safety = _safe_candidate(spec, b3.get("candidate_spec"), b3.get("text_changes"))
            code_repairs.append({"attempt": repair_attempt, "safety": preview_safety})

        # Establish the safe Beat 3 baseline before visual review. A later visual
        # revision must never be allowed to erase this valid reconstruction.
        base_spec, base_safety = _safe_candidate(spec, b3.get("candidate_spec"), b3.get("text_changes"))
        # Keep a failed draft observable.  It remains non-executable until the
        # LLM fixes it, but losing it here made an advisor appear to have made
        # no decisions at all.
        draft_spec = _restore_primary_data(spec, b3.get("candidate_spec"))

        # Still Beat 3: inspect real pixels, rather than attempting to infer
        # whitespace and collisions from code. The first image is the original;
        # the second is the persona's candidate.
        original_png, original_render = render_vl_to_png_data_url(spec)
        candidate_png, candidate_render = render_vl_to_png_data_url(base_spec)
        visual_review: dict[str, Any] = {"ran": False, "original_render": original_render, "candidate_render": candidate_render, "base_safety": base_safety, "code_repairs": code_repairs}
        evaluation_focus = (
            f"the user's stated communication goal: {communication_goal}"
            if communication_goal
            else "the chart's own topic, main comparison/trend, and intended audience inferred from the original chart"
        )
        if base_safety["accepted"] and original_png and candidate_png:
            visual = await ask_vision(
                "beat3_visual_review",
                f"""{persona_core}

You are now this persona's visual editorial critic. You receive TWO rendered charts in order: IMAGE 1 is the original; IMAGE 2 is the candidate reconstruction. Inspect pixels, not just the supplied JSON. Your L3 philosophy must decide what is acceptable; do not fall back to generic chart-cleanup conventions.

Check specifically for: abnormal empty canvas regions; a plot area disproportionately small or separated from text by excessive blank space; title, legend, caption and source reading order; text/annotation overlap; clipped or off-canvas text; annotations detached from their referent; marks obscured by labels; and whether the candidate's hierarchy/composition is genuinely distinctive to this persona rather than a generic repair. In the same audit, inspect every binding L1 rule/token and each triggered L2 rule: verify their visible/spec consequence, not merely whether the LLM mentioned them. L3 cannot excuse an L1/L2 miss.

`layout_risks` lists structural hazards a program found in the candidate's own code. They are places to look, not verdicts: confirm each one against the image and either report it as a finding or repair it. Entries marked `inherited_from_original` also exist in IMAGE 1, so judge whether the candidate made them worse rather than treating them as new damage.

Return a COMPLETE revised Vega-Lite spec even if you judge it acceptable. Preserve the primary analytic data and protected text rules. Do not merely describe changes. List every independently visible change that is actually present in revised_spec; do not count mere preservation as a change. The commitments are a detailed, non-overlapping component manifest: one changed leaf path may occur in only one entry. Use leaf JSON-pointer paths, never whole objects/layers. Ownership is strict: color only palette/color/fill/stroke/background; typography only font/size/weight/style; title only title wording/placement; axes only axis/scale/grid/tick/domain; labels only text/legend wording/binding/placement; layout only canvas/composition spacing and dimensions; structure only marks, analytic encodings/data and transforms. Do not make one commitment describe another component's result.

Keep any `data: {{"$ref":"__vizguide_primary_data__", ...}}` object unchanged: it denotes the immutable complete analytic table, not a Vega-Lite field you may redesign.

Also compare IMAGE 2 against IMAGE 1 for {evaluation_focus}. When a user goal is supplied, judge that exact goal—not a narrower proxy such as generic trend readability. State whether the revised chart is better, worse, or unchanged at expressing it; cite visible evidence from both images. This is an honest evaluation, not a promise that it is improved. JSON only:
{{\"verdict\":\"pass|revise\",\"layout_status\":\"resolved|repair_needed\",\"findings\":[{{\"issue\":str,\"image_evidence\":str,\"l3_ref\":str,\"severity\":\"high|medium|low\"}}],\"goal_audit\":{{\"goal\":str,\"status\":\"implemented|unmet\",\"visible_evidence\":str,\"missing_or_conflicting_evidence\":str}},\"layer_audit\":{{\"l1\":[{{\"rule_id\":str,\"status\":\"implemented|unmet\",\"visible_evidence\":str,\"quote\":str}}],\"l2\":[{{\"rule_id\":str,\"status\":\"implemented|unmet\",\"visible_evidence\":str,\"quote\":str}}],\"l3\":[{{\"rule_id\":str,\"status\":\"implemented|unmet\",\"visible_evidence\":str,\"quote\":str}}]}},\"intent_assessment\":{{\"focus\":str,\"comparison\":\"better|worse|unchanged\",\"reason\":str,\"original_evidence\":str,\"revised_evidence\":str}},\"commitments\":[{{\"id\":str,\"evidence_id\":str,\"component\":\"title|color|axes|labels|typography|layout|structure\",\"claim\":str,\"before\":str,\"after\":str,\"spec_paths\":[str]}}],\"text_changes\":[{{\"before\":str,\"after\":str,\"reason\":str}}],\"revised_spec\":{{...complete Vega-Lite spec...}}}}""",
                json.dumps({"beat1": b1, "communication_goal": communication_goal or None, "evaluation_focus": evaluation_focus, "l1_contract": l1_contract, "l1_tokens": persona.tokens, "l2_contract": l2_contract, "l3_evidence": persona.philosophy_text(), "protected_static_texts": sorted(_static_texts(spec)), "layout_risks": _new_layout_risks(spec, base_spec), "candidate_spec": _compact_for_llm(base_spec), "primary_data_reference": _PRIMARY_DATA_REF}, ensure_ascii=False),
                [original_png, candidate_png],
                {},
                list_key="findings",
            )
            revised = visual.get("revised_spec") if isinstance(visual.get("revised_spec"), dict) else None
            revision_safety: dict[str, Any] | None = None
            if revised is not None:
                _checked, revision_safety = _safe_candidate(spec, revised, visual.get("text_changes"))
            if revised is not None and revision_safety and revision_safety["accepted"]:
                adopted_spec = _checked
                adopted_text_changes = _merge_text_changes(b3.get("text_changes"), visual.get("text_changes"))
                adopted_commitments = visual.get("commitments") if isinstance(visual.get("commitments"), list) and visual.get("commitments") else b3.get("commitments", [])
                b3 = {
                    **b3,
                    "candidate_spec": adopted_spec,
                    "text_changes": adopted_text_changes,
                    "commitments": adopted_commitments,
                }
            else:
                # Keep the already accepted initial candidate, not the source spec.
                b3 = {**b3, "candidate_spec": base_spec}
            visual_review = {
                "ran": True,
                "verdict": visual.get("verdict"),
                "findings": visual.get("findings") or [],
                "original_render": original_render,
                "candidate_render": candidate_render,
                "revision_accepted": bool(revision_safety and revision_safety["accepted"]),
                "revision_rejected_errors": (revision_safety or {}).get("errors") or [],
                "intent_assessment": visual.get("intent_assessment"),
                "goal_audit": visual.get("goal_audit") if isinstance(visual.get("goal_audit"), dict) else {},
                "layer_audit": visual.get("layer_audit") if isinstance(visual.get("layer_audit"), dict) else {},
            }

            # A dedicated layout pass follows editorial review. It receives the
            # rendered chart and review evidence, but is forbidden to redesign
            # or rewrite: its job is solely to place the already-present chart,
            # axes, titles, annotations, captions and source into a coherent
            # composition guided by this persona's L2/L3 layout principles.
            layout_input = b3.get("candidate_spec")
            layout_png, layout_render = render_vl_to_png_data_url(layout_input)
            layout_needed = str(visual.get("layout_status") or "resolved").lower() == "repair_needed"
            if layout_png and layout_needed:
                layout = await ask_vision(
                    "beat3_layout_repair",
                    f"""{persona_core}

You are the dedicated layout editor, working after a design review. IMAGE 1 is the original chart and IMAGE 2 is the reviewed candidate. Repair only IMAGE 2's composition. Your governing L2/L3 layout, typography, hierarchy and reading-order guidance is binding.

You MUST preserve every existing visual component, mark type, analytic value, and editorial string exactly. Do not add, delete, rewrite, recolour, restyle, change chart type, change data mapping, or introduce new annotations. You may only alter canvas/container sizing, padding, view composition, axis/legend/title/caption placement, and positional/layout properties of the existing components.

Make the main plot occupy an intentional share of the canvas; put title/subtitle before the plot and source/caption after it; keep annotations attached to their referents without covering data; keep every paragraph as one contiguous reading unit rather than scattering or semantically reordering its fragments. Never use a prose text field as a quantitative or nominal plot coordinate merely to position a paragraph. Use stable chart/caption regions or a composition container instead of fragile absolute placements wherever the existing components permit it.

Use the review findings as concrete defects to resolve. Return a COMPLETE `candidate_spec`, not a patch or commentary. JSON only: {{"candidate_spec":{{...complete Vega-Lite spec...}}}}""",
                    json.dumps({
                        "review_findings": visual.get("findings") or [],
                        "protected_static_texts": sorted(_static_texts(layout_input)) if isinstance(layout_input, dict) else [],
                        "candidate_spec": _compact_for_llm(layout_input),
                        "primary_data_reference": _PRIMARY_DATA_REF,
                    }, ensure_ascii=False),
                    [original_png, layout_png],
                    {},
                )
                layout_spec = layout.get("candidate_spec") if isinstance(layout.get("candidate_spec"), dict) else None
                layout_safety: dict[str, Any] | None = None
                if layout_spec is not None and isinstance(layout_input, dict):
                    _laid_out, layout_safety = _safe_layout_repair(layout_input, layout_spec)
                    if layout_safety["accepted"]:
                        b3 = {**b3, "candidate_spec": _laid_out}
                visual_review["layout_repair"] = {
                    "attempted": True,
                    "input_render": layout_render,
                    "accepted": bool(layout_safety and layout_safety["accepted"]),
                    "rejected_errors": (layout_safety or {}).get("errors") or [],
                    "render": (layout_safety or {}).get("render") or {},
                }
            else:
                visual_review["layout_repair"] = {"attempted": False, "skipped": "not_requested_by_visual_critic" if layout_png else "candidate_render_unavailable"}

            # A rendered review is a quality gate, not merely telemetry.  The
            # earlier two calls may have produced a correction, so render the
            # *actual* candidate that would leave Beat 3 and ask a fresh judge
            # to approve that exact pair of pixels.  This remains inside the
            # slow design beat; Beat 4 stays a non-aesthetic safety compiler.
            # 必须渲染纠错后的那一份：直接渲原始候选图会因协议键之类的非设计缺陷
            # 失败，于是验收被跳过、图却照常交付——正是要堵的失效开放。
            gate_spec, gate_safety = _safe_candidate(spec, b3.get("candidate_spec"), b3.get("text_changes"))
            final_png, final_render = render_vl_to_png_data_url(gate_spec) if gate_safety["accepted"] else (None, gate_safety.get("render") or {})
            if final_png:
                acceptance = await ask_vision(
                    "beat3_visual_acceptance",
                    f"""{persona_core}

You are the final acceptance gate. IMAGE 1 is the original chart and IMAGE 2 is the exact candidate that will be shown to the user. Do not propose another design and do not assume that earlier reviewers fixed anything. Judge only the visible pixels.

Approve only when IMAGE 2 is clearly better than IMAGE 1 for {evaluation_focus}, while also having no severe overlap, clipping, detached text, abnormal empty canvas, broken reading order, loss of this persona's distinctive L3 editorial character, or any visible miss of a binding L1 rule/token or triggered L2 rule. `layout_risks` names structural hazards a program found in IMAGE 2's own code; check each against the pixels before deciding, and treat entries marked `inherited_from_original` as pre-existing rather than new damage. The earlier review findings below are unresolved constraints: do not contradict them or downgrade them without visible evidence that IMAGE 2 fixes each one. Verify that explanatory prose is contiguous and readable, and that source/caption text sits outside the main plot. If it is merely unchanged, worse, or has any high-severity visible defect, return `revise`: the candidate will be sent back/rejected rather than shown. Be conservative and honest.

When revision is needed, choose `repair_route` yourself. Use `intent_rework` only when the chart's analytic marks and implementation are sound but its visible narrative/hierarchy fails to express {evaluation_focus}. Use `vega_lite_repair` for every implementation problem: missing/invisible marks, bad fields/transforms/scales, duplicate or crowded axes/labels, overlap, clipping, empty plot area, incorrect text placement, or invalid Vega-Lite composition. Include exact code-focused diagnoses for that route.

JSON only: {{"verdict":"pass|revise","delivery_score":0-100,"repair_route":"intent_rework|vega_lite_repair","code_diagnosis":[{{"path":str,"problem":str,"required_fix":str}}],"findings":[{{"issue":str,"image_evidence":str,"severity":"high|medium|low"}}],"intent_assessment":{{"focus":str,"comparison":"better|worse|unchanged","reason":str,"original_evidence":str,"revised_evidence":str}}}}""",
                    json.dumps({"communication_goal": communication_goal or None, "evaluation_focus": evaluation_focus, "earlier_review_findings": visual.get("findings") or [], "earlier_intent_assessment": visual.get("intent_assessment") or {}, "layout_repair": visual_review.get("layout_repair") or {}, "layout_risks": _new_layout_risks(spec, gate_spec)}, ensure_ascii=False),
                    [original_png, final_png],
                    {},
                    list_key="findings",
                )
                assessment = acceptance.get("intent_assessment") if isinstance(acceptance.get("intent_assessment"), dict) else {}
                high_severity = any(
                    isinstance(finding, dict) and str(finding.get("severity", "")).lower() == "high"
                    for finding in (acceptance.get("findings") or [])
                )
                accepted = (
                    str(acceptance.get("verdict", "")).lower() == "pass"
                    and str(assessment.get("comparison", "")).lower() == "better"
                    and not high_severity
                )
                visual_review["acceptance"] = {
                    "render": final_render,
                    "verdict": acceptance.get("verdict"),
                    "delivery_score": _review_score(acceptance),
                    "repair_route": acceptance.get("repair_route"),
                    "code_diagnosis": acceptance.get("code_diagnosis") or [],
                    "findings": acceptance.get("findings") or [],
                    "intent_assessment": assessment or None,
                    "accepted": accepted,
                }
                if not accepted:
                    # Each return is bounded.  It remains an LLM-owned Beat 3
                    # repair; the loop only limits retries, never edits a spec.
                    retries: list[dict[str, Any]] = []
                    best_score = _review_score(acceptance)
                    best_b3 = dict(b3)
                    current_findings = acceptance.get("findings") or []
                    current_assessment = assessment
                    current_png = final_png
                    repair_route = str(acceptance.get("repair_route") or "vega_lite_repair").lower()
                    if repair_route not in {"intent_rework", "vega_lite_repair"}:
                        repair_route = "vega_lite_repair"
                    if repair_route == "intent_rework":
                        repair_stage = "beat3_visual_return"
                        repair_instruction = f"""The visual implementation is sound, but its editorial expression does not successfully communicate {evaluation_focus}. Rebuild the candidate's narrative hierarchy and composition using the intent assessment below. This is the only route where you may make broader design changes."""
                    else:
                        repair_stage = "beat3_vega_lite_repair"
                        repair_instruction = """This is a Vega-Lite implementation repair, not a new design pass. Correct the exact code failures in `code_diagnosis` and acceptance findings: preserve the established visual strategy, analytic data, marks and editorial message wherever they are not implicated. Repair data bindings, transforms, encodings, scales, axes, text/container placement, layers or composition so the existing chart actually renders and reads correctly."""
                    for attempt in range(1, 2):
                        rework = await ask_vision(
                        repair_stage,
                        f"""{persona_core}

Your candidate has been RETURNED by the final visual acceptance gate (repair attempt {attempt} of 1). IMAGE 1 is the original and IMAGE 2 is your rejected candidate. {repair_instruction} Return a COMPLETE Vega-Lite `candidate_spec`, not a patch or explanation. The result must visibly resolve every reported high-severity issue.

Do not shrink the plot into unused canvas or use fragile pixel-positioned text. Preserve primary analytic data exactly and preserve protected static text unless an exact before/after pair is declared in text_changes. List only commitments that are visibly present in your returned spec.

JSON only: {{"story":str,"commitments":[{{"id":str,"evidence_id":str,"component":"title|color|axes|labels|typography|layout|structure","claim":str,"before":str,"after":str,"spec_paths":[str]}}],"text_changes":[{{"before":str,"after":str,"reason":str}}],"candidate_spec":{{...complete Vega-Lite spec...}}}}""",
                        json.dumps({
                            "communication_goal": communication_goal or None,
                            "evaluation_focus": evaluation_focus,
                            "acceptance_findings": current_findings,
                            "acceptance_assessment": current_assessment,
                            "repair_route": repair_route,
                            "code_diagnosis": acceptance.get("code_diagnosis") or [],
                            "protected_static_texts": sorted(_static_texts(spec)),
                            "rejected_candidate_spec": _compact_for_llm(best_b3.get("candidate_spec")),
                            "source_spec": _compact_for_llm(spec),
                            "primary_data_reference": _PRIMARY_DATA_REF,
                        }, ensure_ascii=False),
                        [original_png, current_png],
                        {},
                        list_key="commitments",
                    )
                        repaired_spec = rework.get("candidate_spec") if isinstance(rework.get("candidate_spec"), dict) else None
                        repaired_safety: dict[str, Any] | None = None
                        repaired_text_changes = _merge_text_changes(best_b3.get("text_changes"), rework.get("text_changes"))
                        if repaired_spec is not None:
                            _repaired, repaired_safety = _safe_candidate(spec, repaired_spec, repaired_text_changes)
                        attempt_record: dict[str, Any] = {"attempt": attempt, "repair_route": repair_route, "safety": repaired_safety}
                        if not (repaired_safety and repaired_safety["accepted"]):
                            retries.append(attempt_record)
                            continue
                        repaired_png, repaired_render = render_vl_to_png_data_url(_repaired)
                        if not repaired_png:
                            attempt_record["acceptance"] = {"accepted": False, "skipped": "repaired_render_unavailable"}
                            retries.append(attempt_record)
                            continue
                        acceptance = await ask_vision(
                            "beat3_visual_acceptance",
                            f"""{persona_core}

You are the final acceptance gate. IMAGE 1 is the original and IMAGE 2 is the repaired candidate. Judge pixels only. Approve only when it is clearly better for {evaluation_focus}, resolves every earlier high-severity failure, and has no new high-severity layout, clipping, overlap, blank-canvas, or persona-guideline defect. Also give `delivery_score` from 0 to 100 for how suitable IMAGE 2 is to deliver relative to IMAGE 1; score the visible result honestly, even when verdict is revise. If revise, choose the appropriate `repair_route` and code diagnosis using the same rule as before. JSON only: {{"verdict":"pass|revise","delivery_score":0-100,"repair_route":"intent_rework|vega_lite_repair","code_diagnosis":[{{"path":str,"problem":str,"required_fix":str}}],"findings":[{{"issue":str,"image_evidence":str,"severity":"high|medium|low"}}],"intent_assessment":{{"focus":str,"comparison":"better|worse|unchanged","reason":str,"original_evidence":str,"revised_evidence":str}}}}""",
                            json.dumps({"evaluation_focus": evaluation_focus, "previous_failures": current_findings}, ensure_ascii=False),
                            [original_png, repaired_png],
                            {},
                            list_key="findings",
                        )
                        assessment = acceptance.get("intent_assessment") if isinstance(acceptance.get("intent_assessment"), dict) else {}
                        high_severity = any(isinstance(item, dict) and str(item.get("severity", "")).lower() == "high" for item in (acceptance.get("findings") or []))
                        accepted = str(acceptance.get("verdict", "")).lower() == "pass" and str(assessment.get("comparison", "")).lower() == "better" and not high_severity
                        candidate_score = _review_score(acceptance)
                        attempt_record["acceptance"] = {"render": repaired_render, "verdict": acceptance.get("verdict"), "delivery_score": candidate_score, "findings": acceptance.get("findings") or [], "intent_assessment": assessment or None, "accepted": accepted}
                        retries.append(attempt_record)
                        if accepted or candidate_score > best_score:
                            best_score = candidate_score
                            best_b3 = {**b3, "candidate_spec": _repaired, "text_changes": repaired_text_changes, "commitments": rework.get("commitments") if isinstance(rework.get("commitments"), list) else []}
                            current_findings = acceptance.get("findings") or []
                            current_assessment = assessment
                            current_png = repaired_png
                            attempt_record["selected_for_delivery"] = True
                        if accepted:
                            break
                    b3 = best_b3
                    visual_review["return_rework"] = {"attempted": True, "max_attempts": 1, "initial_repair_route": repair_route, "attempts": retries}
                    if not accepted:
                        visual_review["delivered_despite_visual_rejection"] = True
                        visual_review["return_reason"] = "visual_return_max_attempts_reached"
            else:
                # 记录渲染失败原因：不留痕就无法分辨「候选图真坏」与「渲染器抖动」，
                # 而两者对是否应当放行的判断完全相反。
                visual_review["acceptance"] = {
                    "accepted": False,
                    "skipped": "final_render_unavailable",
                    "render": final_render,
                }
                visual_review["delivered_despite_visual_rejection"] = True
                visual_review["return_reason"] = "final_render_unavailable"
        else:
            visual_review["skipped"] = "base_candidate_invalid" if not base_safety["accepted"] else "render_unavailable"

        # Beat 4 (fast): integrity compilation and contract verification. It
        # makes no aesthetic choice; it validates the Vega-Lite artifact,
        # re-checks the institution's L1 invariants with the same detectors
        # that produced the Beat 2 contract, and validates the advisor's own
        # user-facing account of what that artifact changed.
        await stage("compiling")
        checked_spec, safety = _safe_candidate(spec, b3.get("candidate_spec"), b3.get("text_changes"))
        # The generated chart is only trusted once the unconditional layer has
        # been verified against it. Enforcement runs before the manifest audit
        # so the change record describes the chart that is actually delivered.
        enforcement: dict[str, Any] = {"ran": False, "skipped": "candidate_failed_safety_gate"}
        if safety["accepted"]:
            pre_enforcement = checked_spec
            checked_spec, enforcement = _verify_l1_contract(persona, spec, checked_spec, b3.get("text_changes"), context)
            enforcement_commitments = (
                _enforcement_commitments(persona, pre_enforcement, checked_spec, enforcement["patched"])
                if enforcement.get("patched")
                else []
            )
        else:
            enforcement_commitments = []
        # Safety is a delivery-state report, not an eraser.  Preserve a
        # syntactically shaped failed draft so its independent changes and the
        # compiler diagnosis remain visible to the user and repairable by the
        # next LLM pass.  A later composer must not execute it automatically.
        final_spec = checked_spec if safety["accepted"] else draft_spec if isinstance(draft_spec, dict) else spec
        changed = final_spec != spec
        proposed_commitments = b3.get("commitments") if isinstance(b3.get("commitments"), list) else []
        initial_valid, initial_rejections = _check_commitments(spec, final_spec, proposed_commitments) if changed else ([], [])
        commitments = proposed_commitments
        repair_attempts: list[dict[str, Any]] = []
        # The advisor must document the final artifact, not merely preserve a
        # few commitments it happened to mention while writing the spec.  Even
        # an empty or superficially valid initial list is rebuilt against the
        # actual source→candidate diff inventory.  Beat 4 never rewrites the
        # advisor's design; it only makes the component contract truthful.
        # Paths written by the deterministic L1 enforcement are withheld from
        # the model: they already carry a program-authored commitment, and the
        # advisor must not be prompted to claim authorship of them.
        enforcement_paths = {
            path for item in enforcement_commitments for path in item["spec_paths"]
        }
        inventory = [
            row for row in _manifest_diff_inventory(spec, final_spec)
            if str(row.get("path")) not in enforcement_paths
        ] if changed else []
        if changed:
            for attempt in range(1, 3):
                current_valid, current_rejections = _check_commitments(spec, final_spec, commitments)
                missing_components = _missing_manifest_components(inventory, current_valid)
                # The first pass is deliberately mandatory.  A list can pass
                # path validation while still hiding colour, typography or
                # layout changes inside one broad structural explanation.
                if attempt > 1 and not current_rejections and not missing_components:
                    commitments = current_valid
                    break
                repaired = await ask(
                    f"beat4_commitment_repair_{attempt}",
                    """You are repairing the user-facing change manifest for your OWN completed visualization. You may not alter, redesign, omit, or return Vega-Lite code. The source spec and exact final candidate spec are fixed. Rebuild the COMPLETE component manifest from the supplied source→candidate diff inventory, then correct every listed validation error.

This manifest is the Review Board's only explanation of the candidate. It must account for every listed visual-design difference (except primary-data preservation) using detailed, non-overlapping commitments. Never collapse multiple categories into a generic "whole-chart reconstruction" or a generic structure scaffold. If the inventory includes colour, typography, axes, labels, title, or layout paths, make separately scoped commitments for those paths—even if the chart topology also changed. Structure is permitted only for mark type, analytic encoding/data binding, transforms, sort/order, and non-text analytic layers; it must never cite or describe palette, font, title, axis, label, legend, canvas, or spacing changes.

Return a corrected commitment for every valid input id when it still corresponds to a real final difference; you may split it using `<id>-2`, `<id>-3`. You must also ADD commitments when the inventory shows a changed component absent from the input. Each commitment must have exactly one component from title|color|axes|labels|typography|layout|structure, and must cite one or more exact leaf JSON-pointer paths in `candidate_spec` (paths begin at `/`, never `/candidate_spec`). Paths cannot overlap between entries. Every path must identify a real source→candidate difference. Its explanation must concern only its component:
- color: background/palette/color/fill/stroke/range only;
- typography: font/size/weight/style/line-height only;
- title: title/subtitle wording or non-typographic title placement only;
- axes: axis/scale/grid/tick/domain only, excluding font/color;
- labels: text/legend wording, binding or placement only, excluding font/color;
- layout: width/height/padding/spacing/autosize/bounds/alignment/composition placement only;
- structure: mark type, analytic data/encoding binding, transforms, sort/order and non-text layers only.

Each claim must be a user-readable, exact before→after statement about only the cited component. Do not claim preservation or confirmation as a change. If an input id has no source→candidate effect at all, return it under `unapplied` with a precise reason; do not put it in `commitments`. JSON only: {"commitments":[{"id":str,"evidence_id":str,"component":str,"claim":str,"before":str,"after":str,"spec_paths":[str]}],"unapplied":[{"id":str,"reason":str}]}""",
                    json.dumps({
                        "source_spec": _compact_for_llm(spec),
                        "candidate_spec": _compact_for_llm(final_spec),
                        "commitments": commitments,
                        "commitments_to_repair": commitments,
                        "validation_errors_by_id": current_rejections,
                        "components_missing_from_current_manifest": missing_components,
                        "source_to_candidate_diff_inventory": inventory,
                    }, ensure_ascii=False),
                    {"commitments": commitments, "unapplied": []},
                )
                repaired_list = repaired.get("commitments") if isinstance(repaired.get("commitments"), list) else commitments
                repair_attempts.append({
                    "attempt": attempt,
                    "input_rejections": current_rejections,
                    "unapplied": repaired.get("unapplied") if isinstance(repaired.get("unapplied"), list) else [],
                    "returned_count": len(repaired_list),
                })
                commitments = repaired_list
            final_valid, final_rejections = _check_commitments(spec, final_spec, commitments)
            commitments = final_valid
        else:
            final_valid, final_rejections = initial_valid, initial_rejections
            commitments = final_valid
        # Program-authored entries are appended after validation: their paths
        # were produced by the detectors themselves, so they need no model
        # attestation, and they must not be dropped by a manifest repair.
        if changed and enforcement_commitments:
            commitments = commitments + enforcement_commitments
        commitment_audit: dict[str, Any] = {
            "ran": bool(changed),
            "initial_rejections": initial_rejections,
            "repair_attempts": repair_attempts,
            "final_rejections": final_rejections,
            "uncovered_components": _missing_manifest_components(inventory, commitments) if changed else [],
            "retained_ids": [str(item.get("id")) for item in commitments],
        }
        b3 = {**b3, "commitments": commitments}
        applied_ids = [str(item.get("id")) for item in commitments if isinstance(item, dict) and item.get("id")] if changed else []
        delivery_state = "ready" if safety["accepted"] else "needs_vega_lite_repair"
        b4 = {"safety": safety, "visual_review": visual_review, "l1_contract_verification": enforcement, "commitment_audit": commitment_audit, "changed": changed, "delivery_state": delivery_state, "applied_commitment_ids": applied_ids}
        return {"version": "advisor-v2", "persona_id": persona.id, "beats": {"beat1": b1, "beat2": evidence, "beat3": b3, "beat4": b4}, "spec": final_spec, "applied_commitment_ids": applied_ids, "llm_errors": llm_errors}
