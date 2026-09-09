"""服务端 VL→PNG（vl-convert）。"""
import io
import sys

from app.core.spec_render import render_vl_to_png_data_url


def test_render_simple_bar_png():
    spec = {
        "data": {"values": [{"a": "A", "b": 28}, {"a": "B", "b": 55}]},
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
    }
    url, meta = render_vl_to_png_data_url(spec, scale=1)
    assert meta.get("ok") is True
    assert url and url.startswith("data:image/png;base64,")
    assert (meta.get("bytes") or 0) > 100


def test_render_skips_unresolvable_data_url(monkeypatch):
    monkeypatch.setenv("VIZGUIDE_VISION_SERVER_RENDER", "1")
    spec = {
        "data": {"url": "https://example.invalid/no-such.csv"},
        "mark": "bar",
        "encoding": {
            "x": {"field": "a", "type": "nominal"},
            "y": {"field": "b", "type": "quantitative"},
        },
    }
    url, meta = render_vl_to_png_data_url(spec)
    assert url is None
    assert "unresolvable_data_url" in (meta.get("error") or "")


def test_runtime_error_partial_canvas_is_rejected(monkeypatch):
    """vl-convert may return title-only PNG bytes after a Vega runtime error."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (440, 40), "white").save(buffer, format="PNG")

    class PartialRenderer:
        @staticmethod
        def vegalite_to_png(*, vl_spec, scale):
            return buffer.getvalue()

    monkeypatch.setitem(sys.modules, "vl_convert", PartialRenderer)
    spec = {
        "title": "Runtime failure must not look successful",
        "width": 400,
        "height": 300,
        "data": {"values": [{"category": "A", "value": 12}]},
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "category", "type": "nominal"},
                    "y": {"field": "value", "type": "quantitative"},
                },
            },
            {
                "mark": "text",
                "encoding": {
                    "text": {"field": "value", "type": "quantitative", "format": ".0f p"},
                },
            },
        ],
    }
    url, meta = render_vl_to_png_data_url(spec, scale=1)
    assert url is None
    assert meta.get("ok") is False
    assert "rendered_canvas_underflow" in (meta.get("error") or "")
    assert meta.get("height") == 40
