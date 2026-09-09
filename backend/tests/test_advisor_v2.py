import asyncio
import base64
import io
import json
from pathlib import Path

from app.advisor_v2 import AdvisorV2
from app.advisor_v2.replay import list_records, load_record, start_replay_run
from app.advisor_v2.runner import (
    V2AgentState,
    V2RunState,
    V2RunStore,
    _agent_task,
    _component_changes,
    _evidence_for,
    _evidence_index,
    _proposal,
    wait_run_v2,
)
from app.advisor_v2.service import (
    _as_json_object,
    _check_commitments,
    _l1_contract,
    _l2_contract,
    _layout_risks,
    _new_layout_risks,
    _merge_text_changes,
    _render_integrity_error,
    _repair_datum_value_confusion,
    _repair_structural_defects,
    _safe_candidate,
    _strip_interactive_params,
    _verify_l1_contract,
)
from app.core.spec_render import _substitute_unavailable_fonts
from app.core.persona import Adaptation, Persona, Philosophy, Rule, Story
from app.core.semantic_composer import PRIMARY_DATA_REF, restore_primary_data
from app.core.specfacts import extract_facts
from app.config import settings
from app.llm_log import LLMRunLog


class _LLM:
    def __init__(self):
        self.vision_images = []

    async def chat_json(self, system, user):
        if "repairing the user-facing change manifest" in system:
            return {"commitments": json.loads(user)["commitments"], "rejected": []}
        if "Beat 3" in system:
            return {
                "story": "Rebuild the chart with a dark editorial background.",
                "commitments": [{"id": "c1", "evidence_id": "L3:clarity", "component": "color", "claim": "Changed the canvas from the source default to a dark editorial background.", "before": "No explicit canvas background.", "after": "Canvas background is #111111.", "spec_paths": ["/background"]}],
                "text_changes": [],
                "candidate_spec": {
                    "data": {"values": [{"city": "A", "period": "now", "v": 3}]},
                    "mark": "bar",
                    "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}},
                    "background": "#111111",
                },
            }
        if "Beat 1" in system:
            return {"story": "compare", "audience": "public", "data_roles": [], "risks": []}
        raise AssertionError("Beat 4 must not make a design call")

    async def chat_json_vision(self, system, user, images, **kwargs):
        self.vision_images = images
        if "final acceptance gate" in system:
            return {"verdict": "pass", "findings": [], "intent_assessment": {"focus": "chart topic", "comparison": "better", "reason": "clearer", "original_evidence": "crowded", "revised_evidence": "clear"}}
        candidate = json.loads(user)["candidate_spec"]
        return {"verdict": "pass", "findings": [], "intent_assessment": {"focus": "chart topic", "comparison": "better", "reason": "clearer", "original_evidence": "crowded", "revised_evidence": "clear"}, "commitments": [], "text_changes": [], "revised_spec": candidate}


def test_clean_room_v2_accepts_full_llm_reconstruction():
    persona = Persona(id="p", name="P")
    spec = {
        "data": {"values": [{"city": "A", "period": "now", "v": 3}]},
        "mark": "bar",
        "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}},
    }
    llm = _LLM()
    result = asyncio.run(AdvisorV2(llm).advise(persona, spec))
    assert result["version"] == "advisor-v2"
    assert set(result["beats"]) == {"beat1", "beat2", "beat3", "beat4"}
    assert result["spec"]["background"] == "#111111"
    assert result["applied_commitment_ids"] == ["c1"]
    assert len(llm.vision_images) == 2
    assert result["beats"]["beat4"]["visual_review"]["intent_assessment"]["comparison"] == "better"


def test_v2_adapter_keeps_frontend_change_contract_and_llm_failure_is_nonfatal():
    class FailingLLM:
        async def chat_json(self, system, user):
            raise RuntimeError("temporary gateway failure")

    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"a": "A", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    result = asyncio.run(AdvisorV2(FailingLLM()).advise(persona, spec))
    proposal = _proposal(persona, spec, result, 1)
    assert proposal["modified_spec"] == spec
    assert proposal["llm_errors"]


def test_commitment_audit_rejects_unchanged_or_missing_component_claims():
    source = {"mark": "bar", "background": "#fff"}
    candidate = {"mark": "bar", "background": "#111"}
    valid, rejected = _check_commitments(source, candidate, [
        {"id": "good", "component": "color", "claim": "Changed the canvas background to dark navy.", "before": "white", "after": "#111", "spec_paths": ["/background"]},
        {"id": "bad", "component": "layout", "claim": "Padding was preserved.", "before": "20", "after": "same 20", "spec_paths": ["/mark"]},
    ])
    assert [item["id"] for item in valid] == ["good"]
    assert rejected[0]["id"] == "bad"


def test_commitment_audit_enforces_component_ownership_and_no_path_overlap():
    source = {"mark": "bar", "background": "#fff", "title": {"text": "Old", "fontSize": 16}}
    candidate = {"mark": "bar", "background": "#111", "title": {"text": "New", "fontSize": 22}}
    valid, rejected = _check_commitments(source, candidate, [
        {"id": "title", "component": "title", "claim": "Changed title wording from Old to New.", "before": "Old", "after": "New", "spec_paths": ["/title/text"]},
        {"id": "type", "component": "typography", "claim": "Raised title font size from 16 to 22.", "before": "16", "after": "22", "spec_paths": ["/title/fontSize"]},
        {"id": "bad-owner", "component": "labels", "claim": "Changed a label colour.", "before": "white", "after": "black", "spec_paths": ["/background"]},
        {"id": "duplicate", "component": "title", "claim": "Changed title wording again.", "before": "Old", "after": "New", "spec_paths": ["/title/text"]},
    ])
    assert [item["id"] for item in valid] == ["title", "type"]
    assert {item["id"] for item in rejected} == {"bad-owner", "duplicate"}


def test_commitment_audit_accepts_atomic_palette_arrays_and_nested_layout_values():
    source = {"mark": "arc", "width": 400, "encoding": {"color": {"field": "Category", "scale": {"range": ["#aaa", "#bbb"]}}}}
    candidate = {"mark": "arc", "width": 400, "hconcat": [{"width": 260}], "encoding": {"color": {"field": "Category", "scale": {"range": ["#141F52", "#36E2BD"]}}}}
    valid, rejected = _check_commitments(source, candidate, [
        {"id": "palette", "component": "color", "claim": "Changed the category palette to deep blue and light blue.", "before": "grey range", "after": "blue range", "spec_paths": ["/encoding/color/scale/range"]},
        {"id": "panel-width", "component": "layout", "claim": "Set the first panel width to 260.", "before": "no panel width", "after": "260", "spec_paths": ["/hconcat/0/width"]},
    ])
    assert [item["id"] for item in valid] == ["palette", "panel-width"]
    assert rejected == []


