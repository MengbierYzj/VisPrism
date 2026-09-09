"""Shared Vega-Lite path ownership for advisor manifests and contracts."""
from __future__ import annotations

from typing import Any


SCOPE_PRIORITY = ("color", "typography", "title", "axes", "labels", "layout", "structure")

_APPEARANCE_CHANNELS = {
    "color", "colour", "fill", "fillopacity", "opacity", "palette",
    "stroke", "strokedash", "strokeopacity", "strokewidth",
}
_POSITION_CHANNELS = {
    "x", "x2", "y", "y2", "theta", "theta2", "radius", "radius2",
    "longitude", "longitude2", "latitude", "latitude2",
}
_VIEW_CONTENT_KEYS = {"mark", "encoding", "transform", "data"}


def _decode_parts(path: str) -> tuple[list[str], list[str]]:
    raw = [part for part in str(path or "").strip("/").split("/") if part]
    return raw, [part.replace("~1", "/").replace("~0", "~") for part in raw]


def _value_at_pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    if not isinstance(document, (dict, list)):
        return False, None
    if pointer == "":
        return True, document
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


def _encoding_channel(parts: list[str]) -> str:
    indices = [index for index, part in enumerate(parts[:-1]) if part == "encoding"]
    return parts[indices[-1] + 1] if indices else ""


def _containing_mark_type(path: str, *documents: Any) -> str:
    raw, decoded = _decode_parts(path)
    indices = [index for index, part in enumerate(decoded) if part.lower() in _VIEW_CONTENT_KEYS]
    if not indices:
        return ""
    node_index = indices[-1]
    pointer = "/" + "/".join(raw[:node_index]) if node_index else ""
    for document in documents:
        exists, node = _value_at_pointer(document, pointer)
        if not exists or not isinstance(node, dict):
            continue
        mark = node.get("mark")
        mark_type = str(mark.get("type") or "") if isinstance(mark, dict) else str(mark or "")
        if mark_type:
            return mark_type.lower()
    return ""


def scopes_for_path(path: str, original: Any = None, candidate: Any = None) -> set[str]:
    """Return every legitimate component owner of one RFC-6901 path.

    Scale ownership is channel-aware: an x/y scale is Axes, while a color or
    strokeDash scale is Color. Text-mark context makes position, transform and
    mark construction valid Labels evidence; font and color remain owned by
    Typography and Color.
    """
    _raw, decoded = _decode_parts(path)
    parts = [part.lower() for part in decoded]
    leaf = parts[-1] if parts else ""
    channel = _encoding_channel(parts)
    scopes: set[str] = set()

    appearance_context = (
        channel in _APPEARANCE_CHANNELS
        or any(part in _APPEARANCE_CHANNELS or part.startswith(("stroke", "fill")) for part in parts)
        or leaf.endswith(("color", "colour"))
        or leaf == "background"
        or parts[:2] == ["config", "range"]
    )
    if appearance_context:
        scopes.add("color")

    if any(token in leaf for token in ("font", "fontsize", "fontweight", "fontstyle", "lineheight")):
        scopes.add("typography")

    axis_context = (
        any(part == "axis" or part.startswith("axis") for part in parts)
        or any(part.startswith(("grid", "tick")) for part in parts)
        or channel in _POSITION_CHANNELS
        or ("scale" in parts and not channel and not appearance_context)
    )
    if axis_context:
        scopes.add("axes")

    if not axis_context and "legend" not in parts and any(part in {"title", "subtitle"} for part in parts):
        scopes.add("title")

    if any(part in {"legend", "text", "caption", "source", "annotation", "tooltip"} for part in parts):
        scopes.add("labels")

    layout_context = (
        any(part in {"padding", "autosize"} for part in parts)
        or leaf in {"width", "height", "spacing", "bounds", "align", "columns", "center", "background"}
    )
    if layout_context:
        scopes.add("layout")

    mark_type = _containing_mark_type(path, candidate, original)
    if mark_type == "text" and scopes.isdisjoint({"color", "typography", "title", "layout"}):
        scopes.add("labels")

    if not scopes:
        scopes.add("structure")
    return scopes


def primary_scope(path: str, original: Any = None, candidate: Any = None) -> str:
    scopes = scopes_for_path(path, original, candidate)
    _raw, decoded = _decode_parts(path)
    parts = [part.lower() for part in decoded]
    if (
        "labels" in scopes
        and _containing_mark_type(path, candidate, original) == "text"
        and "axis" not in parts
        and "scale" not in parts
        and scopes.isdisjoint({"color", "typography", "title", "layout"})
    ):
        # A text mark's x/y encoding positions the annotation; it is not the
        # chart axis merely because it uses a positional channel.
        return "labels"
    return next(scope for scope in SCOPE_PRIORITY if scope in scopes)
