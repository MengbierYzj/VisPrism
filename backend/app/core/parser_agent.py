"""Parser Agent：机构规范 Markdown → 可追溯的三层 persona。

live 模式以 LLM 理解为主、程序校验为辅：
1. 分块：LLM 从带行号文档块抽取原子要求与证据（叙事 HIG / cookbook 均适用）；
2. 整编：LLM 去重、重分类、补全受控 then（不发明 hex）；
3. 程序：证据校验、三层分类门、compile 质量门。

分层对齐手工范例（bbc/economist-persona.yaml）——落盘主文件仅含：
  institution / applicability / L1_signature / L2_adaptations / L3_narrative
- L1：无条件恒定 tokens + must/never/should 规则（无可执行 then 时 check:llm）
- L2：有实质 when 的条件规范；也可产出 persona 专属的 visual-strategy / component-assembly
  策略，供拍3在图像证据出现后作出不同机构的处理
- L3：philosophy + stories + exemplars
- 审计字段写入 sidecar `*-parser-audit.yaml`

叙事型指南（如 Apple HIG）可无色板令牌；质量门以可编译 L1/L2 为主，令牌缺失仅警告。
mock 模式仍提供确定性底线解析，保证离线端到端可运行。
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import settings
from ..llm import LLMClient, LLMError

# 与 data/bbc-persona.yaml、data/economist-persona.yaml 一致的规范正文键
PERSONA_CANONICAL_KEYS = (
    "institution",
    "applicability",
    "L1_signature",
    "L2_adaptations",
    "L3_narrative",
    # 面向 advisor 的语义知识层；旧 Persona loader 会安全忽略未知顶层键。
    "diagnostics",
    "chart_type_guidance",
    "palette_guidance",
    "conflicts",
)
PERSONA_AUDIT_KEYS = (
    "unmapped_requirements",
    "evidence_catalog",
    "parser_provenance",
)

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_BARE_HEX = re.compile(r"^[0-9a-fA-F]{6}$")
# 设计系统常把色阶与六位色值连写，如 Purple 70 + 6929c4 → 706929c4。
_SCALE_PREFIXED_HEX = re.compile(r"^(?:100|[1-9]0)([0-9a-fA-F]{6})$")
_NAMED_SCALE_COLOR = re.compile(
    r"\b([A-Za-z][A-Za-z-]{1,24})\s+((?:100|[1-9]0)[0-9a-fA-F]{6})\b"
)
_TOKEN_REF = re.compile(r"^\{?[a-zA-Z][a-zA-Z0-9_-]*(?:\.[a-zA-Z0-9_-]+)+\}?$")
_CSS_VAR = re.compile(r"^--[a-zA-Z0-9_-]+$")
_LINE_REF = re.compile(r"^L(\d+)(?:-L?(\d+))?$", re.I)
_PLACEHOLDERS = ("原文行号", "原文段落", "todo", "待补充")
# 路径叶不得是色阶+hex 或纯 hex，避免 LLM 生成 color.purple.706929c4
_BAD_TOKEN_LEAF = re.compile(r"^(?:100|[1-9]0)?[0-9a-fA-F]{6}$", re.I)
_RULE_HINTS = (
    "must", "never", "always", "should", "avoid", "only", "need to",
    "必须", "禁止", "不得", "应该", "建议", "仅", "默认", "统一",
)
_STRONG_HINTS = ("must", "never", "必须", "禁止", "不得", "always")
_CONDITION_HINTS = (
    " if ", " when ", " whenever ", " only when ", " unless ",
    "single", "multiple", "two series", "small multiples", "static", "digital",
    "如果", "当", "仅当", "单序列", "多序列", "双序列", "小多重图", "移动端", "印刷",
)
_RATIONALE_HINTS = (
    "because", "so that", "in order to", "avoid misleading", "reduces", "easier",
    "为了", "因为", "以便", "避免误导", "减少", "更容易",
)
_SUPPORTED_TARGETS = {
    "mark.color",
    "color.range",
    "emphasized-mark.color",
    "chart.size",
    "chart.type",
    "chart.background",
    "background",
    "font.family",
    "font.sizes",
    "title.anchor",
    "legend.orient",
    "legend.title",
    "grid.horizontal",
    "grid.vertical",
    "source.required",
    "mark.style",
    "bar.style",
    "line.style",
    "point.style",
    "area.style",
    "axis.x",
    "axis.y",
    "encoding.shape",
    "encoding.size",
    "annotation.style",
    "text.style",
    "legend.style",
}

# Parser 可为拍3生成的受限策略词表。它们仍属于 L2，而非新增第四层；每项必须由
# 指南原文 quote 担保，不能用“通用最佳实践”补造。
_PARSER_VISUAL_ISSUES = {
    "mark_label_overlap", "text_mark_collision", "overlap", "whitespace", "crowding",
    "color_similarity", "pairwise_color",
}
_PARSER_VISUAL_ACTIONS = {
    "increase_padding", "increase_height", "recolor_categorical", "recolor_paired",
    "recolor_uniform", "remove_value_labels", "shorten_labels", "thin_axis_labels",
    "thin_axis_ticks", "rotate_x_labels", "reduce_axis_grid", "zero_baseline",
    "widen_bars", "separate_bars", "round_bar_corners", "soften_marks",
    "improve_text_legibility", "deemphasize_annotations", "move_legend_top",
    "remove_legend_title", "tighten_axis_titles", "normalize_axis_title_layout", "nudge_title",
}
# 图型类别标题 → (intent slug, when 键)
_CHART_SECTION_INTENTS = {
    "comparisons": ("comparison", "intent"),
    "comparison": ("comparison", "intent"),
    "trends": ("trend", "intent"),
    "trend": ("trend", "intent"),
    "part to whole": ("part-to-whole", "intent"),
    "part-to-whole": ("part-to-whole", "intent"),
    "correlations": ("correlation", "intent"),
    "correlation": ("correlation", "intent"),
    "relationships and connections": ("relationship", "intent"),
    "relationships": ("relationship", "intent"),
    "maps": ("map", "intent"),
    "map": ("map", "intent"),
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "custom"


EXTRACTION_GUIDE = """
你是可视化设计知识抽取器。只分析本次给出的带行号文档块，逐条抽取原子知识。
优先用语义理解整理规范；不要只做关键词扫描。叙事型 HIG（Apple/Human Interface）
与色板 cookbook（BBC/IBM）同等重要。

分类必须严格遵守 McAdams 三层判据：
- L1：无条件、跨情境恒定的 signature（命名 design tokens；无 when 的 must/never/should）。
  只要存在 when/if/for/特定图型、任务、主题、媒介或受众条件，就绝不能放入 L1。
  定义句（“A mark is…”）不是 must 规范→标 L3-philosophy 或跳过，勿标 L1 must。
- L2：显式绑定任务/数据/图型意图/主题/媒介/受众的 when→then。
  图型推荐必须是 L2，then 用 prefer chart.type（勿改成 chart.size）。
  包括散文：“Bar marks work well for comparing…”→ prefer bar + when.intent=comparison；
  “Line marks… over time”→ line + trend；“Point marks… relate/outliers”→ point + correlation。
  条件必须由原文担保，不能从 for example 的示例数据主题臆造。
- L3-philosophy：原则/价值宣言；requirement 用原文语言逐字；title 可保存原则名。
- L3-story：解释“为什么”的短理由；不是整段规范。
- example：教程示例/示例数据；只进证据目录。

层级完整性：L3 只保留机构级、跨图表的价值原则。不要把目录标题、色板名称、
Legend position、Axis breaks、Gradient use、具体图型小节或其拆句放入 L3；它们必须
作为 L1/L2 规则，或在无法执行时仍作为 L2 自然语言规则保留。每个具名设计原则最多
一条 philosophy 和一条简短 story，禁止同义重复。

关键约束：
1. evidence.lines + evidence.quote 必填；quote 必须逐字来自所给行号。
2. 不得输出占位符；不得发明原文没有的 #RRGGBB。无品牌色时 tokens 可为 []。
3. 多要求句子拆成多个原子 requirement。
4. 无法映射到受控 then 时 then=null，仍保留自然语言 requirement（供慢道）。
5. 有色值时 token path 用语义名（color.primary、palette.categorical），值为 #RRGGBB；
   Purple 706929c4 → color.purple-70 / #6929C4；禁止把 hex 写进 path。
6. “Avoid relying solely on color…”“prefer familiar tick sequences”“zero lower bound
   for bar charts”等应抽取为规则；能映射则给 then，否则 then=null + 清晰 requirement。
7. 对 Color 章节必须同时抽取 token 与选择策略，不能只抄色值：categorical（无内在顺序
的离散类别）、sequential（有序数量/层级）、diverging（有意义中点或双向比较）、
light/dark theme 的极值明暗方向、alert 的状态语义、以及 texture/shape/pattern 对
色觉无障碍的补强。保留指南明确要求的 palette 顺序。
8. 对 Chart anatomy / Legend / Axes / Time series 建立覆盖清单：标题与标签清晰/避免缩写、
直接标注与单类别无图例、图例位置与 mobile/geospatial 例外、零基线/可裁切例外、
axis break、固定时间增量、本地化日期、landmark label。每项原文明确规范至少输出一个
原子 L1/L2；当前 action space 不支持时仍输出 L2 + 真实 when + then=null，勿降为 L3 或 unmapped。
9. 意图规范化：统一使用 comparison、trend、part-to-whole、correlation、relationship、map；
不要为同一段推荐额外创造 composition 等同义条件，也不要重复同一 chart recommendation。

受控 then（仅在原文清楚支持时使用）：
{"set":"mark.color","to":"{color.primary}"}
{"set":"color.range","to":"{palette.categorical}"}
{"prefer":"chart.type","to":"bar","with":"optional alternatives"}
{"prefer":"chart.type","to":"line"}
{"prefer":"chart.type","to":"point"}
{"set":"chart.type","to":"bar"}
{"set":"chart.size","to":"640x450"}
{"set":"legend.orient","to":"bottom"}
{"set":"grid.horizontal","to":"{color.grid}"}
{"set":"grid.vertical","to":false}
{"set":"font.family","to":"{font.family}"}
{"set":"title.anchor","to":"start"}
{"set":"source.required","to":true}
{"set":"mark.style","to":{"opacity":0.8,"strokeWidth":2,"cornerRadius":4}}
{"set":"line.style","to":{"strokeWidth":2,"strokeDash":[4,2],"point":true}}
{"set":"axis.y","to":{"scale":{"zero":true},"axis":{"grid":false}}}
{"set":"encoding.shape","to":{"field":"status","type":"nominal"}}
{"set":"legend.style","to":{"orient":"bottom","labelFontSize":12}}
无法表达时 then=null。

L2 when 示例（键必须受控）：
{"intent":"comparison"} / {"intent":"trend"} / {"intent":"correlation"} /
{"intent":"part-to-whole"} / {"series_count":1} / {"series_count":{"gte":3}} /
{"medium":"digital"} / {"medium":"mobile"} / {"chart.type":"geospatial"} /
{"chart.type":"bar"} / {"chart.type":"line"} / {"chart.type":"scatter"}

除三层规则外，必须把能指导 advisor 诊断的问题、图型选择和色板语义结构化输出。
不要把一组图型推荐压缩成单个 chart.type；保存候选、适用条件和 executable=false。
每条有效规范尽量补充 scope、problem_type、principle_refs、actions、avoid_when、verification。
scope 只可为 chart（默认）、visual-strategy、component-assembly：
- visual-strategy 是 L2：仅当原文明确谈到拥挤、重叠、标签/刻度可读性、留白、对比、装饰克制等
  “发现问题后如何处理”的规范时输出；必须给 visual_issues（mark_label_overlap、text_mark_collision、
  overlap、whitespace、crowding、color_similarity、pairwise_color）和 actions。actions 只能是
  increase_padding/increase_height/recolor_categorical/recolor_paired/recolor_uniform/remove_value_labels/
  shorten_labels/thin_axis_labels/thin_axis_ticks/rotate_x_labels/reduce_axis_grid/zero_baseline/widen_bars/
  separate_bars/round_bar_corners/soften_marks/improve_text_legibility/deemphasize_annotations/move_legend_top/
  remove_legend_title/tighten_axis_titles/normalize_axis_title_layout/nudge_title。
- component-assembly 也是 L2：仅当原文明确规定标题、说明、图内注释、来源/credit 应处于不同稳定阅读
  区域或不得丢失时输出；when 必须为 {"pixel_positioned_text":true}，actions=[]。它授权拍3按
  该 persona 的 quote 重组固定像素导入图，不能输出坐标、padding 或 Vega-Lite。