def test_commitment_audit_repairs_invalid_manifest_instead_of_erasing_changes():
    class RepairingLLM(_LLM):
        async def chat_json(self, system, user):
            if "repairing the user-facing change manifest" in system:
                return {
                    "commitments": [{
                        "id": "c1", "evidence_id": "L3:clarity", "component": "color",
                        "claim": "Changed the canvas background from the source default to #111111.",
                        "before": "No explicit canvas background.", "after": "Canvas background is #111111.",
                        "spec_paths": ["/background"],
                    }],
                    "unapplied": [],
                }
            if "Beat 3" in system:
                result = await super().chat_json(system, user)
                result["commitments"] = [{
                    "id": "c1", "evidence_id": "L3:clarity", "component": "color|layout",
                    "claim": "Confirmed the dark background and layout.", "before": "source", "after": "same",
                    "spec_paths": ["/candidate_spec/background"],
                }]
                return result
            return await super().chat_json(system, user)

    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city"}, "y": {"field": "v"}}}
    result = asyncio.run(AdvisorV2(RepairingLLM()).advise(persona, spec))
    assert result["applied_commitment_ids"] == ["c1"]
    audit = result["beats"]["beat4"]["commitment_audit"]
    assert audit["initial_rejections"]
    assert audit["repair_attempts"]


def test_commitment_manifest_is_rebuilt_when_beat3_returns_no_commitments():
    class ManifestLLM(_LLM):
        async def chat_json(self, system, user):
            if "repairing the user-facing change manifest" in system:
                return {"commitments": [
                    {"id": "colour", "evidence_id": "L1:palette", "component": "color", "claim": "Changed the canvas background from the source default to #111111.", "before": "No explicit background.", "after": "Canvas background is #111111.", "spec_paths": ["/background"]},
                    {"id": "headline", "evidence_id": "L3:narrative", "component": "title", "claim": "Changed the title from the generic source heading to a message-led headline.", "before": "Original title.", "after": "A clearer title.", "spec_paths": ["/title"]},
                    {"id": "type", "evidence_id": "L1:type", "component": "typography", "claim": "Changed the title typeface from the source default to BBC Reith.", "before": "No title font declaration.", "after": "Title font is BBC Reith.", "spec_paths": ["/config/title/font"]},
                ], "unapplied": []}
            if "Beat 3" in system:
                result = await super().chat_json(system, user)
                result["commitments"] = []
                result["candidate_spec"] = {
                    **result["candidate_spec"], "title": "A clearer title",
                    "config": {"title": {"font": "BBC Reith"}},
                }
                return result
            return await super().chat_json(system, user)

    persona = Persona(id="p", name="P")
    spec = {"title": "Original title.", "data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city"}, "y": {"field": "v"}}}
    result = asyncio.run(AdvisorV2(ManifestLLM()).advise(persona, spec))
    assert set(result["applied_commitment_ids"]) == {"colour", "headline", "type"}
    assert result["beats"]["beat4"]["commitment_audit"]["ran"] is True


