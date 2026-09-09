"""Vega-Lite → PNG（服务端），供拍3 多模态审图使用。

使用 vl-convert（自带 V8 + resvg），不依赖浏览器/Node。
失败时返回 None，视觉审图跳过，不影响四拍主路径。
"""
from __future__ import annotations

import base64
import copy
import io
import json
import time
from typing import Any

from ..config import settings

_DEFAULT_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
_RENDER_ATTEMPTS = 3
_RENDER_RETRY_DELAY_S = 0.2
_RENDER_DIMENSION_FLOOR_RATIO = 0.5


def _largest_explicit_view_dimensions(spec: dict) -> tuple[float | None, float | None]:
    """Return conservative canvas floors from numeric view dimensions.

    ``vl-convert`` can log a Vega runtime error yet return a partial PNG. A
    composition root often has no height of its own, so inspect all children
    and use the largest declared view rather than trusting PNG bytes alone.
    """
    widths: list[float] = []
    heights: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            width = node.get("width")
            height = node.get("height")
            if isinstance(width, (int, float)) and not isinstance(width, bool) and width > 0:
                widths.append(float(width))
            if isinstance(height, (int, float)) and not isinstance(height, bool) and height > 0:
                heights.append(float(height))
            # Follow only Vega-Lite view composition. Traversing arbitrary
            # dictionaries would mistake data rows named width/height for
            # canvas declarations.
            for key in ("layer", "vconcat", "hconcat", "concat"):
                children = node.get(key)
                if isinstance(children, list):
                    for child in children:
                        walk(child)
            child_spec = node.get("spec")
            if isinstance(child_spec, dict):
                walk(child_spec)

    walk(spec)
    return (max(widths) if widths else None, max(heights) if heights else None)


def _prepare_spec(spec: dict) -> dict:
    """浅清洗：补 schema；去掉易导致本地渲染失败的远程 data.url（无 values 时）。"""
    out = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    if "$schema" not in out:
        out["$schema"] = _DEFAULT_SCHEMA

    def _scrub_data(node: Any) -> None:
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict):
                url = data.get("url")
                if isinstance(url, str) and url.strip() and "values" not in data:
                    # 无内嵌 values 的远程/相对 url：vl-convert 常无法拉取 → 标记失败由上层跳过
                    node["_vizguide_unresolvable_data_url"] = url
            for v in node.values():
                _scrub_data(v)
        elif isinstance(node, list):
            for v in node:
                _scrub_data(v)

    _scrub_data(out)
    return out


_FONT_KEYS = ("font", "labelFont", "titleFont", "subtitleFont", "tickBandFont")
# 没装的字体在浏览器里会回退到同类字体，在这里却会让整段文字消失，所以按 CSS 惯例
# 各留一条同风格的兜底链。
_FALLBACK_STACKS = {
    "serif": ("Georgia", "Times New Roman", "Times", "DejaVu Serif"),
    "sans": ("Helvetica", "Arial", "Helvetica Neue", "DejaVu Sans"),
    "mono": ("Menlo", "Courier New", "DejaVu Sans Mono"),
}
_SERIF_HINTS = ("serif", "georgia", "times", "garamond", "book", "palatino", "cambria")
_MONO_HINTS = ("mono", "courier", "consolas", "menlo")
_font_probe_cache: dict[str, bool] = {}


def _font_draws_text(family: str) -> bool:
    """Ask the renderer itself whether it can draw glyphs in this family.

    resvg drops text in a family it cannot resolve instead of substituting one,
    so a chart in an uninstalled font renders with every title, axis label and
    legend entry silently missing. There is no font-listing API to consult, so
    the only reliable check is to draw one glyph and look for ink.
    """
    cached = _font_probe_cache.get(family)
    if cached is not None:
        return cached
    probe = {
        "$schema": _DEFAULT_SCHEMA,
        "data": {"values": [{"a": 1}]},
        "mark": {"type": "text", "text": "Ag", "fontSize": 48, "font": family, "color": "black"},
        "width": 80,
        "height": 60,
        "config": {"view": {"stroke": None}},
    }
    try:
        import vl_convert as vlc
        from PIL import Image

        png = vlc.vegalite_to_png(vl_spec=json.dumps(probe), scale=1.0)
        with Image.open(io.BytesIO(png)) as image:
            grey = image.convert("L")
            drew = (grey.getextrema()[0] if grey.getextrema() else 255) < 200
    except Exception:  # noqa: BLE001 — 探测本身失败时按可用处理，且不写缓存，
        # 否则 vl-convert 的偶发抖动会把一个真正缺失的字体永久记成可用。
        return True
    _font_probe_cache[family] = drew
    return drew


def _resolve_font(requested: str) -> str | None:
    """Pick a family the renderer can actually draw, honouring the CSS stack."""
    candidates = [part.strip().strip("'\"") for part in requested.split(",")]
    candidates = [part for part in candidates if part]
    lowered = requested.lower()
    if any(hint in lowered for hint in _MONO_HINTS):
        style = "mono"
    elif any(hint in lowered for hint in _SERIF_HINTS):
        style = "serif"
    else:
        style = "sans"
    for candidate in candidates + list(_FALLBACK_STACKS[style]):
        if candidate.lower() in ("serif", "sans-serif", "monospace"):
            continue
        if _font_draws_text(candidate):
            return candidate
    return None