普通 chart 规则动作只能使用受控 action，无法执行时保留 actions=[] 和 recommend_only=true。

只输出 JSON：
{
  "tokens": [
    {"path":"color.primary","value":"#1380A1",
     "evidence":{"lines":"L12","quote":"逐字含色值的原文"}}
  ],
  "requirements": [
    {"classification":"L1|L2|L3-philosophy|L3-story|example",
     "requirement":"单一、具体、忠于原文",
     "title":"原则名可选",
     "strength":"must|never|should|may",
     "when":{}, "then":null, "scope":"chart|visual-strategy|component-assembly",
     "visual_issues":[],
     "reason":"",
     "applicability":{"intent":"comparison|trend|part-to-whole|correlation|relationship|map|null",
              "mark_type":[],"medium":null,"theme":null},
     "problem_type":"dense_axis_labels|null",
     "principle_refs":[],
     "actions":[], "avoid_when":[], "verification":[],
     "recommend_only":false,
     "evidence":{"lines":"L34","quote":"逐字原文"}}
  ],
  "diagnostics":[{"id":"dense-axis-labels","problem_type":"dense_axis_labels",
    "detect":{"chart_audit":{"axes.x_dense":true}},"severity":"low|medium|high",
    "related_rules":[],"preferred_actions":[],"verification":[]}],
  "chart_type_guidance":[{"intent":"comparison","mode":"recommend_only",
    "candidates":[{"type":"bar","conditions":{},"executable":true}]}],
  "palette_guidance":[{"id":"categorical-light","family":"categorical",
    "theme":"light","mode":"discrete","order":"strict","colors":[],
    "use_when":[],"avoid_when":[]}],
  "conflicts":[{"id":"bar-zero-vs-line-crop","if":{},"prefer":[],"reject":[]}]
}
""".strip()


ORGANIZATION_GUIDE = """
你是可视化设计人格整编器。输入是同一机构指南经分块抽取后的候选 tokens/requirements。
请用设计专家判断做整理（去重、重分类、补全受控 then），输出一份干净草案。
程序稍后会再做证据校验——你必须保留或选用候选里已有的逐字 evidence.quote，不得编造行号/引文。

整编原则：
1. 合并重复；同一规范只保留一条最清晰的表述。
2. 纠正层级：定义句/原则宣言→L3-philosophy；条件性图型/任务建议→L2；
   无条件硬约束→L1。不要把定义句标成 L1 must。
3. 图型散文必须尽量落地为 L2：
   bar/compare/proportions → {"prefer":"chart.type","to":"bar"} + when.intent=comparison
   line/over time/trends → line + intent=trend
   point/scatter/outliers/clusters → point + intent=correlation
4. 绝对不要发明原文没有的 hex / 色板 token。无色则 tokens=[]。
5. then 仅用受控动作（与抽取器相同）；无法映射则 then=null，保留自然语言。
6. 丢弃 Source:/Related: URL、纯目录、无设计含义的句子。
7. strength：真正强制用 must/never；多数 HIG 建议用 should/may。
8. 先完成 section coverage，再去重：Chart taxonomy、Chart anatomy、Legend、Axes（zero/
break/time series）、Color purpose/accessibility、categorical、sequential、diverging、alert、
gradient、texture 各至少检查一次。原文存在明确规范时，必须留下恰当 L1/L2/L3 项。
9. L3 只保留机构级命名原则（如 Understandable/Essential 等），每个原则仅一条；章节标题
和操作性小节不得进入 L3。将其转为原子 L1/L2，并把同义 intent 统一为 comparison、trend、
part-to-whole、correlation、relationship、map。
10. 对尚无受控 then 的有效条件规范，输出 L2 + 原子 requirement + 真实 when + then=null；
不要因为暂不可编译而改为 L3 或 unmapped。
11. 对指南明确的“问题 → 处理”知识，不要只留 diagnostics：同时产出 L2 `scope: visual-strategy`，
给出受限 visual_issues/actions 和原文 evidence。对标题/说明/图内注释/来源的稳定区域或保留要求，
产出 L2 `scope: component-assembly`、`when:{"pixel_positioned_text":true}`；两种 scope 都是三层中的 L2。

输出 JSON（保留抽取器字段，并合并 diagnostics/chart_type_guidance/palette_guidance/conflicts；
不得删除有效 evidence）：
{"tokens":[...],"requirements":[...],"diagnostics":[],"chart_type_guidance":[],
 "palette_guidance":[],"conflicts":[]}
""".strip()


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _normalize_color_literal(value: Any) -> Any:
    """将标准、裸六位及“色阶+六位色值”统一为 #RRGGBB。"""
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if _HEX.fullmatch(raw):
        return raw
    if _BARE_HEX.fullmatch(raw):
        return f"#{raw.upper()}"
    scale_match = _SCALE_PREFIXED_HEX.fullmatch(raw)
    if scale_match:
        return f"#{scale_match.group(1).upper()}"
    return value


def _normalize_token_value(path: str, value: Any) -> Any:
    if path.startswith("color."):
        return _normalize_color_literal(value)
    if path.startswith("palette.") and isinstance(value, list):
        return [_normalize_color_literal(item) for item in value]
    return value


def _contains_term(text: str, term: str) -> bool:
    """按完整英文词/短语匹配，中文仍使用包含匹配。"""
    normalized = _normalize_text(text)
    needle = _normalize_text(term)
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9 -]+", needle):
        pattern = r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return bool(re.search(pattern, normalized))
    return needle in normalized


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _extract_color_literals(line: str) -> list[str]:
    """提取标准 hex、裸六位 hex 和通用的“10–100 色阶+六位 hex”形式。"""
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in _HEX.finditer(line):
        found.append(match.group())
        occupied.append(match.span())
    for match in re.finditer(r"\b(?:100|[1-9]0)([0-9a-fA-F]{6})\b", line):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        found.append(f"#{match.group(1).upper()}")
        occupied.append(match.span())
    for match in re.finditer(r"(?<![#0-9a-fA-F])([0-9a-fA-F]{6})(?![0-9a-fA-F])", line):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw = match.group(1)
        # 裸 hex 至少含一个数字，避免把普通六字母单词误识别为颜色。
        if any(char.isdigit() for char in raw):
            found.append(f"#{raw.upper()}")
    return list(dict.fromkeys(found))


def _slug_chart_type(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    aliases = {
        "simple-bar": "bar",
        "grouped-bar": "grouped-bar",
        "floating-bar": "floating-bar",
        "stacked-bar": "stacked-bar",
        "stacked-area": "stacked-area",
        "scattorplot": "scatter",
        "scatterplot": "scatter",
        "chorpleth-map": "choropleth",
        "choropleth-map": "choropleth",
        "propotional-symbol": "proportional-symbol",
        "proportional-symbol": "proportional-symbol",
        "tree-map": "treemap",
        "circle-pack": "circle-pack",
        "wordcloud": "wordcloud",
        "word-cloud": "wordcloud",
    }
    return aliases.get(cleaned, cleaned)


def _parse_recommended_charts(line: str) -> list[str]:
    match = re.search(
        r"recommend(?:ed)?\s+charts?\s*:\s*(.+)$",
        line,
        re.I,
    )
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r"[、,;/|]+", raw)
    charts = [_slug_chart_type(part) for part in parts if part.strip()]
    return [c for c in charts if c]


def _chart_section_heading(line: str) -> tuple[str, str] | None:
    clean = line.strip().lstrip("#*- ").strip().rstrip("：:").strip()
    key = _normalize_text(clean)
    if key in _CHART_SECTION_INTENTS:
        return _CHART_SECTION_INTENTS[key]
    return None


def _sanitize_token_path(path: str) -> str | None:
    """拒绝把色阶+hex 塞进 path；只保留语义化点路径。"""
    parts = [p for p in path.split(".") if p]
    if not parts or len(parts) > 6:
        return None
    clean: list[str] = []
    for part in parts:
        if _BAD_TOKEN_LEAF.fullmatch(part):
            return None
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", part):
            return None
        clean.append(part)
    return ".".join(clean)


def _named_scale_token(line: str) -> tuple[str, str] | None:
    """Purple 706929c4 → (color.purple-70, #6929C4)。"""
    match = _NAMED_SCALE_COLOR.search(line)
    if not match:
        return None
    hue = slugify(match.group(1))
    raw = match.group(2)
    scale_match = re.match(r"^(100|[1-9]0)", raw)
    if not scale_match:
        return None
    scale = scale_match.group(1)
    color = _normalize_color_literal(raw)
    if not isinstance(color, str) or not _HEX.fullmatch(color):
        return None
    return f"color.{hue}-{scale}", color


def _line_ref(start: int, end: int) -> str:
    return f"L{start}" if start == end else f"L{start}-L{end}"


def _chunk_document(text: str, max_chars: int = 3000) -> list[dict]:
    """按行切块且保留全局行号；优先在 Markdown 标题前断开。"""
    lines = text.splitlines()
    chunks: list[dict] = []
    start = 0
    while start < len(lines):
        size = 0
        end = start
        last_heading = None
        while end < len(lines):
            rendered = f"L{end + 1}:{lines[end]}\n"
            if size + len(rendered) > max_chars and end > start:
                break
            if end > start and lines[end].lstrip().startswith("#"):
                last_heading = end
            size += len(rendered)
            end += 1
        if end < len(lines) and last_heading is not None and last_heading - start >= 8:
            end = last_heading
        numbered = "\n".join(f"L{i + 1}:{lines[i]}" for i in range(start, end))
        chunks.append({"start": start + 1, "end": end, "text": numbered})
        start = end
    return chunks


