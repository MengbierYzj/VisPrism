from app.config import settings
from app.core.persona import PersonaRegistry
from app.core.visual_review import strategy_escalations_from_findings


def test_editorial_personas_inherit_and_choose_different_visual_actions():
    registry = PersonaRegistry(settings.data_dir, settings.storage_dir / "personas")
    bbc = registry.get("bbc-editorial")
    economist = registry.get("economist-editorial")
    assert bbc and economist
    assert bbc.resolve_color("{color.bbc-blue}") == "#1380A1"
    facts = {"axis_x_dense": True, "mark_type": "line"}
    meta = {"findings": [{"issue": "overlap", "verdict": "adopt", "rationale": "dense dates"}]}
    bbc_ops = strategy_escalations_from_findings(bbc, facts, meta)[0]["compiled"]["ops"]
    economist_ops = strategy_escalations_from_findings(economist, facts, meta)[0]["compiled"]["ops"]
    assert any(o.get("action") == "set_axis" for o in bbc_ops)
    assert any(o.get("action") == "thin_axis_labels" for o in economist_ops)
    assert bbc_ops != economist_ops
