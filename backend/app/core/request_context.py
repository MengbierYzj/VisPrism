"""Normalization shared by advisor engines, independent of their pipelines."""
from __future__ import annotations

from typing import Any


def make_context(payload: Any) -> dict:
    """Normalize media, goal and optional preview image from an API request."""
    from .visual_review import normalize_preview_image

    ctx = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {}
    if isinstance(ctx.get("medium"), str):
        out["medium"] = ctx["medium"]
    if isinstance(ctx.get("viewport_px"), (int, float)):
        out["viewport_px"] = ctx["viewport_px"]
    goal = ctx.get("communication_goal")
    if not isinstance(goal, str) or not goal.strip():
        goal = ctx.get("user_intent")
    if isinstance(goal, str) and goal.strip():
        out["communication_goal"] = goal.strip()[:2000]
    preview = normalize_preview_image(ctx.get("preview_image"))
    if preview:
        out["preview_image"] = preview
    return out