def _deterministic_candidates(text: str) -> dict:
    """从明确代码/原文模式补充高置信候选，不替代 LLM 的开放抽取。

    这些模式面向常见设计系统表达（theme/font/legend/grid/size/source），
    所有候选仍走同一证据校验与三层组装。
    """
    lines = text.splitlines()
    fragment: dict[str, list] = {"tokens": [], "requirements": []}

    def find_line(needle: str) -> tuple[int, str] | None:
        for i, line in enumerate(lines, 1):
            if needle.lower() in line.lower():
                return i, line.strip()
        return None

    def evidence(needle: str) -> dict | None:
        found = find_line(needle)
        return {"lines": f"L{found[0]}", "quote": found[1]} if found else None

    def add_token(path: str, value: Any, needle: str) -> None:
        ev = evidence(needle)
        if ev:
            fragment["tokens"].append({"path": path, "value": value, "evidence": ev})

    def add_requirement(
        classification: str,
        requirement: str,
        needle: str,
        *,
        strength: str = "should",
        when: dict | None = None,
        then: dict | None = None,
        reason: str = "",
    ) -> None:
        ev = evidence(needle)
        if ev:
            fragment["requirements"].append(
                {
                    "classification": classification,
                    "requirement": requirement,
                    "strength": strength,
                    "when": when or {},
                    "then": then,
                    "reason": reason,
                    "evidence": ev,
                }
            )

    def range_evidence(start: int, end: int) -> dict:
        return {
            "lines": _line_ref(start, end),
            "quote": "\n".join(lines[start - 1 : end]),
        }

    def add_token_with_evidence(
        path: str,
        value: Any,
        start: int,
        end: int,
        *,
        evidence_kind: str = "direct",
        pattern_sources: list[str] | None = None,
    ) -> None:
        fragment["tokens"].append(
            {
                "path": path,
                "value": value,
                "evidence": range_evidence(start, end),
                "evidence_kind": evidence_kind,
                "pattern_sources": pattern_sources or [],
            }
        )

    def add_requirement_with_evidence(
        classification: str,
        requirement: str,
        start: int,
        end: int,
        *,
        strength: str,
        when: dict,
        then: dict | None,
        reason: str = "",
        derived: bool = False,
        pattern_sources: list[str] | None = None,
    ) -> None:
        fragment["requirements"].append(
            {
                "classification": classification,
                "requirement": requirement,
                "strength": strength,
                "when": when,
                "then": then,
                "reason": reason,
                "derived": derived,
                "pattern_sources": pattern_sources or [],
                "evidence": range_evidence(start, end),
            }
        )

    # 从任意“命名分类色板”章节抽取默认色板。章节名负责语义担保，色值行可使用
    # #RRGGBB、裸六位或“色阶+六位”格式；不依赖具体机构或颜色名称。
    categorical_sections: list[tuple[int, int, list[str], str]] = []
    active_start: int | None = None
    active_mode = "default"
    active_colors: list[str] = []
    active_last_line = 0

    def flush_categorical() -> None:
        nonlocal active_start, active_mode, active_colors, active_last_line
        if active_start is not None and len(active_colors) >= 2:
            categorical_sections.append(
                (active_start, active_last_line, list(dict.fromkeys(active_colors)), active_mode)
            )
        active_start, active_mode, active_colors, active_last_line = None, "default", [], 0

    in_categorical = False
    section_heading = 0
    for line_no, line in enumerate(lines, 1):
        low = _normalize_text(line)
        if re.search(r"\b(?:categorical|qualitative)\s+palettes?\b", low):
            flush_categorical()
            in_categorical = True
            section_heading = line_no
            active_start = line_no
            continue
        if in_categorical and re.search(
            r"\b(?:sequential|diverging|alert|monochromatic)\s+palettes?\b", low
        ):
            flush_categorical()
            in_categorical = False
            continue
        if not in_categorical:
            continue
        mode_match = re.search(r"\b(light|dark)\s+(?:mode|theme)\b", low)
        if mode_match:
            flush_categorical()
            active_mode = mode_match.group(1)
            active_start = section_heading
            continue
        colors = _extract_color_literals(line)
        if colors:
            active_start = active_start or section_heading or line_no
            active_colors.extend(colors)
            active_last_line = line_no
    flush_categorical()

    if categorical_sections:
        default_section = next(
            (item for item in categorical_sections if item[3] in ("light", "default")),
            categorical_sections[0],
        )
        start, end, colors, _ = default_section
        add_token_with_evidence("palette.categorical", colors, start, end)
        # 首色即默认主色：覆盖“无 color 编码 / 单色序列”场景，否则仅有
        # color.range 规则时大量输入图不会发生任何可见改动。
        add_token_with_evidence("color.primary", colors[0], start, end)
        add_requirement_with_evidence(
            "L2",
            "存在多类别颜色编码时使用指南定义的默认分类色板",
            start,
            end,
            strength="should",
            when={"color_count": {"gte": 2}},
            then={"set": "color.range", "to": "{palette.categorical}"},
        )
        add_requirement_with_evidence(
            "L2",
            "单色序列使用分类色板首色作为主色",
            start,
            end,
            strength="should",
            when={"color_count": {"lte": 1}},
            then={"set": "mark.color", "to": "{color.primary}"},
        )
        dark_section = next(
            (item for item in categorical_sections if item[3] == "dark"),
            None,
        )
        if dark_section:
            dark_start, dark_end, dark_colors, _ = dark_section
            add_token_with_evidence(
                "palette.categorical_dark", dark_colors, dark_start, dark_end
            )

    # 设计系统常用表格列出 Primary / Secondary 色组，却不称其为
    # "categorical palette"（例如 Economist）。这仍是有证据的机构 token；
    # 为使 advisor 可以执行，按色组语义构成一个派生的工作色板，并明确标记
    # derived，不能伪装成指南逐字的图表用色命令。
    role_color_sections: dict[str, tuple[int, int, list[str]]] = {}
    active_role: str | None = None
    active_start = 0
    active_colors: list[str] = []

    def flush_role_colors() -> None:
        nonlocal active_role, active_start, active_colors
        if active_role and active_colors:
            role_color_sections[active_role] = (
                active_start,
                active_start + len(active_colors),
                list(dict.fromkeys(active_colors)),
            )
        active_role, active_start, active_colors = None, 0, []

    for line_no, line in enumerate(lines, 1):
        heading = _normalize_text(line).strip(":")
        if heading in {"primary", "secondary"}:
            flush_role_colors()
            active_role, active_start = heading, line_no
            continue
        if active_role:
            colors = _extract_color_literals(line)
            if colors:
                active_colors.extend(colors)
                continue
            # 表格的 Name/Hex/RGB 行不结束色组；遇到下一个普通章节再结束。
            if heading and not heading.startswith(("name", "font", "scale", "multiplier")):
                flush_role_colors()
    flush_role_colors()

    primary_section = role_color_sections.get("primary")
    secondary_section = role_color_sections.get("secondary")
    if primary_section:
        start, end, colors = primary_section
        # end 由色值数量近似，取实际包含色值的连续行作证据范围。
        end = max(start, next(
            (i for i in range(start, len(lines) + 1) if i >= start and any(_extract_color_literals(lines[i - 1]))),
            start,
        ))
        # 后续表格可能含无色 header，实际将范围延至最后一个有色值行。
        color_lines = [
            i for i in range(start, len(lines) + 1)
            if _extract_color_literals(lines[i - 1]) and (i == start or i - start < 20)
        ]
        if color_lines:
            end = max(i for i in color_lines if i < (secondary_section[0] if secondary_section else len(lines) + 1))
        add_token_with_evidence("color.primary", colors[0], start, end)
    if secondary_section:
        start, end, colors = secondary_section
        next_heading = next(
            (i for i in range(start + 1, len(lines) + 1) if _normalize_text(lines[i - 1]).strip(":") in {"greyscale", "canvas", "typography", "grid spacing"}),
            len(lines) + 1,
        )
        color_lines = [i for i in range(start, next_heading) if _extract_color_literals(lines[i - 1])]
        end = max(color_lines) if color_lines else end
        add_token_with_evidence("color.secondary", colors[0], start, end)

    if primary_section and secondary_section and not categorical_sections:
        p_start, _, primary_colors = primary_section
        s_start, s_end, secondary_colors = secondary_section
        palette = list(dict.fromkeys([*primary_colors, *secondary_colors]))
        if len(palette) >= 2:
            evidence_end = max(s_end, s_start)
            add_token_with_evidence("palette.categorical", palette, p_start, evidence_end)
            add_requirement_with_evidence(
                "L2",
                "多类别或多序列时以机构 primary/secondary 色组构成的工作色板保持一致",
                p_start,
                evidence_end,
                strength="should",
                when={"color_count": {"gte": 2}},
                then={"set": "color.range", "to": "{palette.categorical}"},
                derived=True,
                pattern_sources=[_line_ref(p_start, p_start), _line_ref(s_start, evidence_end)],
            )
            add_requirement_with_evidence(
                "L2",
                "单色序列使用机构 primary 色",
                p_start,
                evidence_end,
                strength="should",
                when={"color_count": {"lte": 1}},
                then={"set": "mark.color", "to": "{color.primary}"},
                derived=True,
                pattern_sources=[_line_ref(p_start, p_start), _line_ref(s_start, evidence_end)],
            )

    # 命名色阶色值 → 语义 token（color.purple-70），禁止把 706929c4 写入 path。
    for line_no, line in enumerate(lines, 1):
        named = _named_scale_token(line)
        if named:
            add_token_with_evidence(named[0], named[1], line_no, line_no)

    # 序列 / 发散 / 告警色板：章节标题担保语义，色值行格式与分类色板相同。
    def collect_palette_block(
        start_pred, stop_pred, path: str, min_colors: int = 3
    ) -> None:
        collecting = False
        block_start = 0
        block_end = 0
        colors: list[str] = []
        for line_no, line in enumerate(lines, 1):
            low = _normalize_text(line)
            if start_pred(low):
                collecting = True
                block_start = line_no
                colors = []
                continue
            if collecting and stop_pred(low):
                break
            if not collecting:
                continue
            found = _extract_color_literals(line)
            # IBM Carbon 的 palette 表通常使用 ``10edf5ff`` 这类 8 位 RGBA：
            # 前两位是色阶/alpha 标记，不能让整段 palette 因不匹配 6 位 hex 而丢失。
            named = _named_scale_token(line)
            if named:
                found.append(named[1])
            if found:
                colors.extend(found)
                block_end = line_no
        colors = list(dict.fromkeys(colors))
        if len(colors) >= min_colors and block_start and block_end:
            add_token_with_evidence(path, colors, block_start, block_end)

    collect_palette_block(
        lambda low: bool(re.search(r"\bsequential\s+palettes?\b", low)),
        lambda low: bool(
            re.search(r"\b(?:diverging|alert|categorical|qualitative)\s+palettes?\b", low)
        ),
        "palette.sequential",
    )
    collect_palette_block(
        lambda low: bool(re.search(r"\bdiverging\s+palettes?\b", low)),
        lambda low: bool(
            re.search(r"\b(?:alert|categorical|qualitative|sequential)\s+palettes?\b", low)
            or low.startswith("gradient use")
        ),
        "palette.diverging",
    )
    collect_palette_block(
        lambda low: bool(re.search(r"\balert\s+palette\b", low)),
        lambda low: bool(
            re.search(r"\bgradient\b", low)
            or re.search(r"\bcolor and texture\b", low)
        ),
        "palette.alert",
        min_colors=3,
    )

    # Fallback for Markdown subsection headings such as ``- Sequential palettes``:
    # the general collector may encounter an inline sentence mentioning another
    # palette before the actual subsection. Re-scan exact heading blocks so Carbon
    # sequential/diverging palettes are never silently omitted.
    for target, next_names in (
        ("palette.sequential", ("diverging palettes", "alert palette", "categorical palettes")),
        ("palette.diverging", ("alert palette", "categorical palettes", "gradient use")),
    ):
        start = next(
            (i for i, line in enumerate(lines, 1)
             if _normalize_text(line).strip("- ").strip().startswith(target.split(".", 1)[1] + " palettes")),
            0,
        )
        if not start:
            continue
        end = len(lines)
        for i in range(start + 1, len(lines) + 1):
            low = _normalize_text(lines[i - 1]).strip("- ").strip()
            if any(low.startswith(name) for name in next_names):
                end = i - 1
                break
        colors: list[str] = []
        color_lines: list[int] = []
        for i in range(start + 1, end + 1):
            named = _named_scale_token(lines[i - 1])
            if named:
                colors.append(named[1])
                color_lines.append(i)
        colors = list(dict.fromkeys(colors))
        if len(colors) >= 3 and color_lines:
            add_token_with_evidence(target, colors, start, max(color_lines))

    # Chart 类别 + Recommend chart → L2 prefer chart.type（对齐 Economist 图型适应）。
    current_intent: tuple[str, str, int] | None = None
    for line_no, line in enumerate(lines, 1):
        heading = _chart_section_heading(line)
        if heading:
            intent_value, when_key = heading
            current_intent = (intent_value, when_key, line_no)
            continue
        charts = _parse_recommended_charts(line)
        if not charts or not current_intent:
            continue
        intent_value, when_key, head_line = current_intent
        primary, *rest = charts
        then: dict[str, Any] = {"prefer": "chart.type", "to": primary}
        if rest:
            then["with"] = ", ".join(rest)
        add_requirement_with_evidence(
            "L2",
            f"当传播意图为{intent_value}时优先使用推荐图型（{', '.join(charts)}）",
            head_line,
            line_no,
            strength="should",
            when={when_key: intent_value},
            then=then,
            reason=f"指南为 {intent_value} 任务给出推荐图型",
        )

    # Design principle / Design Philosophy 行 → L3 philosophy（保留原文）。
    in_principle_section = False
    for line_no, line in enumerate(lines, 1):
        low = _normalize_text(line)
        if re.search(
            r"\b(?:design principles?|design philosophy|what makes .+ special)\b",
            low,
        ):
            in_principle_section = True
            continue
        if in_principle_section and re.match(
            r"^(?:visual standards|color|typography|chart|layout|when to use|"
            r"key advantages|perfect for|applicability)\b",
            low,
        ):
            in_principle_section = False
        clean = line.strip().lstrip("#*- ").strip()
        match = re.match(r"^([^:]{2,40}):\s*(.+)$", clean)
        if not match or len(match.group(2).strip()) < 40:
            continue
        title = match.group(1).strip()
        title_key = _normalize_text(title)
        if title_key in {
            "perfect for",
            "key advantages",
            "recommend chart",
            "recommended chart",
        }:
            continue
        if not (in_principle_section or _looks_like_philosophy_statement(clean)):
            continue
        quote = match.group(2).strip()
        fragment["requirements"].append(
            {
                "classification": "L3-philosophy",
                "requirement": quote,
                "title": title,
                "strength": "should",
                "when": {},
                "then": None,
                "reason": "",
                "evidence": {"lines": f"L{line_no}", "quote": clean},
            }
        )

    # 一些设计系统（如 Economist）把原则写成「bullet 标题 + 下一段解释」，
    # 而非 ``Title: body``。这类原文是 L3 叙事认同，不能因缺少冒号而遗漏。
    principle_section = False
    for index, line in enumerate(lines):
        low = _normalize_text(line.lstrip("#").strip()).strip(":")
        if low in {"principles", "design principles", "design philosophy"}:
            principle_section = True
            continue
        if principle_section and line.lstrip().startswith("#"):
            principle_section = False
        if not principle_section:
            continue
        match = re.match(r"^\s*-\s+([^:]{2,60})\s*$", line)
        if not match:
            continue
        title = match.group(1).strip()
        body_lines: list[str] = []
        end_index = index
        for following in range(index + 1, len(lines)):
            candidate = lines[following].strip()
            if not candidate:
                if body_lines:
                    break
                continue
            if candidate.startswith("-") or candidate.startswith("#"):
                break
            body_lines.append(candidate)
            end_index = following
        if not body_lines:
            continue
        quote = " ".join(body_lines)
        fragment["requirements"].append(
            {
                "classification": "L3-philosophy",
                "requirement": quote,
                "title": title,
                "strength": "should",
                "when": {},
                "then": None,
                "reason": "",
                "evidence": {
                    "lines": _line_ref(index + 1, end_index + 1),
                    "quote": "\n".join(lines[index : end_index + 1]),
                },
            }
        )

    # 字体比例/行高表属于全局 L1 token 与规则；尽管现有 VL action space
    # 不能无损表达整张比例表，也要保留给 advisor 的慢道裁决，避免只剩调色板。
    serif_line = next(
        (
            (line_no, line.strip())
            for line_no, line in enumerate(lines, 1)
            if "--ds-type-system-serif" in line
        ),
        None,
    )
    if serif_line:
        add_token_with_evidence(
            "font.family", "--ds-type-system-serif", serif_line[0], serif_line[0]
        )
    scale_line = find_line("Uses a Major Second scale")
    if scale_line:
        add_requirement_with_evidence(
            "L1",
            "所有字号使用 Major Second 字体比例，避免任意字号",
            scale_line[0],
            scale_line[0],
            strength="must",
            when={},
            then=None,
        )
    leading_line = find_line("Line-height (leading) multipliers")
    if leading_line:
        add_requirement_with_evidence(
            "L1",
            "行高使用指南定义的 leading 倍率以维持可读性与垂直节奏",
            leading_line[0],
            leading_line[0],
            strength="must",
            when={},
            then=None,
        )

    # 参考型无条件软规范 → L1 should/llm（范例 BBC 亦保留 should 级 L1）。
    soft_l1 = [
        (
            "标题应反映数据揭示的主要洞见，并保持简洁",
            "The title should reflect the main insight",
            "should",
            "标题陈述要点，避免冗长复述",
        ),
        (
            "尽可能在图上直接标注，避免过长图例",
            "use labels directly on the chart to avoid long legends",
            "should",
            "直接标注减少图例来回对照",
        ),
        (
            "禁止用渐变表示有意义的递变或发散",
            "Gradients should not be used to represent any meaningful progression",
            "never",
            "渐变不得冒充序列/发散色板",
        ),
    ]
    for requirement, needle, strength, reason in soft_l1:
        found = find_line(needle)
        if not found:
            continue
        line_no, line = found
        # 只用含 needle 的子句作证据，避免同行其它 when 从句触发条件重分类。
        clause = next(
            (
                part.strip()
                for part in re.split(r"(?<=[.。;；])\s+", line.strip())
                if needle.lower() in part.lower()
            ),
            line.strip(),
        )
        fragment["requirements"].append(
            {
                "classification": "L1",
                "requirement": requirement,
                "strength": strength,
                "when": {},
                "then": None,
                "reason": reason,
                "evidence": {"lines": f"L{line_no}", "quote": clause},
            }
        )

    single_legend = find_line("need a legend if it only presents one data category")
    if single_legend:
        line_no, line = single_legend
        clause = next(
            (
                part.strip()
                for part in re.split(r"(?<=[.。;；])\s+", line.strip())
                if "one data category" in part.lower()
            ),
            line.strip(),
        )
        fragment["requirements"].append(
            {
                "classification": "L2",
                "requirement": "单数据类别时不需要图例",
                "strength": "should",
                "when": {"color_count": {"lte": 1}},
                "then": None,
                "reason": "单类别图例无额外信息",
                "evidence": {"lines": f"L{line_no}", "quote": clause},
            }
        )

    # 比较/占比图数值轴从零：有明确 when，进入 L2。
    zero_line = find_line("Always start numerical axes at zero")
    if zero_line:
        add_requirement_with_evidence(
            "L2",
            "比较与占比类图表的数值轴必须从零开始",
            zero_line[0],
            zero_line[0],
            strength="must",
            when={"intent": ["comparison", "part-to-whole"]},
            then=None,
            reason="截断数值轴会夸大差异",
        )

    # “默认位于顶部/底部”是跨情境恒定且已有受控动作的规则；只解析明确 default，
    # 不把 dashboard/mobile 等情境示例提升为无条件规范。
    for line_no, line in enumerate(lines, 1):
        low = _normalize_text(line)
        if "legend" not in low or "default" not in low:
            continue
        orient_match = re.search(r"\b(?:top|bottom)\b", low)
        if not orient_match:
            continue
        orient = orient_match.group()
        add_requirement_with_evidence(
            "L1",
            f"图例默认置于图表{orient}",
            line_no,
            line_no,
            strength="must",
            when={},
            then={"set": "legend.orient", "to": orient},
        )
        break

    # 参考型指南常用“语义名称 + 值 / 简短祈使句”表达规范，而不是提供 theme
    # 源码。以下模式只接受明确角色、数值和动作词，避免把任意教程示例提升为规则。
    semantic_colors: dict[str, tuple[str, int]] = {}
    color_role_map = {
        "primary": "primary",
        "secondary": "secondary",
        "accent": "accent",
        "tertiary": "tertiary",
        "neutral": "neutral",
    }
    for line_no, line in enumerate(lines, 1):
        match = re.search(
            r"(?P<name>[A-Za-z][A-Za-z -]{1,40})\s*"
            r"\((?P<color>#[0-9a-fA-F]{6})\)\s*:\s*"
            r"(?P<role>primary|secondary|accent|tertiary|neutral)\b",
            line,
            re.I,
        )
        if not match:
            continue
        role = color_role_map[match.group("role").lower()]
        color = match.group("color").upper()
        semantic_colors.setdefault(role, (color, line_no))
        add_token_with_evidence(f"color.{role}", color, line_no, line_no)

    if len(semantic_colors) >= 2:
        ordered_roles = ("primary", "secondary", "accent", "tertiary", "neutral")
        palette = [semantic_colors[role][0] for role in ordered_roles if role in semantic_colors]
        palette_start = min(line_no for _, line_no in semantic_colors.values())
        palette_end = max(line_no for _, line_no in semantic_colors.values())
        add_token_with_evidence(
            "palette.categorical",
            palette,
            palette_start,
            palette_end,
        )

    # “Typography: Helvetica font family” 这类参考条目也属于明确命名 token。
    for line_no, line in enumerate(lines, 1):
        match = re.search(
            r"(?:typography\s*:\s*)?([A-Za-z][A-Za-z0-9 ]{1,30})\s+font family\b",
            line,
            re.I,
        )
        if match:
            family = match.group(1).strip()
            add_token_with_evidence("font.family", family, line_no, line_no)
            add_requirement_with_evidence(
                "L1",
                f"所有图表文字使用 {family} 字体",
                line_no,
                line_no,
                strength="must",
                when={},
                then={"set": "font.family", "to": "{font.family}"},
            )
            break

    size_roles = {
        "main title": "title",
        "title": "title",
        "subtitle": "subtitle",
        "body text": "body",
        "body": "body",
        "caption/source": "caption",
        "caption": "caption",
        "source": "caption",
    }
    reference_sizes: dict[str, int] = {}
    size_lines: list[int] = []
    for line_no, line in enumerate(lines, 1):
        match = re.search(
            r"[-*]?\s*(main title|title|subtitle|body text|body|caption/source|caption|source)"
            r"\s*:\s*(\d+)\s*(?:pt|px)\b",
            line,
            re.I,
        )
        if match:
            reference_sizes[size_roles[match.group(1).lower()]] = int(match.group(2))
            size_lines.append(line_no)
    if reference_sizes:
        for role, value in reference_sizes.items():
            evidence_line = next(
                line_no
                for line_no in size_lines
                if re.search(
                    rf"\b{re.escape(role.replace('_', ' '))}\b|\b{value}\s*(?:pt|px)\b",
                    lines[line_no - 1],
                    re.I,
                )
            )
            add_token_with_evidence(f"font.size.{role}", value, evidence_line, evidence_line)
        add_requirement_with_evidence(
            "L1",
            "使用指南定义的标题、副标题、正文和来源字号层级",
            min(size_lines),
            max(size_lines),
            strength="must",
            when={},
            then={"set": "font.sizes", "to": reference_sizes},
        )

    # 明确、无条件且可映射到受控动作的参考型规则。
    add_requirement(
        "L1",
        "所有文字元素左对齐",
        "Left-align all text elements",
        strength="must",
        then={"set": "title.anchor", "to": "start"},
    )
    add_requirement(
        "L1",
        "图表必须包含来源署名",
        "Always include source attribution",
        strength="must",
        then={"set": "source.required", "to": True},
    )
    grid_line = find_line("Horizontal gridlines only")
    if grid_line:
        grid_match = _HEX.search(grid_line[1])
        if grid_match:
            add_token_with_evidence(
                "color.grid", grid_match.group().lower(), grid_line[0], grid_line[0]
            )
        add_requirement_with_evidence(
            "L1",
            "仅保留水平网格线并使用指南网格色",
            grid_line[0],
            grid_line[0],
            strength="must",
            when={},
            then={"set": "grid.horizontal", "to": "{color.grid}"},
        )
    add_requirement(
        "L1",
        "禁止显示垂直网格线",
        "No vertical gridlines",
        strength="never",
        then={"set": "grid.vertical", "to": False},
    )
    add_requirement(
        "L1",
        "图例默认置于图表顶部",
        "Top position is",
        strength="must",
        then={"set": "legend.orient", "to": "top"},
    )
    add_requirement(
        "L1",
        "默认移除图例标题",
        "Remove legend titles",
        strength="must",
        then={"set": "legend.title", "to": None},
    )

    # 显式“情境: 动作”条目编译为受控 L2，而不是保留 condition/string then。
    if "primary" in semantic_colors:
        primary = semantic_colors["primary"][0]
        add_requirement(
            "L2",
            f"单序列使用机构主色 {primary}",
            "Single Series:",
            strength="should",
            when={"series_count": 1},
            then={"set": "mark.color", "to": "{color.primary}"},
        )
    secondary_role = "secondary" if "secondary" in semantic_colors else "accent"
    if "primary" in semantic_colors and secondary_role in semantic_colors:
        add_requirement(
            "L2",
            "双序列使用机构主色与辅助色组合",
            "Two Series:",
            strength="should",
            when={"series_count": 2},
            then={
                "set": "color.range",
                "to": [
                    semantic_colors["primary"][0],
                    semantic_colors[secondary_role][0],
                ],
            },
        )
    if len(semantic_colors) >= 3:
        add_requirement(
            "L2",
            "多序列使用完整机构分类色板",
            "Multiple Series:",
            strength="should",
            when={"series_count": {"gte": 3}},
            then={"set": "color.range", "to": "{palette.categorical}"},
        )
    if secondary_role in semantic_colors:
        add_requirement(
            "L2",
            "需要强调时使用机构强调色",
            "Highlighting:",
            strength="should",
            when={"intent": "emphasis"},
            then={
                "set": "emphasized-mark.color",
                "to": f"{{color.{secondary_role}}}",
            },
        )
    if "neutral" in semantic_colors:
        add_requirement(
            "L2",
            "辅助数据使用机构中性色",
            "Neutrality:",
            strength="should",
            when={"data_role": "supporting"},
            # 当前动作词汇无法定位“辅助序列”；禁止退化成整图 mark.color，
            # 否则会覆盖主色与强调色。保留自然语言交慢道/人工确认。
            then=None,
        )
    size_line = next(
        (
            (line_no, line)
            for line_no, line in enumerate(lines, 1)
            if re.search(r"\b\d+\s*[×x]\s*\d+\s*px\b.*\bdigital\b", line, re.I)
        ),
        None,
    )
    if size_line:
        dimensions = re.search(r"(\d+)\s*[×x]\s*(\d+)\s*px", size_line[1], re.I)
        if dimensions:
            add_requirement_with_evidence(
                "L2",
                "数字媒介使用标准图表尺寸",
                size_line[0],
                size_line[0],
                strength="should",
                when={"medium": "digital"},
                then={
                    "set": "chart.size",
                    "to": f"{dimensions.group(1)}x{dimensions.group(2)}",
                },
            )

    # 带明确原则标签的价值宣言属于 L3，而非 L1 must。
    philosophy_labels = (
        "Clarity First:",
        "Accessibility:",
        "Professional Consistency:",
        "Editorial Integrity:",
    )
    for label in philosophy_labels:
        found = find_line(label)
        if found:
            statement = found[1].split(":", 1)[-1].strip()
            add_requirement_with_evidence(
                "L3-philosophy",
                statement,
                found[0],
                found[0],
                strength="should",
                when={},
                then=None,
            )

    # 显式命名的主/辅色属于 L1 design tokens；若原文同时给出无条件 must，
    # 生成同证据的 L1 可执行规则。此路径适用于设计系统文本，不依赖机构名称。
    named_colors: dict[str, tuple[str, int]] = {}
    for line_no, line in enumerate(lines, 1):
        match = re.search(
            r"\b(primary|main|secondary|accent)\s+colou?r\b[^#]*(#[0-9a-fA-F]{6})\b",
            line,
            re.I,
        )
        if not match:
            continue
        raw_role, color = match.group(1).lower(), match.group(2).upper()
        role = "primary" if raw_role in ("primary", "main") else ("accent" if raw_role == "accent" else "secondary")
        named_colors.setdefault(role, (color, line_no))
        add_token_with_evidence(f"color.{role}", color, line_no, line_no)
        low = line.lower()
        if role == "primary" and any(hint in low for hint in _STRONG_HINTS):
            add_requirement_with_evidence(
                "L1",
                f"主序列恒定使用机构主色 {color}",
                line_no,
                line_no,
                strength="must",
                when={},
                then={"set": "mark.color", "to": "{color.primary}"},
            )

    if "primary" in named_colors and "secondary" in named_colors:
        primary, primary_line = named_colors["primary"]
        secondary, secondary_line = named_colors["secondary"]
        secondary_text = lines[secondary_line - 1]
        if "comparison" in secondary_text.lower() or "比较" in secondary_text:
            add_requirement_with_evidence(
                "L2",
                "比较任务使用机构主色与辅色组合",
                min(primary_line, secondary_line),
                max(primary_line, secondary_line),
                strength="should",
                when={"context": "comparisons" if "comparison" in secondary_text.lower() else "比较"},
                then={"set": "color.range", "to": [primary, secondary]},
            )

    # 机构 cookbook 常以重复代码模式表达色板，而不是显式写 “primary”。
    # 只有跨多个图表重复出现才推导角色，并以 derived + pattern_sources 留痕；
    # 单个示例仍由 LLM 归入 evidence_catalog.examples。
    color_occurrences: dict[str, list[int]] = {}
    manual_palettes: list[tuple[int, list[str]]] = []
    for line_no, line in enumerate(lines, 1):
        colors = _HEX.findall(line)
        if not colors:
            continue
        low = line.lower()
        if re.search(r"scale_(?:colour|color|fill)_manual", low):
            manual_palettes.append((line_no, colors))
        if any(marker in low for marker in ("geom_", "scale_colour_manual", "scale_color_manual", "scale_fill_manual")):
            if any(excluded in low for excluded in ("geom_hline", "geom_vline", "panel.grid", "element_text")):
                continue
            for color in colors:
                color_occurrences.setdefault(color.upper(), []).append(line_no)

    ranked_colors = sorted(
        ((color, refs) for color, refs in color_occurrences.items() if len(refs) >= 2),
        key=lambda item: (-len(item[1]), item[1][0]),
    )
    if ranked_colors:
        primary, primary_lines = ranked_colors[0]
        add_token_with_evidence(
            "color.primary",
            primary,
            primary_lines[0],
            primary_lines[0],
            evidence_kind="repeated-pattern",
            pattern_sources=[f"L{line_no}" for line_no in primary_lines],
        )
        if len(ranked_colors) > 1:
            accent, accent_lines = ranked_colors[1]
            add_token_with_evidence(
                "color.accent",
                accent,
                accent_lines[0],
                accent_lines[0],
                evidence_kind="repeated-pattern",
                pattern_sources=[f"L{line_no}" for line_no in accent_lines],
            )

        single_heading = find_line("## Make a line chart")
        single_use = next(
            (
                (i, line)
                for i, line in enumerate(lines, 1)
                if single_heading
                and i >= single_heading[0]
                and primary.lower() in line.lower()
                and "geom_line" in line.lower()
            ),
            None,
        )
        if single_heading and single_use:
            add_requirement_with_evidence(
                "L2",
                f"单序列图使用机构主色 {primary}",
                single_heading[0],
                single_use[0],
                strength="should",
                when={"series_count": 1},
                then={"set": "mark.color", "to": "{color.primary}"},
                reason="该主色在多种单序列图示中重复形成可识别的一致性",
                derived=True,
                pattern_sources=[f"L{line_no}" for line_no in primary_lines],
            )

    if manual_palettes:
        palette_counts: dict[tuple[str, ...], list[int]] = {}
        for line_no, colors in manual_palettes:
            key = tuple(color.upper() for color in colors)
            palette_counts.setdefault(key, []).append(line_no)
        palette, palette_lines = max(
            palette_counts.items(),
            key=lambda item: (len(item[0]), len(item[1])),
        )
        evidence_line = palette_lines[0]
        add_token_with_evidence(
            "palette.categorical",
            list(palette),
            evidence_line,
            evidence_line,
            evidence_kind="repeated-pattern",
            pattern_sources=[f"L{line_no}" for line_no in palette_lines],
        )
        if len(palette) >= 2:
            multiple_heading = find_line("## Make a multiple line chart")
            two_series_line = next(
                (line_no for line_no, colors in manual_palettes if len(colors) == 2),
                None,
            )
            if multiple_heading and two_series_line:
                add_token_with_evidence(
                    "palette.two_series",
                    [_HEX.findall(lines[two_series_line - 1])[0].upper(), _HEX.findall(lines[two_series_line - 1])[1].upper()],
                    two_series_line,
                    two_series_line,
                    evidence_kind="repeated-pattern",
                    pattern_sources=[
                        f"L{line_no}" for line_no, colors in manual_palettes if len(colors) == 2
                    ],
                )
                add_requirement_with_evidence(
                    "L2",
                    "双序列图使用指南中重复出现的双色组合",
                    multiple_heading[0],
                    two_series_line,
                    strength="should",
                    when={"series_count": 2},
                    then={"set": "color.range", "to": "{palette.two_series}"},
                    reason="双色组合在多序列折线图和分组图中重复使用",
                    derived=True,
                    pattern_sources=[
                        f"L{line_no}" for line_no, colors in manual_palettes if len(colors) == 2
                    ],
                )

    font = find_line('font <- "')
    if font:
        match = re.search(r'font\s*<-\s*"([^"]+)"', font[1])
        if match:
            family = match.group(1)
            add_token("font.family", family, 'font <- "')
            add_requirement(
                "L1",
                f"所有图表文字使用 {family} 字体",
                'font <- "',
                strength="must",
                then={"set": "font.family", "to": "{font.family}"},
            )

    # ggplot theme 源码中的标题/副标题/图例/轴字号是明确默认值。
    size_patterns = {
        "title": ("plot.title", r"size\s*=\s*(\d+)"),
        "subtitle": ("size = 28", r"plot\.subtitle.*?size\s*=\s*(\d+)"),
        "legend_label": ("legend.text =", r"size\s*=\s*(\d+)"),
        "axis_label": ("axis.text =", r"size\s*=\s*(\d+)"),
    }
    extracted_sizes: dict[str, int] = {}
    for role, (needle, pattern) in size_patterns.items():
        found = find_line(needle)
        if not found:
            continue
        line_no, line = found
        # subtitle 的声明跨两行，向后合并一行再匹配。
        segment = " ".join(lines[line_no - 1 : min(line_no + 1, len(lines))])
        match = re.search(pattern, segment)
        if match:
            value = int(match.group(1))
            extracted_sizes[role] = value
            end_line = min(line_no + 1, len(lines))
            fragment["tokens"].append(
                {
                    "path": f"font.size.{role}",
                    "value": value,
                    "evidence": {
                        "lines": _line_ref(line_no, end_line),
                        "quote": "\n".join(lines[line_no - 1 : end_line]),
                    },
                }
            )
    if extracted_sizes:
        block_start = find_line("plot.title")
        block_end = find_line("axis.text =")
        if block_start and block_end:
            start_no, end_no = block_start[0], min(block_end[0] + 1, len(lines))
            fragment["requirements"].append(
                {
                    "classification": "L1",
                    "requirement": "使用指南定义的标题、副标题、图例和坐标轴字号层级",
                    "strength": "must",
                    "when": {},
                    "then": {"set": "font.sizes", "to": extracted_sizes},
                    "reason": "",
                    "evidence": {
                        "lines": _line_ref(start_no, end_no),
                        "quote": "\n".join(lines[start_no - 1 : end_no]),
                    },
                }
            )

    add_requirement(
        "L1",
        "图例默认置于图表顶部",
        'legend.position = "top"',
        strength="must",
        then={"set": "legend.orient", "to": "top"},
    )
    add_requirement(
        "L1",
        "默认移除图例标题",
        "legend.title = ggplot2::element_blank()",
        strength="must",
        then={"set": "legend.title", "to": None},
    )
    add_token("color.grid", "#cbcbcb", "panel.grid.major.y")
    add_requirement(
        "L1",
        "仅保留水平网格线并使用指南网格色",
        "panel.grid.major.y",
        strength="must",
        then={"set": "grid.horizontal", "to": "{color.grid}"},
    )
    add_requirement(
        "L1",
        "默认不显示垂直网格线",
        "panel.grid.major.x = ggplot2::element_blank()",
        strength="must",
        then={"set": "grid.vertical", "to": False},
    )
    add_requirement(
        "L1",
        "标题与副标题左对齐",
        "left-aligns the title and subtitle",
        strength="must",
        then={"set": "title.anchor", "to": "start"},
    )
    add_requirement(
        "L1",
        "图表应包含以 Source: 开头的数据来源署名",
        'type the word `"Source:"`',
        strength="must",
        then={"set": "source.required", "to": True},
    )
    add_requirement(
        "L1",
        "发布图表默认尺寸为 640×450 像素",
        "width_pixels = 640, height_pixels = 450",
        strength="must",
        then={"set": "chart.size", "to": "640x450"},
    )
    add_requirement(
        "L1",
        "优先使用直接文字标注，而不是仅依赖图例",
        "better to label data directly",
        then=None,
        reason="直接标注能减少读者在图例与图形之间来回对应",
    )

    add_requirement(
        "L2",
        "堆叠图表达比例时使用 fill 位置模式",
        '`position = "fill"` will draw your stacks as proportions',
        when={"context": "proportions"},
        then=None,
    )
    add_requirement(
        "L2",
        "堆叠图表达实际数值时使用 identity 位置模式",
        '`position = "identity"` will draw number values',
        when={"context": "number values"},
        then=None,
    )
    add_requirement(
        "L2",
        "小多重图默认保持统一 y 轴尺度；必要时才允许独立尺度",
        "fixed axis scales across the small multiples",
        when={"context": "small multiples"},
        then=None,
        reason="统一尺度可避免误导性比较",
    )

    add_requirement(
        "L3-story",
        "BBC 图表主题由设计团队的建议与反馈形成。",
        "recommendations and feedback from the design team",
    )
    add_requirement(
        "L3-philosophy",
        "通过可复现流程创建可发布的机构风格图形，并降低新用户制作门槛。",
        "publication-ready graphics in our in-house style",
    )
    return fragment