def _substitute_unavailable_fonts(spec: dict) -> dict[str, str]:
    """Swap fonts the renderer cannot draw; the delivered spec keeps its own."""
    substitutions: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in _FONT_KEYS:
                requested = node.get(key)
                if not isinstance(requested, str) or not requested.strip():
                    continue
                if _font_draws_text(requested):
                    continue
                replacement = _resolve_font(requested)
                if replacement and replacement != requested:
                    node[key] = replacement
                    substitutions[requested] = replacement
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(spec)
    return substitutions


def _has_unresolvable_data_url(spec: dict) -> str | None:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("_vizguide_unresolvable_data_url"):
                found.append(str(node["_vizguide_unresolvable_data_url"]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    return found[0] if found else None


def render_vl_to_png_data_url(
    spec: dict,
    *,
    scale: float | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """将 VL spec 渲染为 PNG data URL。

    返回 (data_url|None, meta)。meta 含 ok / error / bytes / ms / scale。
    """
    meta: dict[str, Any] = {"ok": False, "source": "server_render"}
    if not isinstance(spec, dict) or not spec:
        meta["error"] = "empty_spec"
        return None, meta
    if not settings.vision_server_render:
        meta["error"] = "server_render_disabled"
        return None, meta

    prepared = _prepare_spec(spec)
    bad_url = _has_unresolvable_data_url(prepared)
    if bad_url:
        meta["error"] = f"unresolvable_data_url:{bad_url[:120]}"
        return None, meta

    # 去掉内部标记，避免进 VL 编译
    def _strip_markers(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("_vizguide_unresolvable_data_url", None)
            for v in node.values():
                _strip_markers(v)
        elif isinstance(node, list):
            for v in node:
                _strip_markers(v)

    _strip_markers(prepared)
    font_substitutions = _substitute_unavailable_fonts(prepared)
    if font_substitutions:
        meta["font_substitutions"] = font_substitutions

    use_scale = float(scale if scale is not None else settings.vl_render_scale)
    use_scale = min(max(use_scale, 0.5), 2.0)
    meta["scale"] = use_scale

    started = time.perf_counter()
    # vl-convert 偶发非确定性失败（内嵌 V8 运行时在并发/连续调用下可能抛错），
    # 而这类失败会让上层误判为「候选图不可渲染」并跳过验收闸门。真正的 spec
    # 错误在重试下会稳定复现，因此重试只吸收抖动，不会放行坏 spec。
    payload = json.dumps(prepared, ensure_ascii=False)
    png: bytes | None = None
    last_error: str | None = None
    for attempt in range(1, _RENDER_ATTEMPTS + 1):
        try:
            import vl_convert as vlc

            png = vlc.vegalite_to_png(vl_spec=payload, scale=use_scale)
            last_error = None
            meta["attempts"] = attempt
            break
        except ModuleNotFoundError as exc:
            # 缺依赖是确定性的，重试无意义；上层据此标记 render_unverified。
            meta["error"] = f"{type(exc).__name__}: {exc}"
            meta["ms"] = round((time.perf_counter() - started) * 1000, 1)
            meta["attempts"] = attempt
            return None, meta
        except Exception as exc:  # noqa: BLE001 — 渲染失败不拖垮顾问
            last_error = f"{type(exc).__name__}: {exc}"
            meta["attempts"] = attempt
            if attempt < _RENDER_ATTEMPTS:
                time.sleep(_RENDER_RETRY_DELAY_S * attempt)

    if png is None:
        meta["error"] = last_error or "render_failed"
        meta["ms"] = round((time.perf_counter() - started) * 1000, 1)
        return None, meta

    meta["ms"] = round((time.perf_counter() - started) * 1000, 1)
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
        meta["error"] = "invalid_png"
        return None, meta

    b64 = base64.b64encode(png).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"
    if len(data_url) > settings.preview_image_max_chars:
        meta["error"] = f"png_too_large:{len(data_url)}"
        meta["bytes"] = len(png)
        return None, meta

    meta.update({"bytes": len(png), "chars": len(data_url)})
    # 画布实际尺寸是判断「版式是否失控」的直接证据（例如像素坐标被误当数据值，
    # 会把画布横向拽出几倍宽），因此随渲染结果一起返回。
    try:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            meta["width"], meta["height"] = image.width, image.height
    except Exception:  # noqa: BLE001 — 取不到尺寸不影响渲染结果本身
        pass

    declared_width, declared_height = _largest_explicit_view_dimensions(prepared)
    actual_width = meta.get("width")
    actual_height = meta.get("height")
    underflow: list[str] = []
    if (
        declared_width is not None
        and isinstance(actual_width, (int, float))
        and actual_width < declared_width * use_scale * _RENDER_DIMENSION_FLOOR_RATIO
    ):
        underflow.append(f"width {actual_width} < declared floor {declared_width:g}")
    if (
        declared_height is not None
        and isinstance(actual_height, (int, float))
        and actual_height < declared_height * use_scale * _RENDER_DIMENSION_FLOOR_RATIO
    ):
        underflow.append(f"height {actual_height} < declared floor {declared_height:g}")
    if underflow:
        meta["error"] = "rendered_canvas_underflow: " + "; ".join(underflow)
        return None, meta

    meta["ok"] = True
    return data_url, meta
