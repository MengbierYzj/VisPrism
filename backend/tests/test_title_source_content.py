"""标题/副标题/来源文案落地与数据标签保留。"""
import json
from pathlib import Path

from app.core.actions import (
    _descriptive_title_ops,
    _to_sentence_case,
    apply_ops,
)
from app.core.spec_rebuild import rebuild_spec_for_advisor
from app.core.specfacts import extract_facts
from app.core.view_geometry import walk_annotated_units

ROOT = Path(__file__).resolve().parents[2]
ANIMALS = ROOT / "data" / "dataset" / "09_animals_and_share_of_US_adults" / "chart_spec.json"
FISH = ROOT / "data" / "dataset" / "07_fish_seafood_production" / "chart_spec.json"


def test_animals_keeps_value_labels_and_source_provider():
    raw = json.loads(ANIMALS.read_text(encoding="utf-8"))
    working, report = rebuild_spec_for_advisor(raw)
    roles = [u["role"] for u in walk_annotated_units(working)]
    assert "secondary_data" in roles  # 柱上数值
    facts = extract_facts(working)
    assert facts["has_source_note"] is True
    assert facts.get("source_provider") == "YouGov"
    # 描述性副标题与来源并存
    sub = working.get("title", {}).get("subtitle")
    assert sub
    blob = " ".join(sub) if isinstance(sub, list) else str(sub)
    assert "morally unacceptable" in blob or "Share of" in blob
    assert "YouGov" in blob or "Source" in blob


def test_source_note_does_not_wipe_subtitle():
    spec = {
        "title": {
            "text": "Fish and seafood production",
            "subtitle": "Measured as wild catch plus aquaculture.",
        },
        "mark": "line",
        "encoding": {"x": {"field": "y"}, "y": {"field": "v"}},
    }
    out = apply_ops(spec, [{"action": "set_source_note", "text": "Source: Our World in Data"}])
    sub = out["title"]["subtitle"]
    lines = sub if isinstance(sub, list) else [sub]
    assert any("aquaculture" in str(x) for x in lines)
    assert any("Our World in Data" in str(x) for x in lines)


def test_sentence_case_and_descriptive_fish():
    raw = json.loads(FISH.read_text(encoding="utf-8"))
    working, _ = rebuild_spec_for_advisor(raw)
    facts = extract_facts(working)
    assert facts.get("max_category") and facts["max_category"]["name"] == "China"
    ops = _descriptive_title_ops(facts)
    assert any(o.get("action") == "set_title_text" for o in ops)
    titled = apply_ops(working, ops)
    assert "China" in str(titled["title"]["text"])
    sub = titled["title"].get("subtitle")
    blob = " ".join(sub) if isinstance(sub, list) else str(sub or "")
    assert "Measured as" in blob or "aquaculture" in blob
    assert not blob.lower().startswith("is measured")


def test_animals_title_sentence_case():
    title = "One in Four Americans Say It’s Wrong To Eat an Octopus"
    out = _to_sentence_case(title)
    assert out.startswith("One in")
    assert "four americans say" in out.lower()
    assert out != title