def _evidence(candidate: dict, source_lines: list[str]) -> tuple[str, str] | None:
    raw = candidate.get("evidence")
    if not isinstance(raw, dict):
        return None
    ref = str(raw.get("lines") or "").strip()
    quote = str(raw.get("quote") or "").strip()
    if not ref or not quote or any(p in ref.lower() or p in quote.lower() for p in _PLACEHOLDERS):
        return None
    match = _LINE_REF.fullmatch(ref)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1 or end < start or end > len(source_lines):
        return None
    segment = "\n".join(source_lines[start - 1 : end])
    qn, sn = _normalize_text(quote), _normalize_text(segment)
    # 短 token 允许精确包含；较长证据至少须与指定行双向包含。
    if not qn or (qn not in sn and sn not in qn):
        return None
    return _line_ref(start, end), quote


def _token_is_grounded(path: str, value: Any, quote: str, evidence_kind: str = "direct") -> bool:
    if value is None:
        return False
    q = _normalize_text(quote)
    if path == "font.family":
        return isinstance(value, str) and _normalize_text(value) in q
    if path.startswith("font.size."):
        role = path.rsplit(".", 1)[-1].replace("_label", "").replace("_", " ")
        return (
            bool(re.search(r"\d+", str(value)))
            and str(value) in q
            and role.split()[0] in q
        )
    if path.startswith("color."):
        if not isinstance(value, str):
            return False
        normalized_value = value.strip()
        is_hex = bool(_HEX.fullmatch(normalized_value))
        is_alias = bool(_TOKEN_REF.fullmatch(normalized_value))
        is_css_var = bool(_CSS_VAR.fullmatch(normalized_value))
        if not (is_hex or is_alias or is_css_var):
            return False
        grounded_value = normalized_value.lower().strip("{}")
        # 颜色必须与从原文提取并规范化后的完整色值精确一致，不能只做子串
        # 匹配。否则 IBM 的 ``Red 60da1e28`` 会错误接受模型幻觉的
        # ``#60DA1E``（它只是色阶串的前六位）而非正确的 ``#DA1E28``。
        if is_hex:
            quoted_colors = {color.lower() for color in _extract_color_literals(quote)}
            if grounded_value not in quoted_colors:
                return False
        elif grounded_value not in q and grounded_value.lstrip("#") not in q:
            return False
        if not is_hex:
            # 语义 alias / CSS 变量的路径和值已在原文出现即可，角色由令牌树本身表达。
            return path.rsplit(".", 1)[-1].lower() in q or path.lower() in q
        role = path.rsplit(".", 1)[-1]
        hints = {
            "primary": ("primary", "main", "default"),
            "secondary": ("secondary", "supporting"),
            "accent": ("accent", "highlight", "emphasis"),
            "background": ("background",),
            "grid": ("grid",),
            "text": ("text", "title", "axis", "legend"),
        }
        if role not in hints or any(hint in q for hint in hints[role]):
            return True
        if role == "primary" and "series" in q and any(
            marker in q for marker in ("blue", "colour", "color", "fill")
        ):
            return True
        # 分类/定性色板章节的首色可担保为 primary，即使原文未写 “primary”。
        if role == "primary" and any(
            marker in q
            for marker in ("categorical", "qualitative", "palette", "色板")
        ):
            return True
        # 重复出现的机构代码模式可以担保角色推导；单个示例不放宽。
        return evidence_kind == "repeated-pattern" and any(
            marker in q for marker in ("colour", "color", "fill", "values")
        )
    if path.startswith("palette."):
        quoted_colors = {color.lower() for color in _extract_color_literals(quote)}
        return (
            isinstance(value, list)
            and len(value) >= 2
            and all(
                isinstance(v, str)
                and (_HEX.fullmatch(v) or _TOKEN_REF.fullmatch(v) or _CSS_VAR.fullmatch(v))
                and (
                    v.lower() in quoted_colors
                    if _HEX.fullmatch(v)
                    else (
                        v.lower().strip("{}") in q
                        or v.lower().strip("{}").lstrip("#") in q
                    )
                )
                for v in value
            )
        )
    return False


