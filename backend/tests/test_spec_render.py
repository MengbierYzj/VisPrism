"""服务端 VL→PNG（vl-convert）。"""
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
