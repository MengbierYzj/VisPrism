"""主持人议程合成：慢道写议程、快道验 id 归属/覆盖/数字接地/降级路径。"""
import asyncio

from app.core.agenda import _FALLBACK_TITLE, synthesize_agenda, validate_agenda


def _proposal(pid: str, name: str, changes: list[dict]) -> dict:
    return {
        "persona_id": pid,
        "persona_name": name,
        "facts": {
            "title_text": "Sales by product",
            "mark_type": "bar",
            "categories": ["Product A", "Product B", "Product C"],
            "max_category": {"name": "Product C", "value": 162},
            "chart_slice": {"rows": [{"product": "Product C", "sales": 162}]},
        },
        "changes": changes,
    }


def _change(cid: str, label: str) -> dict:
    return {
        "id": cid,
        "label": label,
        "layer": "L1",
        "status": "applied",
        "strength": "should",
        "ops": [{"action": "set_title_text", "text": "Product C is the clear winner"}],
        "reason": "The title should state the takeaway.",
        "warrant": {"quote": "Titles state the finding."},
    }


PROPOSALS = {
    "bbc": _proposal("bbc", "BBC", [_change("bbc:s-title", "Takeaway headline"), _change("bbc:s-color", "Grey context")]),
    "eco": _proposal("eco", "The Economist", [_change("eco:s-color", "House palette accent")]),
}


class AgendaLLM:
    mode = "live"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def chat_json(self, system, user, **kwargs):
        self.calls += 1
        return self.payload


def _valid_issue(**over):
    base = {
        "title": "Title states the topic, not the takeaway",
        "blurb": "The headline names the data; the goal asks it to argue the finding.",
        "category": "title",
        "discussion_intro": "Both advisors want the title to carry the takeaway.",
        "quick_asks": ["Can a kicker and a takeaway headline work together?"],
        "treatments": [
            {"persona_id": "bbc", "line": "Left-aligned takeaway headline", "change_ids": ["bbc:s-title"]},
        ],
    }
    base.update(over)
    return base


def test_mock_mode_returns_none():
    class MockLLM:
        mode = "mock"

        async def chat_json(self, *a, **k):
            raise AssertionError("mock 模式不得发起议程调用")

    out = asyncio.run(synthesize_agenda(["bbc"], PROPOSALS, {}, MockLLM()))
    assert out is None


def test_agenda_grounds_ids_and_covers_leftovers():
    llm = AgendaLLM(
        {
            "issues": [
                _valid_issue(),
                {
                    # 全部 change id 均不存在 → 议题被丢弃
                    "title": "Phantom issue",
                    "category": "axes",
                    "treatments": [
                        {"persona_id": "bbc", "line": "x", "change_ids": ["bbc:not-real"]}
                    ],
                },
                {
                    # 混入他人 id 与假 id：只保留归属正确的真 id
                    "title": "Categorical rainbow doesn't serve the goal",
                    "blurb": "Colour carries no meaning here.",
                    "category": "color",
                    "discussion_intro": "Strategies differ on muting vs re-encoding.",
                    "quick_asks": ["What about colour-blind readers?"],
                    "treatments": [
                        {"persona_id": "bbc", "line": "Grey out the context", "change_ids": ["bbc:s-color", "eco:s-color", "bbc:fake"]},
                        {"persona_id": "eco", "line": "House navy with a red accent", "change_ids": ["eco:s-color"]},
                    ],
                },
            ]
        }
    )
    out = asyncio.run(synthesize_agenda(["bbc", "eco"], PROPOSALS, {}, llm))
    assert out is not None and llm.calls == 1
    titles = [i["title"] for i in out["issues"]]
    assert "Phantom issue" not in titles
    # 双机构议题排最前
    assert titles[0] == "Categorical rainbow doesn't serve the goal"
    color = out["issues"][0]
    assert [t["change_ids"] for t in color["treatments"]] == [["bbc:s-color"], ["eco:s-color"]]
    # 每条 change 恰好出现一次；无漏网 → 没有兜底议题
    all_ids = [cid for i in out["issues"] for t in i["treatments"] for cid in t["change_ids"]]
    assert sorted(all_ids) == ["bbc:s-color", "bbc:s-title", "eco:s-color"]
    assert _FALLBACK_TITLE not in titles


def test_leftover_changes_get_fallback_issue():
    llm = AgendaLLM({"issues": [_valid_issue()]})  # 只覆盖 bbc:s-title
    out = asyncio.run(synthesize_agenda(["bbc", "eco"], PROPOSALS, {}, llm))
    assert out is not None
    fallback = out["issues"][-1]
    assert fallback["title"] == _FALLBACK_TITLE
    ids = {cid for t in fallback["treatments"] for cid in t["change_ids"]}
    assert ids == {"bbc:s-color", "eco:s-color"}