def _set_token(tokens: dict, path: str, value: Any, quote: str, evidence_kind: str = "direct") -> bool:
    path = _sanitize_token_path(path) or ""
    value = _normalize_token_value(path, value)
    parts = [p for p in path.split(".") if re.fullmatch(r"[a-zA-Z0-9_-]+", p)]
    if not parts or len(parts) > 6 or not _token_is_grounded(path, value, quote, evidence_kind):
        return False
    node = tokens
    for part in parts[:-1]:
        existing = node.setdefault(part, {})
        if not isinstance(existing, dict):
            return False
        node = existing
    node.setdefault(parts[-1], value)
    return True


def _then_supported(then: Any) -> bool:
    if not isinstance(then, dict):
        return False
    verb = next((v for v in ("set", "prefer", "override") if v in then), None)
    return bool(verb and str(then.get(verb)) in _SUPPORTED_TARGETS)


# LLM 常把散文意图槽化为 comparison/trend；原文未必出现该词本身。
_INTENT_GROUNDING_ALIASES: dict[str, tuple[str, ...]] = {
    "comparison": (
        "comparison", "compare", "comparing", "compared", "categories",
        "proportions", "relative proportions", "对比", "比较",
    ),
    "trend": (
        "trend", "trends", "over time", "change over time", "changes over time",
        "overall trends", "趋势", "随时间",
    ),
    "correlation": (
        "correlation", "correlate", "relate", "relationship", "relationships",
        "outliers", "clusters", "scatter", "相关", "离群",
    ),
    "composition": (
        "composition", "part to whole", "parts of a whole", "stacked",
        "proportions", "构成", "占比",
    ),
    "distribution": ("distribution", "histogram", "spread", "分布"),
}