def test_v2_adapter_exposes_recomposable_component_deltas_not_duplicate_specs():
    persona = Persona(id="bbc", name="BBC")
    source = {"title": "Original", "mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "title": "A clearer title", "background": "#ffffff", "config": {"axis": {"labelFont": "BBC Reith"}}}
    rows = _component_changes(persona, source, candidate, [{"claim": "Use a concise title."}])
    assert {row["scope"] for row in rows} == {"title", "color", "typography"}
    assert all(row["id"].startswith("bbc:v2:") for row in rows)
    assert all(row["ops"][0]["action"] == "compose_component" for row in rows)
    # 卡片挂的是主数据占位符而非整表副本：组装时按源图还原，必须逐字复原候选图。
    assert all(row["ops"][0]["candidate_spec"]["data"] == {"$ref": PRIMARY_DATA_REF} for row in rows)
    assert all(restore_primary_data(source, row["ops"][0]["candidate_spec"]) == candidate for row in rows)


def test_v2_proposal_does_not_copy_one_full_spec_to_every_commitment():
    persona = Persona(id="bbc", name="BBC")
    source = {"mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    result = {
        "spec": {**source, "background": "#111111", "title": "BBC framing"},
        "applied_commitment_ids": ["c1", "c2"],
        "beats": {"beat3": {"commitments": [{"id": "c1", "claim": "Set the editorial background."}, {"id": "c2", "claim": "Tighten the title."}]}, "beat4": {"safety": {"accepted": True}}},
    }
    proposal = _proposal(persona, source, result, 1)
    assert {change["scope"] for change in proposal["changes"]} == {"color", "title"}
    assert all(change["id"].startswith("bbc:v2:") for change in proposal["changes"])
    assert all(op["action"] == "compose_component" for change in proposal["changes"] for op in change["ops"])
    assert all(set(op["bundle"]["change_ids"]) == {change["id"] for change in proposal["changes"]} for change in proposal["changes"] for op in change["ops"])


def test_v2_structural_candidate_never_invents_a_whole_chart_structure_card():
    persona = Persona(id="bbc", name="BBC")
    source = {"mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {"vconcat": [{**source}, {"mark": "text", "data": {"values": [{"label": "Note"}]}, "encoding": {"text": {"field": "label"}}}]}
    rows = _component_changes(persona, source, candidate, [])
    assert rows == []


def test_vconcat_color_diff_is_carded_even_without_a_color_commitment():
    """Gallery charts can recolor bars inside vconcat while Beat 3 only names layout."""
    persona = Persona(id="bbc", name="BBC")
    source = {
        "title": {"text": "Waste", "color": "#2d2e2d"},
        "vconcat": [{
            "mark": {"type": "bar", "color": "#168c96"},
            "encoding": {"y": {"field": "Country"}, "x": {"field": "v"}},
            "data": {"values": [{"Country": "US", "v": 1}]},
        }],
    }
    candidate = {
        **source,
        "vconcat": [{
            **source["vconcat"][0],
            "height": 400,
            "mark": {"type": "bar"},
            "encoding": {
                **source["vconcat"][0]["encoding"],
                "color": {"value": "#1380A1"},
            },
        }],
    }
    rows = _component_changes(persona, source, candidate, [
        {"id": "canvas", "component": "layout", "claim": "Use a 640 digital canvas.", "spec_paths": ["/vconcat/0/height"]},
    ])
    scopes = {row["scope"] for row in rows}
    assert "layout" in scopes
    assert "color" in scopes
    color = next(row for row in rows if row["scope"] == "color")
    assert any("/color" in path or path.endswith("/color") or "/encoding/color" in path for path in color["component_detail"]["spec_paths"])
    assert color["ops"][0]["spec_paths"]


def test_v2_structural_candidate_keeps_llm_component_manifest():
    persona = Persona(id="bbc", name="BBC")
    source = {"mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {"vconcat": [{**source}, {"mark": "text", "data": {"values": [{"note": "Source"}]}, "encoding": {"text": {"field": "note"}}}]}
    commitments = [
        {"id": "headline", "evidence_id": "L3-narrative", "component": "title", "claim": "Reframed the headline from a generic label to the central comparison.", "before": "generic title", "after": "message-led headline", "spec_paths": ["/title/text"]},
        {"id": "caption", "evidence_id": "L2-source", "component": "labels", "claim": "Moved the source into a dedicated caption region below the plot.", "before": "overlaid source", "after": "separate caption", "spec_paths": ["/vconcat/1"]},
    ]
    rows = _component_changes(persona, source, candidate, commitments)
    assert [row["scope"] for row in rows] == ["title", "labels"]
    assert all(row["ops"][0]["action"] == "compose_component" for row in rows)


def test_invalid_visual_revision_keeps_the_safe_beat3_candidate():
    class InvalidVisionLLM(_LLM):
        async def chat_json_vision(self, system, user, images, **kwargs):
            if "final acceptance gate" in system:
                return {"verdict": "pass", "findings": [], "intent_assessment": {"comparison": "better"}}
            return {"verdict": "revise", "findings": [], "commitments": [], "text_changes": [], "revised_spec": {"mark": "bar"}}

    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    result = asyncio.run(AdvisorV2(InvalidVisionLLM()).advise(persona, spec))
    assert result["spec"]["background"] == "#111111"
    review = result["beats"]["beat4"]["visual_review"]
    assert review["revision_accepted"] is False and review["revision_rejected_errors"]


def test_visual_acceptance_failure_keeps_the_last_safe_generated_candidate():
    class RejectedVisionLLM(_LLM):
        async def chat_json_vision(self, system, user, images, **kwargs):
            candidate = json.loads(user).get("candidate_spec", {})
            if "final acceptance gate" in system:
                return {
                    "verdict": "revise",
                    "findings": [{"issue": "caption overlaps plot", "severity": "high"}],
                    "intent_assessment": {"comparison": "worse"},
                }
            return {"verdict": "pass", "findings": [], "intent_assessment": {"comparison": "better"}, "commitments": [], "text_changes": [], "revised_spec": candidate}

    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    result = asyncio.run(AdvisorV2(RejectedVisionLLM()).advise(persona, spec))
    assert result["spec"]["background"] == "#111111"
    assert result["beats"]["beat4"]["visual_review"]["delivered_despite_visual_rejection"] is True
    assert result["beats"]["beat4"]["visual_review"]["acceptance"]["accepted"] is False


def test_failed_acceptance_is_reworked_and_rechecked_before_shipping():
    class ReworkVisionLLM(_LLM):
        def __init__(self):
            super().__init__()
            self.acceptance_calls = 0

        async def chat_json_vision(self, system, user, images, **kwargs):
            if "final acceptance gate" in system:
                self.acceptance_calls += 1
                if self.acceptance_calls > 1:
                    return {"verdict": "pass", "findings": [], "intent_assessment": {"comparison": "better"}}
                return {"verdict": "revise", "findings": [{"issue": "blank canvas", "severity": "high"}], "intent_assessment": {"comparison": "worse"}}
            if "has been RETURNED" in system:
                candidate = json.loads(user)["rejected_candidate_spec"]
                return {"story": "Repair the composition.", "commitments": [{"id": "repair", "evidence_id": "L3", "claim": "Repair canvas composition."}], "text_changes": [], "candidate_spec": {**candidate, "background": "#225577"}}
            return await super().chat_json_vision(system, user, images, **kwargs)

    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    result = asyncio.run(AdvisorV2(ReworkVisionLLM()).advise(persona, spec))
    assert result["spec"]["background"] == "#225577"
    rework = result["beats"]["beat4"]["visual_review"]["return_rework"]
    assert rework["attempted"] is True and rework["max_attempts"] == 1
    assert rework["attempts"][0]["acceptance"]["accepted"] is True


def test_safety_gate_rejects_data_loss_and_undeclared_text_rewrite():
    source = {"title": "Original title", "data": {"values": [{"a": "A", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    invalid = {"title": "New title", "data": {"values": [{"a": "A", "v": 2}]}, "mark": "bar", "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    final_spec, report = _safe_candidate(source, invalid, [])
    assert final_spec == source
    assert not report["accepted"]
    assert any("data source" in err for err in report["errors"])
    assert any("required text" in err for err in report["errors"])


def test_safety_gate_normalises_single_text_change_object_and_keeps_it_through_repair():
    source = {"title": "Original title", "data": {"values": [{"a": "A", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "a", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    candidate = {**source, "title": "A clearer title"}
    single_object = {"before": "Original title", "after": "A clearer title", "reason": "Clarify the message."}
    checked, report = _safe_candidate(source, candidate, single_object)
    assert report["accepted"] and checked["title"] == "A clearer title"
    assert _merge_text_changes(single_object, []) == [single_object]


def test_uniform_renderer_png_is_a_code_failure_not_a_successful_chart():
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), "white").save(buffer, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    assert _render_integrity_error(image)


def test_beat2_makes_l1_binding_and_evaluates_l2_triggers():
    persona = Persona(
        id="p",
        name="P",
        tokens={"color": {"primary": "#123456"}},
        rules=[Rule(id="l1-colour", rule="Use the institutional primary colour", strength="must", story="story")],
        adaptations=[
            Adaptation(id="l2-two-series", when={"series_count": 2}, then={"set": "color.range", "to": ["#123456", "#abcdef"]}),
            Adaptation(id="l2-semantic", when={"intent": "comparison"}, then={"prefer": "chart.type", "to": "bar"}),
        ],
    )
    spec = {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "c", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    l1 = _l1_contract(persona, spec, {})
    assert l1[0]["rule_id"] == "l1-colour"
    # A rule with no programmatic detector cannot be judged against the source
    # chart, and the contract must say so rather than imply compliance.
    assert l1[0]["source_compliance"] == "not_machine_checkable"
    l2 = _l2_contract(persona, {"series_count": 2})
    assert [item["rule_id"] for item in l2["triggered"]] == ["l2-two-series"]
    assert [item["rule_id"] for item in l2["requires_persona_judgment"]] == ["l2-semantic"]


def test_l1_contract_reports_source_violations_detected_by_the_fast_lane():
    """A programmatic rule the source chart breaks must reach Beat 3 as evidence."""
    persona = Persona(
        id="p",
        name="P",
        tokens={"color": {"primary": "#123456"}},
        rules=[Rule(id="l1-bg", rule="Charts sit on the institutional canvas", strength="must",
                    check="programmatic", story="story", raw={"then": {"set": "chart.background", "to": "#ffeedd"}})],
    )
    spec = {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "c", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    entry = _l1_contract(persona, spec, extract_facts(spec))[0]
    assert entry["source_compliance"] == "violated_by_source_chart"
    assert entry["violation_detail"]


def test_beat4_verifies_l1_invariants_against_the_generated_chart():
    """The generated spec is re-checked by the detectors that built the contract."""
    persona = Persona(
        id="p",
        name="P",
        tokens={"color": {"primary": "#123456"}},
        rules=[Rule(id="l1-bg", rule="Charts sit on the institutional canvas", strength="must",
                    check="programmatic", story="story", raw={"then": {"set": "chart.background", "to": "#ffeedd"}})],
    )
    source = {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "c", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    generated = {**source, "title": "Generated"}
    final, report = _verify_l1_contract(persona, source, generated, [], None)
    assert report["mode"] == "patch"
    assert "l1-bg" in report["patched"]
    assert final["background"] == "#ffeedd"
    assert report["unmet"] == []


def test_l1_enforcement_can_be_disabled_for_ablation(monkeypatch):
    """`off` leaves the LLM chart untouched but still records the verdict."""
    monkeypatch.setenv("VIZGUIDE_V2_L1_ENFORCEMENT", "off")
    persona = Persona(
        id="p",
        name="P",
        tokens={"color": {"primary": "#123456"}},
        rules=[Rule(id="l1-bg", rule="Charts sit on the institutional canvas", strength="must",
                    check="programmatic", story="story", raw={"then": {"set": "chart.background", "to": "#ffeedd"}})],
    )
    source = {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "c", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    final, report = _verify_l1_contract(persona, source, source, [], None)
    assert report["ran"] is False and final == source
    assert report["unmet"] == ["l1-bg"]


def test_explicit_user_goal_is_a_generation_and_visual_review_contract():
    class GoalLLM(_LLM):
        def __init__(self):
            super().__init__()
            self.systems = []

        async def chat_json(self, system, user):
            self.systems.append(system)
            return await super().chat_json(system, user)

        async def chat_json_vision(self, system, user, images, **kwargs):
            self.systems.append(system)
            return await super().chat_json_vision(system, user, images, **kwargs)

    goal = "Emphasise that solved cases remain very low despite the overall trend."
    spec = {"data": {"values": [{"city": "A", "period": "now", "v": 3}]}, "mark": "bar", "encoding": {"x": {"field": "city", "type": "nominal"}, "y": {"field": "v", "type": "quantitative"}}}
    llm = GoalLLM()
    asyncio.run(AdvisorV2(llm).advise(Persona(id="p", name="P"), spec, {"communication_goal": goal}))
    assert any(goal in system and "Task contract" in system for system in llm.systems)
    assert any(goal in system and "visual editorial critic" in system for system in llm.systems)


def test_v2_stops_a_persona_when_a_visible_stage_exceeds_its_timeout(monkeypatch):
    class HungLLM:
        async def chat_json(self, system, user):
            await asyncio.sleep(5)

    monkeypatch.setenv("VIZGUIDE_ADVISOR_STAGE_TIMEOUT_SECONDS", "1")
    persona = Persona(id="p", name="P")
    spec = {"data": {"values": [{"a": "A", "v": 1}]}, "mark": "bar", "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    run = V2RunState("timeout-test", spec, {}, {"p": V2AgentState("p")}, ["p"], "now", llm_log=LLMRunLog("timeout-test"))
    asyncio.run(_agent_task(run, persona, HungLLM()))
    assert run.agents["p"].status == "error"
    assert "超过 1 秒" in run.agents["p"].error


# ---------------------------------------------------------------------------
# 历史 run 的留痕与回放
# ---------------------------------------------------------------------------

def _write_run_file(directory: Path, run_id: str, *, engine: str, metadata_line: bool, personas: list[str]) -> dict:
    document = {
        "engine": engine,
        "run_id": run_id,
        "status": "done",
        "created_at": "2026-08-14T12:00:00+00:00",
        "request": {
            "spec": {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar", "title": "Stored chart"},
            "persona_ids": personas,
            "context": {"communication_goal": "show the gap"},
        },
        "agents": [
            {"persona_id": pid, "status": "done", "progress": 1.0, "error": None,
             "proposal": {"persona_id": pid, "modified_spec": {"background": f"#{i}{i}{i}{i}{i}{i}"}, "invariants": [{"rule_id": "s-source", "ok": True, "detail": ""}]}}
            for i, pid in enumerate(personas, start=1)
        ],
    }
    path = directory / f"{run_id}.json"
    with path.open("w", encoding="utf-8") as handle:
        if metadata_line:
            handle.write(json.dumps({"engine": engine, "run_id": run_id}) + "\n")
        json.dump(document, handle, ensure_ascii=False)
    return document


def test_stored_runs_from_both_engines_are_listed_and_loadable(tmp_path, monkeypatch):
    """两个引擎的快照结构一致，回放不应挑引擎。"""
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    _write_run_file(runs_dir, "v2-0001", engine="advisor-v2", metadata_line=True, personas=["bbc"])
    _write_run_file(runs_dir, "0002", engine="advisor-v1", metadata_line=False, personas=["bbc", "economist"])

    listed = {item["run_id"]: item for item in list_records()}
    assert set(listed) == {"v2-0001", "0002"}
    assert listed["v2-0001"]["engine"] == "advisor-v2"
    assert listed["0002"]["replayable_persona_ids"] == ["bbc", "economist"]
    assert listed["0002"]["communication_goal"] == "show the gap"
    assert listed["v2-0001"]["chart_title"] == "Stored chart"
    assert load_record("v2-0001")[0]["run_id"] == "v2-0001"


def test_replay_reproduces_the_recorded_proposals_without_an_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    document = _write_run_file(runs_dir, "v2-0001", engine="advisor-v2", metadata_line=True, personas=["bbc", "economist"])

    async def replay():
        store = V2RunStore()
        run, error = start_replay_run(store, "v2-0001", beat_delay_ms=0)
        assert error == "" and run is not None
        await wait_run_v2(run)
        return run

    run = asyncio.run(replay())
    assert run.status == "done"
    assert run.replay_of == "v2-0001"
    assert run.payload()["replay_of"] == "v2-0001"
    # 复现必须逐字一致，且请求上下文取自记录本身
    for agent in document["agents"]:
        assert run.agents[agent["persona_id"]].proposal == agent["proposal"]
    assert run.context["communication_goal"] == "show the gap"
    # 只读复现：不得新增或覆盖任何记录文件
    assert {path.name for path in runs_dir.iterdir()} == {"v2-0001.json"}


def test_a_replay_carries_the_original_chart_so_the_ui_can_rebuild_the_session(tmp_path, monkeypatch):
    """前端复现时手里没有当初那张原图，只能从 payload 里取，否则界面无从还原。"""
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    document = _write_run_file(runs_dir, "v2-0001", engine="advisor-v2", metadata_line=True, personas=["bbc"])

    async def replay():
        run, error = start_replay_run(V2RunStore(), "v2-0001", beat_delay_ms=0)
        assert error == "" and run is not None
        await wait_run_v2(run)
        return run.payload()

    payload = asyncio.run(replay())

    assert payload["spec"] == document["request"]["spec"]
    assert payload["context"]["communication_goal"] == "show the gap"
    # 一次真实咨询不该背上这些字段，前端据 replay_of 分辨两者。
    live = V2RunState(run_id="v2-0002", spec={"mark": "bar"}, context={}, agents={}, order=[], created_at="now")
    assert "spec" not in live.payload() and "replay_of" not in live.payload()


def test_a_change_carries_the_problem_it_answers_not_only_the_treatment():
    """卡片只讲处理方式，设计师就无从判断这一改是冲着什么去的。

    审阅结论里写着当初看到的问题，改动靠 evidence_id 与它相连；两端必须在
    change 上合拢，界面才能说清「问题是什么 / 怎么处理的」。
    """
    persona = Persona(id="bbc", name="BBC")
    source = {"mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "background": "#111111"}
    visual_review = {
        "acceptance": {"findings": [
            {"issue": "Canvas is stark white and fights the series colour.", "image_evidence": "White field behind dark bars.", "severity": "high"},
        ]},
        "findings": [{"issue": "Grid lines are the wrong token.", "l3_ref": "L1 s-grid-horizontal", "severity": "medium"}],
    }
    commitments = [{"id": "c1", "evidence_id": "acceptance_findings[0]", "component": "color", "claim": "Set an editorial canvas.", "before": "White canvas.", "after": "Canvas #111111.", "spec_paths": ["/background"]}]

    rows = _component_changes(persona, source, candidate, commitments, visual_review)

    change = next(row for row in rows if row["scope"] == "color")
    assert change["problem"] == "Canvas is stark white and fights the series colour."
    assert change["severity"] == "high"
    assert change["problem_evidence"] == "White field behind dark bars."


def test_a_finding_cited_in_shorthand_still_resolves_to_the_same_problem():
    """不同 persona 会把同一条结论写成 acceptance_findings[1] 或 AF-2。

    简写按 1 起计；越界时宁可不给出处，也不能张冠李戴地配上别人的问题。
    """
    evidence = _evidence_index({"acceptance": {"findings": [
        {"issue": "First problem."}, {"issue": "Second problem."},
    ]}})

    assert _evidence_for("acceptance_findings[1]", evidence)["problem"] == "Second problem."
    assert _evidence_for("AF-2", evidence)["problem"] == "Second problem."
    assert _evidence_for("AF-9", evidence) == {}
    assert _evidence_for("inventory", evidence) == {}


def test_a_cited_rule_is_quoted_verbatim_instead_of_by_narrative_id():
    """规则的 story 字段存的是叙事编号，不是可读条文。

    把编号原样端到界面上，"依据"一栏就成了 "n-hierarchy" 这样的碎片；必须解引用
    到叙事正文，并把条文原句与它在指南中的位置一并带上。
    """
    persona = Persona(
        id="cmu", name="CMU", source_file="cmu-persona.yaml",
        rules=[Rule(id="s-type-hierarchy", rule="Apply the fixed type hierarchy (Title 15pt Bold / Subtitle 13pt)",
                    strength="must", story="n-hierarchy", src=["L204-238"])],
        stories={"n-hierarchy": Story(id="n-hierarchy", story="Font sizes create a hierarchy that guides the reader.")},
    )
    source = {"mark": "bar", "data": {"values": [{"a": "A", "v": 1}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "config": {"axis": {"labelFontSize": 12}}}
    commitments = [{"id": "t1", "evidence_id": "s-type-hierarchy", "component": "typography", "claim": "Fix the type scale.", "before": "Default sizes.", "after": "Axis labels 12pt.", "spec_paths": ["/config/axis/labelFontSize"]}]

    change = next(row for row in _component_changes(persona, source, candidate, commitments) if row["scope"] == "typography")

    assert change["warrant"]["quote"] == "Apply the fixed type hierarchy (Title 15pt Bold / Subtitle 13pt)"
    assert change["warrant"]["story"] == "Font sizes create a hierarchy that guides the reader."
    assert change["warrant"]["src"] == ["L204-238"]
    # 引用到成文规则才算有出处，界面据此区分「馆规」与「推导」
    assert change["warrant"]["derived"] is False
    assert change["layer"] == "L1"


def test_a_conditional_adaptation_is_credited_to_the_condition_that_triggered_it():
    """机构的条件化适应此前在界面上一条都看不到。

    改动自报的 evidence_id 常是 `inventory` 这类泛指，于是全被压成 L3-derived；
    而拍3 的层级兑现自评里明明写着哪条 L2 落在了哪个 spec 节点上。按这份证据归因，
    并把触发条件念成设计师读得懂的从句。
    """
    persona = Persona(
        id="economist", name="The Economist", source_file="economist-persona.yaml",
        adaptations=[Adaptation(id="a-emphasis", when={"intent": "highlight the key message"}, strength="should")],
    )
    source = {"mark": "line", "data": {"values": [{"a": 1, "v": 2}]}, "encoding": {"x": {"field": "a"}, "y": {"field": "v"}}}
    candidate = {**source, "layer": [{"mark": "rect"}]}
    commitments = [{
        "id": "t1", "evidence_id": "inventory", "component": "marks",
        "claim": "Band the surge window.", "before": "Flat line.", "after": "Tinted band.",
        "spec_paths": ["/layer/0/mark"],
    }]
    implementation = {"l2": [{
        "rule_id": "a-emphasis", "status": "implemented", "trigger": "intent: highlight the key message",
        "spec_evidence": "Tinted band for the surge window (/layer/0).",
    }]}

    change = _component_changes(persona, source, candidate, commitments, None, implementation)[0]

    assert change["layer"] == "L2"
    assert change["knowledge"] == {"layer": "L2", "condition": "the goal is to highlight the key message"}


def test_a_comparison_condition_is_read_out_rather_than_dumped_as_a_mapping():
    """L2 的 when 里会写 `{gt: 600px}` 这类比较式，直接摊到界面上就是一段字典。"""
    persona = Persona(
        id="economist", name="The Economist",
        adaptations=[Adaptation(id="a-grid-wide", when={"viewport": {"gt": "600px"}})],
    )
    source = {"mark": "bar", "encoding": {}}
    commitments = [{"id": "t1", "evidence_id": "inventory", "component": "layout", "claim": "Widen the gutters.",
                    "after": "Padding 32px.", "spec_paths": ["/padding"]}]
    implementation = {"l2": [{"rule_id": "a-grid-wide", "status": "implemented", "spec_evidence": "/padding=32"}]}

    change = _component_changes(persona, source, source, commitments, None, implementation)[0]

    assert change["knowledge"]["condition"] == "the canvas is more than 600px wide"


def test_house_colors_are_l1_knowledge_not_a_before_after_note():
    """落到图上的馆定色值是 L1 气质签名，应出现在 Knowledge，而不是垫在 Change 下的灰字。"""
    persona = Persona(
        id="economist", name="The Economist",
        tokens={"color": {"london-10": "#1A1A1A", "london-35": "#595959"}},
        philosophy=[Philosophy(id="p-clarity", title="Less is more", quote="Be concise.")],
    )
    source = {"mark": "line", "encoding": {}}
    commitments = [{
        "id": "t1", "evidence_id": "inventory", "component": "title",
        "claim": "Darker title and subtitle colors improve readability at a glance.",
        "before": "Title color #292929; subtitle color #555555",
        "after": "Title color #1A1A1A; subtitle color #595959",
    }]

    change = _component_changes(persona, source, source, commitments)[0]

    assert change["layer"] == "L1"
    assert change["knowledge"]["applied"] == "Title color London 10 (#1A1A1A); subtitle color London 35 (#595959)"
    assert change["knowledge"]["tokens"] == [
        {"name": "london-10", "value": "#1A1A1A"},
        {"name": "london-35", "value": "#595959"},
    ]


def test_a_house_hex_is_named_in_knowledge():
    """裸 hex 必须写成馆定色名，Knowledge 不能只剩色号。"""
    persona = Persona(id="bbc", name="BBC", tokens={"color": {"bbc-blue": "#1380A1", "bbc-gray": "#333333"}})
    commitments = [{
        "id": "t1", "evidence_id": "inventory", "component": "color",
        "claim": "Primary series uses #1380A1.",
        "after": "Primary #1380A1; supporting #333333",
    }]
    change = _component_changes(persona, {"mark": "bar"}, {"mark": "bar"}, commitments)[0]
    assert change["knowledge"]["applied"] == "Primary BBC Blue (#1380A1); supporting BBC Gray (#333333)"


def test_engine_self_talk_is_not_a_designer_facing_change():
    """快道补丁的自述不能变成议题卡上的灰色 before→after。"""
    persona = Persona(id="bbc", name="BBC")
    source = {"mark": "bar", "encoding": {}}
    commitments = [{
        "id": "l1-contract-title", "evidence_id": "L1", "component": "title",
        "claim": "Fast-lane contract check restored BBC's unconditional L1 requirements.",
        "before": "generated chart violated the institution's L1 signature",
        "after": "L1 signature re-verified by the fast-lane detectors",
        "authored_by": "fast_lane_contract_enforcement",
    }]

    assert _component_changes(persona, source, source, commitments) == []


def test_a_change_is_explained_by_a_philosophy_the_institution_actually_holds():
    """L3 的理由要说成机构自己的设计信念（"For clarity design identity"）。

    只有该机构确实宣示过这条哲学、且改动的理由确实体现了它，才这么说；
    否则整行留白，不给它套一个外部标签。
    """
    persona = Persona(
        id="bbc", name="BBC",
        philosophy=[Philosophy(id="p-clarity", title="Clarity First", quote="Information should be immediately understandable.")],
    )
    source = {"mark": "bar", "encoding": {}}
    declutter = {"id": "t1", "evidence_id": "inventory", "component": "layout",
                 "claim": "Removed the legend to reduce clutter and make the chart easier to read.", "after": "Direct labels."}
    unrelated = {"id": "t2", "evidence_id": "inventory", "component": "marks",
                 "claim": "Rounded the bar corners.", "after": "Corner radius 2."}

    rows = _component_changes(persona, source, source, [declutter, unrelated])

    assert rows[0]["knowledge"]["layer"] == "L3"
    assert rows[0]["knowledge"]["philosophy"] == "clarity"
    assert rows[0]["knowledge"]["quote"] == "Information should be immediately understandable."
    assert "knowledge" not in rows[1]


def test_a_change_can_carry_more_than_one_knowledge_layer():
    """馆定色是 L1 Traits，理由里的清晰性是 L3 Identity，两层应同时留下。"""
    persona = Persona(
        id="bbc", name="BBC",
        tokens={"color": {"bbc-blue": "#1380A1"}},
        philosophy=[Philosophy(id="p-clarity", title="Clarity First", quote="Information should be immediately understandable.")],
    )
    commitments = [{
        "id": "t1", "evidence_id": "inventory", "component": "color",
        "claim": "Primary series uses BBC Blue so the chart is clearer at a glance.",
        "after": "Series color #1380A1",
    }]
    change = _component_changes(persona, {"mark": "bar"}, {"mark": "bar"}, commitments)[0]
    layers = {item["layer"] for item in change["knowledge_layers"]}
    assert layers == {"L1", "L3"}


def test_an_older_run_gains_its_problems_and_quotes_when_replayed(tmp_path, monkeypatch):
    """早期快照写下时还没有这两个字段，但素材都在同一份记录与知识库里。

    补齐只发生在读取时，磁盘上的留痕必须仍是当初那一份。
    """
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    document = _write_run_file(runs_dir, "v2-0001", engine="advisor-v2", metadata_line=False, personas=["bbc"])
    stored = json.loads((runs_dir / "v2-0001.json").read_text(encoding="utf-8"))
    proposal = stored["agents"][0]["proposal"]
    proposal["facts"] = {"visual_review": {"acceptance": {"findings": [{"issue": "Headline competes with the data.", "severity": "high"}]}}}
    proposal["changes"] = [{
        "id": "bbc:v2:component:t1", "rule_id": "acceptance_findings[0]", "label": "Typography",
        "reason": "Tightened the headline.", "layer": "L1", "strength": "must", "confidence": "high",
        "status": "applied", "ops": [],
        "warrant": {"src": [], "story_id": "s-type-hierarchy", "story": "n-hierarchy", "quote": "", "source_file": "bbc-persona.yaml", "derived": False},
    }]
    (runs_dir / "v2-0001.json").write_text(json.dumps(stored), encoding="utf-8")
    before = (runs_dir / "v2-0001.json").read_text(encoding="utf-8")

    persona = Persona(
        id="bbc", name="BBC",
        rules=[Rule(id="s-type-hierarchy", rule="Apply the four-level type hierarchy", story="n-hierarchy", src=["L48-54"])],
        stories={"n-hierarchy": Story(id="n-hierarchy", story="Type hierarchy guides the reader.")},
    )

    class _Registry:
        def get(self, persona_id):
            return persona if persona_id == "bbc" else None

    async def replay():
        run, error = start_replay_run(V2RunStore(), "v2-0001", beat_delay_ms=0, registry=_Registry())
        assert error == "" and run is not None
        await wait_run_v2(run)
        return run

    change = asyncio.run(replay()).agents["bbc"].proposal["changes"][0]

    assert change["problem"] == "Headline competes with the data."
    assert change["warrant"]["quote"] == "Apply the four-level type hierarchy"
    assert change["warrant"]["story"] == "Type hierarchy guides the reader."
    assert (runs_dir / "v2-0001.json").read_text(encoding="utf-8") == before
    assert document["run_id"] == "v2-0001"


def test_replay_can_select_a_persona_subset_and_reports_missing_ones(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    _write_run_file(runs_dir, "v2-0001", engine="advisor-v2", metadata_line=True, personas=["bbc", "economist"])

    async def replay_subset():
        run, error = start_replay_run(V2RunStore(), "v2-0001", ["economist"], beat_delay_ms=0)
        assert error == "" and run is not None
        await wait_run_v2(run)
        return run

    assert asyncio.run(replay_subset()).order == ["economist"]
    assert start_replay_run(V2RunStore(), "v2-0001", ["who"], beat_delay_ms=0)[1].endswith("who")


def test_replay_rejects_unknown_and_traversing_run_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("VIZGUIDE_STORAGE_DIR", str(tmp_path))
    (tmp_path / "runs").mkdir(parents=True)
    assert "未找到" in start_replay_run(V2RunStore(), "missing")[1]
    # run_id 直接拼进文件路径，必须挡住穿越
    assert "非法" in start_replay_run(V2RunStore(), "../../etc/passwd")[1]


def test_proposal_keeps_the_l1_verification_verdict_for_the_stored_run():
    """拍4 的核验结论必须进入 proposal，否则快照里查不到契约是否兑现。"""
    persona = Persona(id="p", name="P")
    original = {"data": {"values": [{"c": "a", "v": 1}]}, "mark": "bar"}
    verdict = [{"rule_id": "s-source", "ok": True, "detail": "已含来源署名"}]
    result = {
        "spec": {**original, "background": "#ffffff"},
        "beats": {
            "beat2": {"facts": {}},
            "beat3": {"story": "s", "commitments": []},
            "beat4": {
                "changed": True,
                "delivery_state": "ready",
                "safety": {"accepted": True, "errors": []},
                "l1_contract_verification": {"ran": True, "mode": "patch", "patched": ["s-source"], "after": verdict, "unmet": []},
            },
        },
    }
    proposal = _proposal(persona, original, result, 12.0)
    assert proposal["invariants"] == verdict
    assert proposal["facts"]["l1_contract_verification"]["patched"] == ["s-source"]


def test_structural_repair_types_a_secondary_channel_the_primary_cannot_supply():
    """`y` 给的是常量时 `y2` 无从继承类型，缺 type 会让整图编译失败。"""
    source = {"data": {"values": [{"year": 1850, "v": -0.2}]}, "mark": "line", "encoding": {"x": {"field": "year", "type": "quantitative"}}}
    candidate = {
        "data": {"values": [{"year": 1850, "v": -0.2}]},
        "mark": "area",
        "encoding": {"x": {"field": "year", "type": "quantitative"}, "y": {"value": 0}, "y2": {"field": "v"}},
        "primary_data_reference": "__vizguide_primary_data__",
    }
    repaired, repairs = _repair_structural_defects(source, candidate)
    assert repaired["encoding"]["y2"]["type"] == "quantitative"
    assert "primary_data_reference" not in repaired
    assert any("y2" in item for item in repairs) and any("protocol key" in item for item in repairs)


def test_structural_repair_wraps_a_title_that_is_wider_than_its_own_plot():
    """未换行的长副标题会把画布撑到远宽于绘图区，留下大片空白。"""
    source = {"width": 640, "data": {"values": [{"a": 1}]}, "mark": "bar"}
    sentence = "Global temperatures have warmed sharply since 1850, with a record high in 2024 and no sign of reversal."
    candidate = {"width": 640, "data": {"values": [{"a": 1}]}, "mark": "bar", "title": {"text": "Warming", "subtitle": sentence}, "config": {"title": {"subtitleFontSize": 22}}}
    repaired, repairs = _repair_structural_defects(source, candidate)
    lines = repaired["title"]["subtitle"]
    assert isinstance(lines, list) and len(lines) > 1
    assert " ".join(lines) == sentence
    assert any("wrapped overlong title" in item for item in repairs)


def test_an_unfilled_source_placeholder_is_reported_to_the_visual_gate():
    """机构规范要求署名，但原图没有来源可抄时，模型会拿占位符充数。"""
    spec = {
        "title": {"text": "Warming", "subtitle": "Annual anomalies. Source: [Add source]"},
        "mark": "line",
    }

    risks = [risk for risk in _layout_risks(spec) if risk["kind"] == "unfilled_placeholder_text"]

    assert len(risks) == 1
    assert "[Add source]" in risks[0]["check"]
    assert _layout_risks({"title": {"text": "Source: NOAA"}, "mark": "line"}) == []


def test_a_font_the_renderer_cannot_draw_falls_back_within_its_own_style():
    """缺字体时 resvg 是丢字而不是回退，会让验收闸门以为整张图没有文字。"""
    spec = {"config": {"axis": {"labelFont": "Noto Sans"}}, "title": {"font": "Made Up Serif Face"}}

    substitutions = _substitute_unavailable_fonts(spec)

    assert spec["config"]["axis"]["labelFont"] in ("Helvetica", "Arial", "Helvetica Neue", "DejaVu Sans")
    assert spec["title"]["font"] in ("Georgia", "Times New Roman", "Times", "DejaVu Serif")
    assert set(substitutions) == {"Noto Sans", "Made Up Serif Face"}


def test_an_available_font_is_left_exactly_as_the_persona_asked_for_it():
    spec = {"title": {"font": "Georgia"}}

    assert _substitute_unavailable_fonts(spec) == {}
    assert spec["title"]["font"] == "Georgia"


def test_a_year_written_as_a_pixel_constant_is_read_back_as_a_year():
    """`value` 是像素、`datum` 才是数据值：写错会把注记推出绘图区并撑开画布。"""
    source = {
        "width": 600,
        "data": {"values": [{"year": 1850, "t": -0.1}, {"year": 2025, "t": 1.0}]},
        "mark": "line",
        "encoding": {"x": {"field": "year", "type": "quantitative"}, "y": {"field": "t", "type": "quantitative"}},
    }
    candidate = json.loads(json.dumps(source))
    candidate["layer"] = [
        {"mark": "rule", "encoding": {"x": {"value": 2016, "type": "quantitative"}}},
        {"mark": "text", "encoding": {"x": {"value": 1852}, "y": {"value": 0.05}, "text": {"value": "baseline"}}},
        {"mark": "point", "encoding": {"size": {"value": 60}, "opacity": {"value": 0.5}}},
    ]

    repaired, converted = _repair_datum_value_confusion(source, candidate)

    assert repaired["layer"][0]["encoding"]["x"] == {"datum": 2016}
    assert repaired["layer"][1]["encoding"]["x"] == {"datum": 1852}
    assert repaired["layer"][1]["encoding"]["y"] == {"datum": 0.05}
    # 非位置通道的常量本来就该是 value，不能被一起改掉。
    assert repaired["layer"][2]["encoding"]["size"] == {"value": 60}
    assert len(converted) == 3


def test_a_pixel_constant_outside_the_data_range_is_left_alone():
    """落在数据域之外的位置常量确实可能是像素定位，程序不替 persona 决定。"""
    source = {
        "width": 600,
        "data": {"values": [{"share": 0.2}, {"share": 0.8}]},
        "mark": "bar",
        "encoding": {"y": {"field": "share", "type": "quantitative"}},
    }
    candidate = json.loads(json.dumps(source))
    candidate["layer"] = [{"mark": "text", "encoding": {"y": {"value": 40}}}]

    _, converted = _repair_datum_value_confusion(source, candidate)

    assert converted == []


def test_layout_risks_separate_what_the_candidate_introduced_from_what_it_inherited():
    """程序只负责指出「该看哪里」，并区分新引入与原图既有，判断权留给视觉闸门。"""
    source = {
        "resolve": {"scale": {"y": "independent"}},
        "layer": [
            {"mark": "line", "encoding": {"y": {"field": "c", "type": "quantitative", "axis": {"title": "°C"}}}},
            {"mark": "line", "encoding": {"y": {"field": "f", "type": "quantitative", "axis": {"title": "°F"}}}},
        ],
    }
    candidate = json.loads(json.dumps(source))
    candidate["layer"][0]["encoding"]["color"] = {"field": "sign", "type": "nominal", "legend": {"orient": "top-right"}}
    risks = {risk["kind"]: risk["inherited_from_original"] for risk in _new_layout_risks(source, candidate)}
    assert risks["dual_axis_independent_scales"] == "yes"
    assert risks["legend_inside_plot"] == "no"
    assert _layout_risks({"mark": "bar", "encoding": {"y": {"field": "v", "type": "quantitative"}}}) == []


def test_verification_beats_use_a_lighter_reasoning_budget_than_design_beats():
    """核验拍不需要与设计拍同等推理深度；阶段未登记时按设计档，不牺牲质量。"""
    assert settings.reasoning_effort_for("beat3") == settings.reasoning_effort
    assert settings.reasoning_effort_for("beat3_vega_lite_repair") == settings.reasoning_effort
    assert settings.reasoning_effort_for("beat3_visual_acceptance") == settings.verify_reasoning_effort
    assert settings.reasoning_effort_for("beat1") == settings.verify_reasoning_effort
    assert settings.reasoning_effort_for(None) == settings.reasoning_effort


def test_stripping_a_selection_also_removes_the_filter_that_referenced_it():
    """只删声明会把「信号重名」换成「信号未识别」，引用必须一起删。"""
    spec = {
        "params": [{"name": "brush", "select": {"type": "interval", "encodings": ["x"]}}],
        "vconcat": [
            {"mark": "line", "encoding": {"x": {"field": "year", "type": "quantitative"}}},
            {"mark": "bar", "transform": [{"filter": {"param": "brush"}}], "encoding": {"x": {"field": "year", "type": "quantitative"}}},
        ],
    }
    stripped, dropped = _strip_interactive_params(spec)
    assert dropped == ["brush"]
    assert "params" not in stripped
    assert "transform" not in stripped["vconcat"][1]


def test_a_lone_wrapped_object_and_a_bare_item_list_are_both_recovered():
    """模型把对象裹进数组、或只回列表字段本身时，不该整拍作废。"""
    assert _as_json_object([{"verdict": "pass"}]) == {"verdict": "pass"}
    findings = [{"issue": "overlap", "severity": "high"}, {"issue": "clipping", "severity": "low"}]
    assert _as_json_object(findings, "findings") == {"findings": findings}
    assert _as_json_object("not json") == "not json"