def test_fabricated_numbers_are_rejected_per_field():
    pool = [162.0, 3.0]
    raw = {
        "issues": [
            _valid_issue(title="Product C wins with 87% share"),  # 标题编造 → 议题丢弃
            _valid_issue(
                title="Product C is far ahead at 162",
                blurb="It holds 91% of the market.",  # blurb 编造 → 仅清空 blurb
                treatments=[
                    {
                        "persona_id": "bbc",
                        # 行内编造大数 → 回落 change label
                        "line": "Highlight the 4750 gap",
                        "change_ids": ["bbc:s-title"],
                    }
                ],
            ),
        ]
    }
    out = validate_agenda(raw, PROPOSALS, pool)
    assert out is not None
    kept = [i for i in out["issues"] if i["title"] != _FALLBACK_TITLE]
    assert len(kept) == 1
    assert kept[0]["title"] == "Product C is far ahead at 162"
    assert kept[0]["blurb"] == ""
    assert kept[0]["treatments"][0]["line"] == "Takeaway headline"
    # 被丢弃议题的 changes 落入兜底议题，采纳入口不丢失
    assert out["issues"][-1]["title"] == _FALLBACK_TITLE


def test_validate_agenda_none_on_garbage():
    assert validate_agenda(None, PROPOSALS, []) is None
    assert validate_agenda({"issues": "nope"}, PROPOSALS, []) is None
    assert validate_agenda({"issues": []}, PROPOSALS, []) is None


def test_why_line_validated_hex_humanized_and_ungrounded_cleared():
    raw = {
        "issues": [
            _valid_issue(
                treatments=[{
                    "persona_id": "bbc",
                    "line": "Left-aligned takeaway headline",
                    "why": "When the goal names a finding, the headline argues it in #1380A1",
                    "change_ids": ["bbc:s-title"],
                }]
            )
        ]
    }
    out = validate_agenda(raw, PROPOSALS, [162.0])
    assert out is not None
    t = out["issues"][0]["treatments"][0]
    # hex → 口语色词；句式原样保留
    assert t["why"] == "When the goal names a finding, the headline argues it in teal"

    raw2 = {
        "issues": [
            _valid_issue(
                treatments=[{
                    "persona_id": "bbc",
                    "line": "Left-aligned takeaway headline",
                    "why": "When sales exceed 9000, highlight the winner",
                    "change_ids": ["bbc:s-title"],
                }]
            )
        ]
    }
    out2 = validate_agenda(raw2, PROPOSALS, [162.0])
    assert out2 is not None
    # 编造数字的 why 清空（前端回落 reason 首句），treatment 本身保留
    assert out2["issues"][0]["treatments"][0]["why"] == ""
    assert out2["issues"][0]["treatments"][0]["change_ids"] == ["bbc:s-title"]


def test_leftover_rescue_attaches_to_matching_issue():
    # bbc:s-color 漏排，但存在 color 议题 → 拉回该议题（行文退化为 label），不落兜底
    raw = {
        "issues": [
            _valid_issue(),
            {
                "title": "Categorical rainbow doesn't serve the goal",
                "category": "color",
                "treatments": [
                    {"persona_id": "eco", "line": "House navy with a red accent", "change_ids": ["eco:s-color"]}
                ],
            },
        ]
    }
    out = validate_agenda(raw, PROPOSALS, [162.0])
    assert out is not None
    titles = [i["title"] for i in out["issues"]]
    assert _FALLBACK_TITLE not in titles
    color = next(i for i in out["issues"] if i["category"] == "color")
    by_pid = {t["persona_id"]: t for t in color["treatments"]}
    assert set(by_pid) == {"eco", "bbc"}
    assert by_pid["bbc"]["change_ids"] == ["bbc:s-color"]
    assert by_pid["bbc"]["line"] == "Grey context"


def test_category_normalized_from_title_claim():
    # 模型把标题议题标成 labels；标题判断句明说 Title → 锚点类别归一为 title
    raw = {"issues": [_valid_issue(category="labels")]}
    out = validate_agenda(raw, PROPOSALS, [162.0])
    assert out is not None
    kept = [i for i in out["issues"] if i["title"] != _FALLBACK_TITLE]
    assert kept[0]["category"] == "title"


def test_hex_codes_become_color_words_and_same_persona_treatments_merge():
    raw = {
        "issues": [
            _valid_issue(
                title="Colour choices dilute the emphasis",
                blurb="All marks share #6929c4 so nothing stands out.",
                category="color",
                treatments=[
                    # 首行带句末句号：合并时应去掉，避免 ".;" 拼接瑕疵
                    {"persona_id": "bbc", "line": "Set all marks to #3665f3.", "change_ids": ["bbc:s-title"]},
                    {"persona_id": "bbc", "line": "Grey out the context in #cbcbcb", "change_ids": ["bbc:s-color"]},
                ],
            )
        ]
    }
    out = validate_agenda(raw, PROPOSALS, [162.0])
    assert out is not None
    issue = out["issues"][0]
    by_pid = {t["persona_id"]: t for t in issue["treatments"]}
    # 同机构两条 treatment 合并为一行，ids 连接；hex 全部转口语色词
    assert by_pid["bbc"]["change_ids"] == ["bbc:s-title", "bbc:s-color"]
    assert by_pid["bbc"]["line"] == "Set all marks to blue; Grey out the context in light grey"
    assert issue["blurb"] == "All marks share purple so nothing stands out."
    # 漏网的 eco:s-color 被救援进这个 color 议题（行文退化为 label），无兜底议题
    assert by_pid["eco"]["change_ids"] == ["eco:s-color"]
    assert all(i["title"] != _FALLBACK_TITLE for i in out["issues"])