def _condition_is_grounded(when: dict, quote: str) -> bool:
    """拦截由示例数据臆造的主题/意图条件；结构条件由明确措辞担保。

    intent 允许近义短语（compare→comparison），以配合 LLM 整编后的受控槽位。
    """
    if not when:
        return True
    q = _normalize_text(quote)
    q_flex = q.replace("-", " ")

    def value_in_quote(raw: Any) -> bool:
        v = _normalize_text(raw)
        v_flex = v.replace("-", " ")
        return (
            v in q
            or v_flex in q_flex
            or v.rstrip("s") in q
            or (v + "s") in q
            or v_flex.rstrip("s") in q_flex
        )

    def intent_in_quote(raw: Any) -> bool:
        v = _normalize_text(raw)
        if value_in_quote(v):
            return True
        for alias in _INTENT_GROUNDING_ALIASES.get(v, ()):
            if alias in q or alias in q_flex:
                return True
        return False

    for key, value in when.items():
        if key == "intent":
            values = value if isinstance(value, list) else [value]
            if not any(intent_in_quote(v) for v in values):
                return False
            continue
        if key in ("data_topic", "data_role", "context", "task", "audience", "comparison"):
            values = value if isinstance(value, list) else [value]
            if not any(value_in_quote(v) for v in values):
                return False
        if key == "series_count":
            if not any(
                word in q
                for word in (
                    "single", "one series", "two series", "multiple",
                    "单序列", "双序列", "多序列",
                )
            ):
                return False
    return True


def _when_is_tautological(when: dict, quote: str, requirement: str = "") -> bool:
    """整句回填为 context 的“假条件”：没有真实情境槽位，不能升格为 L2。"""
    if not isinstance(when, dict) or set(when) != {"context"}:
        return False
    ctx = _normalize_text(when.get("context"))
    if not ctx:
        return False
    return ctx in {_normalize_text(quote), _normalize_text(requirement)}


def _looks_like_condition(text: str) -> bool:
    return _contains_any_term(text, _CONDITION_HINTS)


def _is_hedge_only_condition(text: str) -> bool:
    """when/if possible 是语气缓和，不是 McAdams 意义上的情境 when。"""
    normalized = _normalize_text(text)
    return bool(re.match(r"^(?:when|if)\s+possible\b", normalized))


def _looks_like_philosophy_statement(text: str) -> bool:
    """识别带原则标签的抽象价值宣言，防止被模型误标为 L1 must。"""
    normalized = _normalize_text(text)
    labels = (
        "clarity first:",
        "accessibility:",
        "professional consistency:",
        "editorial integrity:",
        "design philosophy:",
        "understandable:",
        "essential:",
        "impactful:",
        "consistent:",
        "contextual:",
        "less is more:",
    )
    if normalized.startswith(labels):
        return True
    # 通用“原则名: 长句宣言”——排除规则条款、图型推荐、色板与轴规范标题。
    match = re.match(r"^([a-z][a-z0-9 -]{2,40}):\s+(.{60,})$", normalized)
    if not match:
        return False
    title, body = match.group(1), match.group(2)
    blocked_titles = (
        "recommend chart", "recommended chart", "recommend charts",
        "axes and labels", "alert palette", "gradient use",
        "consistent increments", "when starting at non-zero is bad",
        "when starting at non-zero is good", "title, labels and legend",
        "emphasize the story you want to tell",
        "improve readability and hierarchy of elements",
        "texture and markers", "represent quantity",
        "perfect for", "key advantages",
    )
    if title in blocked_titles or title.startswith("recommend"):
        return False
    if _HEX.search(text) or re.search(r"\b\d+\s*(?:pt|px)\b", normalized):
        return False
    action_markers = (
        "set ", "use #", "font family", "legend", "gridline", "palette",
        "mark.color", "color.range", "recommend chart", "axis", "tick",
    )
    return not any(marker in body for marker in action_markers)


def _looks_like_rationale(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in _RATIONALE_HINTS)


def _looks_like_example(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(
        marker in normalized
        for marker in ("example:", "for example", "e.g.", "示例", "例如")
    )


def _unique_id(prefix: str, text: str, used: set[str]) -> str:
    base = slugify(text)[:42] or "requirement"
    candidate = f"{prefix}-{base}"
    n = 2
    while candidate in used:
        candidate = f"{prefix}-{base}-{n}"
        n += 1
    used.add(candidate)
    return candidate


def _then_counts_as_executable_for_gate(persona: Any, then: Any, facts: dict) -> bool:
    """质量门计数：与 prefer_mode 解耦；受控 prefer chart.type 即使 suggest 也算可执行。"""
    from .actions import (
        CHART_TYPE_MARK_ALIASES,
        EXECUTABLE_MARKS,
        _normalize_chart_type_key,
        compile_then,
    )

    compiled = compile_then(persona, then, facts)
    if compiled.get("ops"):
        return True
    if not isinstance(then, dict):
        return False
    verb = None
    target = None
    for key in ("prefer", "set", "override"):
        if key in then:
            verb, target = key, then.get(key)
            break
    if target != "chart.type":
        return False
    chart_type = _normalize_chart_type_key(then.get("to"))
    mark_type = CHART_TYPE_MARK_ALIASES.get(chart_type, chart_type)
    return bool(verb and mark_type in EXECUTABLE_MARKS)


def _candidates_digest_for_organization(fragments: list[dict], *, limit: int = 72) -> dict:
    """压缩分块结果供 LLM 整编（控制 token）。"""
    tokens: list[dict] = []
    requirements: list[dict] = []
    seen_tok: set[str] = set()
    seen_req: set[str] = set()
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        for token in fragment.get("tokens") or []:
            if not isinstance(token, dict):
                continue
            path = str(token.get("path") or "").strip()
            key = f"{path}|{token.get('value')}"
            if not path or key in seen_tok:
                continue
            seen_tok.add(key)
            tokens.append(token)
        for req in fragment.get("requirements") or []:
            if not isinstance(req, dict):
                continue
            quote = ""
            ev = req.get("evidence") if isinstance(req.get("evidence"), dict) else {}
            quote = str(ev.get("quote") or req.get("requirement") or "")[:180]
            key = f"{req.get('classification')}|{quote.lower()}"
            if key in seen_req:
                continue
            seen_req.add(key)
            requirements.append(req)
            if len(requirements) >= limit:
                break
        if len(requirements) >= limit:
            break
    structured = {}
    for key in ("diagnostics", "chart_type_guidance", "palette_guidance", "conflicts"):
        values = []
        seen = set()
        for fragment in fragments:
            for item in (fragment.get(key) or []) if isinstance(fragment, dict) else []:
                if not isinstance(item, dict):
                    continue
                marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if marker not in seen:
                    seen.add(marker)
                    values.append(item)
        structured[key] = values[:40]
    return {"tokens": tokens[:40], "requirements": requirements[:limit], **structured}


async def _organize_with_llm(
    name: str,
    fragments: list[dict],
    llm: LLMClient,
) -> dict | None:
    """LLM 整编分块候选 → 统一 tokens/requirements；失败返回 None。"""
    digest = _candidates_digest_for_organization(fragments)
    if not digest["requirements"] and not digest["tokens"]:
        return None
    user = json.dumps(
        {
            "institution_name": name,
            "task": "Organize extracted candidates into a clean persona draft.",
            "candidates": digest,
        },
        ensure_ascii=False,
    )
    raw = await llm.chat_json(ORGANIZATION_GUIDE, user)
    if not isinstance(raw, dict):
        return None
    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), list) else []
    requirements = raw.get("requirements") if isinstance(raw.get("requirements"), list) else []
    if not tokens and not requirements:
        return None
    return {
        "tokens": tokens,
        "requirements": requirements,
        "diagnostics": raw.get("diagnostics") if isinstance(raw.get("diagnostics"), list) else [],
        "chart_type_guidance": raw.get("chart_type_guidance") if isinstance(raw.get("chart_type_guidance"), list) else [],
        "palette_guidance": raw.get("palette_guidance") if isinstance(raw.get("palette_guidance"), list) else [],
        "conflicts": raw.get("conflicts") if isinstance(raw.get("conflicts"), list) else [],
        "organization": True,
    }


def _assemble_persona(
    name: str,
    text: str,
    fragments: list[dict],
    chunk_count: int,
    llm_chunks_succeeded: int | None = None,
) -> tuple[dict, list[str]]:
    source_lines = text.splitlines()
    warnings: list[str] = []
    tokens: dict = {}
    token_sources: dict[str, dict] = {}
    accepted: list[dict] = []
    rejected = 0
    structured: dict[str, list] = {
        "diagnostics": [], "chart_type_guidance": [], "palette_guidance": [], "conflicts": []
    }

    for fragment in fragments:
        if isinstance(fragment, dict):
            for key in structured:
                for value in fragment.get(key) or []:
                    if isinstance(value, dict):
                        marker = json.dumps(value, sort_keys=True, ensure_ascii=False)
                        if not any(json.dumps(x, sort_keys=True, ensure_ascii=False) == marker for x in structured[key]):
                            structured[key].append(value)
        for token in fragment.get("tokens") or []:
            if not isinstance(token, dict):
                rejected += 1
                continue
            ev = _evidence(token, source_lines)
            path = str(token.get("path") or "").strip()
            evidence_kind = str(token.get("evidence_kind") or "direct")
            if ev and _set_token(tokens, path, token.get("value"), ev[1], evidence_kind):
                token_sources.setdefault(
                    path,
                    {
                        "src": ev[0],
                        "quote": ev[1],
                        "evidence_kind": evidence_kind,
                        "pattern_sources": token.get("pattern_sources") or [],
                    },
                )
            else:
                rejected += 1
        for req in fragment.get("requirements") or []:
            if not isinstance(req, dict):
                rejected += 1
                continue
            ev = _evidence(req, source_lines)
            requirement = str(req.get("requirement") or "").strip()
            classification = str(req.get("classification") or "").strip()
            if not ev or len(requirement) < 5 or classification not in {
                "L1", "L2", "L3-philosophy", "L3-story", "example", "unmapped"
            }:
                rejected += 1
                continue
            when = req.get("when") if isinstance(req.get("when"), dict) else {}
            strength = str(req.get("strength") or "should").lower()
            scope = str(req.get("scope") or "chart").strip().lower()
            if scope not in {"chart", "visual-strategy", "component-assembly"}:
                scope = "chart"
            visual_issues = [str(x).lower() for x in (req.get("visual_issues") or []) if str(x).lower() in _PARSER_VISUAL_ISSUES]
            visual_actions = [str(x) for x in (req.get("actions") or []) if str(x) in _PARSER_VISUAL_ACTIONS]
            is_visual_strategy = scope == "visual-strategy" and bool(visual_issues and visual_actions)
            is_component_assembly = scope == "component-assembly"
            if scope == "visual-strategy" and not is_visual_strategy:
                warnings.append(f"{ev[0]}：visual-strategy 缺少受限 issue/actions，已作为普通 L2 保留")
                scope = "chart"
            if is_component_assembly:
                # 组件重组只处理运行时已确认的混合像素布局；不得由 parser 生成任意几何参数。
                when = {"pixel_positioned_text": True}
            if (is_visual_strategy or is_component_assembly) and classification != "L2":
                classification = "L2"
            derived_pattern = bool(req.get("derived")) and len(req.get("pattern_sources") or []) >= 2

            # 确定性片段先进入装配；同一逐字证据若已有等价项，或已有可执行映射，
            # 忽略模型重复生成的自然语言版本，避免同一规范同时出现 applied/suggested。
            duplicate = next(
                (
                    item
                    for item in accepted
                    if _normalize_text(item.get("evidence_quote")) == _normalize_text(ev[1])
                    and (
                        _normalize_text(item.get("requirement"))
                        == _normalize_text(requirement)
                        or (
                            _then_supported(item.get("then"))
                            and not _then_supported(req.get("then"))
                        )
                    )
                ),
                None,
            )
            if duplicate:
                continue

            # 三层分类门：程序不信任模型给出的标签，按条件/强度/叙事职责重判。
            if (
                classification == "L1"
                and not _then_supported(req.get("then"))
                and _looks_like_philosophy_statement(ev[1])
            ):
                warnings.append(f"{ev[0]}：抽象原则不属于 L1，已重分类为 L3-philosophy")
                classification = "L3-philosophy"
                when = {}
                req["then"] = None

            if classification == "L1" and (when or _looks_like_condition(ev[1])):
                if not when and _is_hedge_only_condition(ev[1]):
                    # “When possible, …” 保留为无条件 should，不升格假 L2。
                    pass
                elif (when and _condition_is_grounded(when, ev[1])) or derived_pattern:
                    warnings.append(f"{ev[0]}：L1 含情境条件，已重分类为 L2")
                    classification = "L2"
                elif _looks_like_example(ev[1]):
                    warnings.append(f"{ev[0]}：示例条件不得提升为规范，已归入 evidence catalog")
                    classification, when = "example", {}
                    req["then"] = None
                else:
                    warnings.append(f"{ev[0]}：条件缺少原文担保，已保留为 unmapped requirement")
                    classification, when = "unmapped", {}
                    req["then"] = None

            if classification == "L2":
                if not when and _looks_like_condition(ev[1]):
                    when = {"context": ev[1]}
                # 整句当 context 不是真实情境槽位；若同时无可执行 then，降为 unmapped，
                # 避免启发式/LLM 把含 when/if 的长句刷成大量无效 L2。
                if _when_is_tautological(when, ev[1], requirement) and not _then_supported(
                    req.get("then")
                ) and not (is_visual_strategy or is_component_assembly):
                    warnings.append(
                        f"{ev[0]}：L2 条件仅为原文回填，已保留为 unmapped requirement"
                    )
                    classification, when = "unmapped", {}
                    req["then"] = None
                else:
                    grounded = bool(when) and (
                        _condition_is_grounded(when, ev[1]) or derived_pattern
                    )
                    grounded = grounded or is_visual_strategy or is_component_assembly
                    if not grounded:
                        if _looks_like_example(ev[1]):
                            warnings.append(
                                f"{ev[0]}：示例条件不得提升为 L2，已归入 evidence catalog"
                            )
                            classification, when = "example", {}
                        else:
                            warnings.append(
                                f"{ev[0]}：L2 缺少真实情境担保，已保留为 unmapped requirement"
                            )
                            classification, when = "unmapped", {}
                        req["then"] = None

            if classification == "L1" and strength not in ("must", "never"):
                # 对齐范例：无条件 should/may 可保留为 L1（check:llm）；
                # 仅把纯理由句降到 L3-story，不再整批丢进 unmapped。
                if _looks_like_philosophy_statement(ev[1]):
                    warnings.append(f"{ev[0]}：抽象原则不属于 L1，已重分类为 L3-philosophy")
                    classification = "L3-philosophy"
                    when = {}
                    req["then"] = None
                elif (
                    _looks_like_rationale(ev[1])
                    and not _contains_any_term(ev[1], _RULE_HINTS)
                    and not _then_supported(req.get("then"))
                ):
                    warnings.append(f"{ev[0]}：无条件弱指导属于理由叙述，已重分类为 L3-story")
                    classification = "L3-story"
                    when = {}
                    req["then"] = None
                # else: 保留 L1 should/may

            if classification in ("L3-philosophy", "L3-story"):
                # L3 只提供意义与理由，不承担参数化动作。
                when = {}
                req["then"] = None
            accepted.append(
                {
                    **req,
                    "classification": classification,
                    "requirement": requirement,
                    "when": when,
                    "strength": strength,
                    "scope": scope,
                    "visual_issues": visual_issues,
                    "visual_actions": visual_actions,
                    "src": ev[0],
                    "evidence_quote": ev[1],
                }
            )

    # 相同层级、相同要求只保留一次；不同证据通过第一个原文来源留痕。
    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for req in accepted:
        then_key = (
            json.dumps(req.get("then"), sort_keys=True, ensure_ascii=False)
            if _then_supported(req.get("then"))
            else _normalize_text(req["requirement"])
        )
        key = (req["classification"], then_key)
        if key not in seen:
            seen.add(key)
            deduped.append(req)

    rules: list[dict] = []
    adaptations: list[dict] = []
    philosophy: list[dict] = []
    stories: list[dict] = []
    examples: list[dict] = []
    unmapped: list[dict] = []
    used_ids: set[str] = set()
    story_for_reason: dict[str, str] = {}

    def story_id_for(req: dict) -> str:
        reason = str(req.get("reason") or "").strip()
        if not reason:
            return ""
        key = _normalize_text(reason)
        if key not in story_for_reason:
            sid = _unique_id("n", reason, used_ids)
            story_for_reason[key] = sid
            stories.append(
                {
                    "id": sid,
                    "story": reason,
                    "src": req["src"],
                    "evidence_quote": req["evidence_quote"],
                }
            )
        return story_for_reason[key]

    for req in deduped:
        kind = req["classification"]
        if kind == "unmapped":
            unmapped.append(
                {
                    "classification": "unmapped",
                    "requirement": req["requirement"],
                    "src": req["src"],
                    "quote": req["evidence_quote"],
                    "handling": "不满足严格 L1/L2/L3 判据，保留审计但不装配为规则",
                }
            )
            continue
        if kind == "example":
            examples.append(
                {
                    "text": req["requirement"],
                    "src": req["src"],
                    "quote": req["evidence_quote"],
                }
            )
            continue
        if kind == "L3-philosophy":
            title = str(req.get("title") or "").strip()
            quote = req["requirement"]
            # 若 requirement 仍是 “Title: body”，拆出 title。
            if not title:
                titled = re.match(r"^([^:]{2,40}):\s*(.+)$", quote)
                if titled and len(titled.group(2).strip()) >= 20:
                    title, quote = titled.group(1).strip(), titled.group(2).strip()
            philosophy.append(
                {
                    "id": _unique_id("p", title or quote, used_ids),
                    "title": title,
                    "quote": quote,
                    "src": req["src"],
                    "evidence_quote": req["evidence_quote"],
                }
            )
            continue
        if kind == "L3-story":
            stories.append(
                {
                    "id": _unique_id("n", req["requirement"], used_ids),
                    "story": req["requirement"],
                    "src": req["src"],
                    "evidence_quote": req["evidence_quote"],
                }
            )
            continue

        then = req.get("then")
        executable = _then_supported(then)
        strength = str(req.get("strength") or "should").lower()
        if strength not in ("must", "never", "should", "may"):
            strength = "should"
        story_id = story_id_for(req)
        if kind == "L2":
            # LLM 有时识别出条件性，但未结构化 when。保留在 L2，以真实原文
            # 作为语义 context，交慢道判断；绝不错误下沉为无条件 L1。
            when = req["when"] or {"context": req["evidence_quote"]}
            item = {
                "id": _unique_id("a", req["requirement"], used_ids),
                "when": when,
                "then": then if executable else req["requirement"],
                "strength": strength,
                "check": "programmatic" if executable else "llm",
                "story": story_id,
                "src": req["src"],
                "evidence_quote": req["evidence_quote"],
                "raw_requirement": req["requirement"],
                "derived": bool(req.get("derived")),
                "pattern_sources": req.get("pattern_sources") or [],
                "applicability": req.get("applicability") or {},
                "problem_type": req.get("problem_type"),
                "principle_refs": req.get("principle_refs") or [],
                "actions": req.get("actions") or [],
                "avoid_when": req.get("avoid_when") or [],
                "verification": req.get("verification") or [],
                "recommend_only": bool(req.get("recommend_only")),
            }
            scope = str(req.get("scope") or "chart")
            if scope == "visual-strategy":
                item["scope"] = scope
                item["visual_issues"] = list(req.get("visual_issues") or [])
                item["then"] = {"visual_actions": list(req.get("visual_actions") or [])}
                item["check"] = "llm"
            elif scope == "component-assembly":
                item["scope"] = scope
                item["when"] = {"pixel_positioned_text": True}
                item["then"] = {"profile": "editorial"}
                item["check"] = "llm"
            adaptations.append(item)
        else:
            item = {
                "id": _unique_id("s", req["requirement"], used_ids),
                "rule": req["requirement"],
                "strength": strength,
                "check": "programmatic" if executable else "llm",
                "story": story_id,
                "src": req["src"],
                "evidence_quote": req["evidence_quote"],
                "raw_requirement": req["requirement"],
                "derived": bool(req.get("derived")),
                "pattern_sources": req.get("pattern_sources") or [],
                "applicability": req.get("applicability") or {},
                "problem_type": req.get("problem_type"),
                "principle_refs": req.get("principle_refs") or [],
                "actions": req.get("actions") or [],
                "avoid_when": req.get("avoid_when") or [],
                "verification": req.get("verification") or [],
                "recommend_only": bool(req.get("recommend_only")),
            }
            if executable:
                item["then"] = then
            rules.append(item)
        if not executable:
            unmapped.append(
                {
                    "classification": kind,
                    "requirement": req["requirement"],
                    "src": req["src"],
                    "quote": req["evidence_quote"],
                    "handling": "保留在对应层，check:llm / suggested，不丢弃",
                }
            )

    quality_errors = []
    if len(rules) + len(adaptations) < 2:
        quality_errors.append("有效 L1/L2 规范少于 2 条")
    # “programmatic”只是结构标签；质量门验证 then 可编译（prefer 与 prefer_mode 解耦）。
    from .persona import Persona

    probe_persona = Persona(id=slugify(name), name=name, tokens=tokens)
    probe_facts = {
        "color_field": "__category__",
        "category_field": "__category__",
        "value_field": "__value__",
        "per_category_coloring": False,
    }
    executable_count = sum(
        1
        for item in [*rules, *adaptations]
        if item.get("check") == "programmatic"
        and _then_counts_as_executable_for_gate(
            probe_persona, item.get("then"), probe_facts
        )
    )
    if executable_count < 2:
        quality_errors.append("可执行 L1/L2 规范少于 2 条")
    # 叙事型 HIG 可无色板：有足够可执行规则时令牌缺失仅警告，不硬挡。
    if not tokens:
        if executable_count >= 2:
            warnings.append(
                "未提取到有证据的设计令牌（叙事型规范可无色板，已放宽质量门）"
            )
        else:
            quality_errors.append("未提取到有证据的设计令牌")
    if quality_errors:
        warnings.extend(f"质量门失败：{error}" for error in quality_errors)

    domain, applicability = _infer_applicability(text)
    # 教程示例进入 L3 exemplars（对齐 bbc/economist），审计副本仍进 evidence_catalog
    exemplars: list[dict[str, Any]] = []
    for i, ex in enumerate(examples or [], 1):
        if not isinstance(ex, dict):
            continue
        exemplars.append(
            {
                "id": str(ex.get("id") or f"ex-{i}"),
                "note": str(ex.get("note") or ex.get("title") or ex.get("quote") or "")[:240],
                "src": ex.get("src") or [],
            }
        )
    data = {
        "institution": {
            "id": slugify(name),
            "name": name,
            "domain": domain,
            "source": f"{slugify(name)}.md",
        },
        "applicability": applicability,
        "L1_signature": {"tokens": tokens, "rules": rules},
        "L2_adaptations": adaptations,
        "L3_narrative": {
            "philosophy": philosophy,
            "stories": stories,
            "exemplars": exemplars,
        },
        "diagnostics": structured["diagnostics"],
        "chart_type_guidance": structured["chart_type_guidance"],
        "palette_guidance": structured["palette_guidance"],
        "conflicts": structured["conflicts"],
        # 审计字段：内存/API 质量门仍可用；落盘时剥离到 sidecar（见 split_persona_documents）
        "unmapped_requirements": unmapped,
        "evidence_catalog": {"token_sources": token_sources, "examples": examples},
        "parser_provenance": {
            "mode": (
                "deterministic-fallback"
                if chunk_count and llm_chunks_succeeded == 0
                else "live-chunked"
            ),
            "source_lines": len(source_lines),
            "chunks": chunk_count,
            "llm_chunks_succeeded": llm_chunks_succeeded,
            "llm_chunks_failed": (
                chunk_count - llm_chunks_succeeded
                if llm_chunks_succeeded is not None
                else None
            ),
            "accepted_items": len(deduped),
            "rejected_items": rejected,
            "quality_errors": quality_errors,
        },
    }
    return data, warnings


def split_persona_documents(data: dict) -> tuple[dict, dict]:
    """拆成范例形态的人格正文 + 解析审计 sidecar。

    正文键与 bbc/economist-persona.yaml 一致；审计不进入三层人格 YAML。
    """
    persona_doc = {k: data[k] for k in PERSONA_CANONICAL_KEYS if k in data}
    # 保证 L3 结构完整
    l3 = persona_doc.setdefault("L3_narrative", {})
    if isinstance(l3, dict):
        l3.setdefault("philosophy", [])
        l3.setdefault("stories", [])
        l3.setdefault("exemplars", [])
    audit_doc = {k: data[k] for k in PERSONA_AUDIT_KEYS if k in data}
    return persona_doc, audit_doc


def _infer_applicability(text: str) -> tuple[str, dict]:
    """从指南元信息推断 domain 与 applicability（对齐范例 suits/promises）。"""
    domain = "custom"
    suits: list[str] = []
    promises: list[str] = []
    for line in text.splitlines()[:40]:
        low = _normalize_text(line)
        type_match = re.match(r"^type\s*:\s*(.+)$", low)
        if type_match:
            raw = type_match.group(1).strip()
            if "technolog" in raw or "corp" in raw or "product" in raw:
                domain = "technology"
                suits.append("技术产品与企业分析可视化")
                suits.append("需要设计系统一致性的数字界面")
            elif "journal" in raw or "news" in raw or "media" in raw:
                domain = "journalism"
                suits.append("新闻与媒体数据叙事")
            else:
                domain = slugify(raw)[:32] or "custom"
                suits.append(raw)
        if low.startswith("perfect for") or "when to use" in low:
            promises.append(line.strip().lstrip("#*- ").strip())
        key_adv = re.search(r"key advantages?\s*:\s*(.+)$", low)
        if key_adv:
            promises.extend(
                part.strip()
                for part in re.split(r"[-;,]", key_adv.group(1))
                if len(part.strip()) > 4
            )
    applicability: dict[str, Any] = {}
    if suits:
        applicability["suits"] = list(dict.fromkeys(suits))
    if promises:
        applicability["promises"] = list(dict.fromkeys(promises))[:8]
    return domain, applicability


def _heuristic_fragment(text: str) -> dict:
    """生成保守的词法候选；仅作 live 补强或离线底线。"""
    source_lines = text.splitlines()
    fragment: dict[str, list] = {"tokens": [], "requirements": []}
    for line_no, line in enumerate(source_lines, 1):
        clean = line.strip().lstrip("#*- ").strip()
        low = clean.lower()
        conditional = _looks_like_condition(clean)
        if (
            _contains_any_term(low, _RULE_HINTS) or conditional
        ) and 6 <= len(clean) <= 240:
            strong = _contains_any_term(low, _STRONG_HINTS)
            classification = "L2" if conditional else ("L1" if strong else "unmapped")
            strength = (
                "never"
                if _contains_any_term(low, ("never", "禁止", "不得"))
                else ("must" if strong else "should")
            )
            fragment["requirements"].append(
                {
                    "classification": classification,
                    "requirement": clean,
                    "strength": strength,
                    "when": {"context": clean} if conditional else {},
                    "then": None,
                    "reason": "",
                    "evidence": {"lines": f"L{line_no}", "quote": clean},
                }
            )
        elif _looks_like_rationale(clean) and 10 <= len(clean) <= 240:
            fragment["requirements"].append(
                {
                    "classification": "L3-story",
                    "requirement": clean,
                    "strength": "should",
                    "when": {},
                    "then": None,
                    "reason": "",
                    "evidence": {"lines": f"L{line_no}", "quote": clean},
                }
            )
        if len(fragment["requirements"]) >= 24:
            break
    return fragment


def _mock_parse(name: str, text: str) -> dict:
    """离线底线：仍通过严格三层分类门，不把任意 hex/教程句提升为 L1。"""
    data, _ = _assemble_persona(
        name,
        text,
        [_deterministic_candidates(text), _heuristic_fragment(text)],
        0,
    )
    data["parser_provenance"]["mode"] = "mock"
    return data


async def parse_guideline(name: str, text: str, llm: LLMClient) -> tuple[dict, list[str]]:
    """分块 LLM 抽取 →（可选）LLM 整编 → 程序装配；质量门失败再启发式补强。"""
    warnings: list[str] = []
    if llm.mode == "live":
        # 兼容网关常对长 JSON 生成设置较短硬超时；缩小单块以降低输入与输出体量。
        chunks = _chunk_document(text, max_chars=settings.parser_chunk_chars)
        # 确定性显式模式与 LLM 抽取并行进入同一证据校验；整编以 LLM 结果为主。
        fragments: list[dict] = [_deterministic_candidates(text)]
        llm_chunks_succeeded = 0
        for index, chunk in enumerate(chunks, 1):
            user = json.dumps(
                {
                    "institution_name": name,
                    "chunk": index,
                    "chunk_count": len(chunks),
                    "line_range": _line_ref(chunk["start"], chunk["end"]),
                    "content": chunk["text"],
                },
                ensure_ascii=False,
            )
            try:
                raw = await llm.chat_json(EXTRACTION_GUIDE, user)
                if isinstance(raw, dict):
                    fragments.append(raw)
                    llm_chunks_succeeded += 1
                else:
                    warnings.append(f"第 {index}/{len(chunks)} 块输出非对象，已忽略")
            except LLMError as exc:
                warnings.append(f"第 {index}/{len(chunks)} 块解析失败：{exc}")

        organized = False
        if llm_chunks_succeeded > 0:
            try:
                draft = await _organize_with_llm(name, fragments[1:], llm)
                if draft:
                    # 整编草案优先；保留确定性候选作色板/显式模式补强
                    fragments = [_deterministic_candidates(text), draft]
                    organized = True
                    warnings.append(
                        f"LLM 整编完成：候选 "
                        f"{len(draft.get('requirements') or [])} 条 requirement / "
                        f"{len(draft.get('tokens') or [])} 个 token"
                    )
            except LLMError as exc:
                warnings.append(f"LLM 整编失败，沿用分块结果：{exc}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"LLM 整编异常，沿用分块结果：{type(exc).__name__}: {exc}")

        data, validation_warnings = _assemble_persona(
            name,
            text,
            fragments,
            len(chunks),
            llm_chunks_succeeded,
        )
        if organized:
            data.setdefault("parser_provenance", {})["organization"] = "llm"
        quality_errors = data["parser_provenance"]["quality_errors"]
        if not quality_errors:
            warnings.extend(validation_warnings)
            prefix = (
                "确定性降级完成"
                if llm_chunks_succeeded == 0
                else ("分块+整编完成" if organized else "分块解析完成")
            )
            warnings.insert(
                0,
                f"{prefix}：{len(chunks)} 块，"
                f"L1 {len(data['L1_signature']['rules'])} / "
                f"L2 {len(data['L2_adaptations'])} / "
                f"L3 {len(data['L3_narrative']['philosophy']) + len(data['L3_narrative']['stories'])}",
            )
            return data, warnings
        # 不丢弃已成功的 live 分块；将保守词法候选合并后重新走同一证据/层级质量门。
        warnings.extend(
            warning
            for warning in validation_warnings
            if not warning.startswith("质量门失败：")
        )
        warnings.append("live 初始结果未通过质量门，正在合并启发式候选补强")
        augmented, augmented_warnings = _assemble_persona(
            name,
            text,
            [*fragments, _heuristic_fragment(text)],
            len(chunks),
            llm_chunks_succeeded,
        )
        if organized:
            augmented.setdefault("parser_provenance", {})["organization"] = "llm"
        augmented["parser_provenance"]["mode"] = "live-augmented"
        warnings.extend(augmented_warnings)
        if not augmented["parser_provenance"]["quality_errors"]:
            warnings.insert(
                0,
                f"分块解析补强完成：{len(chunks)} 块，"
                f"L1 {len(augmented['L1_signature']['rules'])} / "
                f"L2 {len(augmented['L2_adaptations'])} / "
                f"L3 {len(augmented['L3_narrative']['philosophy']) + len(augmented['L3_narrative']['stories'])}",
            )
            return augmented, warnings
        augmented["parser_provenance"]["mode"] = "quality-failed"
        warnings.append("合并启发式候选后仍未通过质量门")
        return augmented, warnings
    else:
        warnings.append("mock 模式：启发式解析（配置 OPENAI_API_KEY 后启用分块证据抽取）")
    return _mock_parse(name, text), warnings
