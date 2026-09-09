import { Check, Upload, FileJson, Code2, X, Sparkles, Wand2, Plus, Loader2, CircleAlert, Maximize2, AlignLeft, ChevronDown, ChevronUp, CheckCircle2, ArrowLeft, Download, Search, MessageSquare, Send, GripVertical } from "lucide-react";
import { type ReactNode, useState, useRef, useEffect, useCallback, useMemo } from "react";
import {
  api,
  type PersonaMeta,
  type DesignChange,
  type Proposal,
  type AgentStatus,
  type ApplyResult,
  type DiscussReply,
  type DiscussHistoryItem,
  type AgendaPayload,
} from "./api";
import { VegaLiteChart, type VegaViewHandle } from "./components/VegaLiteChart";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "./components/ui/resizable";
import { institutionLogoPresentation } from "./institutionLogos";

// ─── Types ───────────────────────────────────────────────────────────────────

type Stage = "idle" | "generating" | "generated";

interface AgentView {
  status: AgentStatus;
  progress: number;
}

interface ParsingAgent {
  tempId: string;
  name: string;
}

/** 讨论区一轮问答：用户提问 → 各机构回复（+ 可选主持人合成） */
interface DiscussAsk {
  question: string;
  replies: DiscussReply[];
  synthesis: string | null;
  pending: boolean;
  error: string | null;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const DEFAULT_SPEC = `{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "width": 350,
  "height": 220,
  "title": "Product Sales Comparison",
  "data": {
    "values": [
      {"product": "Product A", "num": 320},
      {"product": "Product B", "num": 210},
      {"product": "Product C", "num": 450},
      {"product": "Product D", "num": 280}
    ]
  },
  "mark": "bar",
  "encoding": {
    "x": {"field": "product", "type": "nominal"},
    "y": {"field": "num", "type": "quantitative"},
    "color": {"field": "product", "type": "nominal", "legend": null}
  }
}`;

function downloadUrl(url: string, filename: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function downloadTextFile(contents: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  downloadUrl(url, filename);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// 四拍推理阶段 → 状态文案（慢-快-慢-快）
const STATUS_LABEL: Record<AgentStatus, string> = {
  pending: "Queued",
  reading: "Slow · Reading intent",
  detecting: "Fast · Norm detection",
  adjudicating: "Slow · Adjudicating",
  compiling: "Fast · Compiling",
  done: "Done",
  error: "Error",
};

// 机构一句话签名（Advisors 列表副标语；未收录的机构回退 full_name）
const PERSONA_TAGLINES: Record<string, string> = {
  bbc: "Clarity-first · restrained annotation",
  economist: "Editorial contrast · assertive hierarchy",
  cmu: "Accessibility-first · direct labeling",
  cfpb: "Plain-public · five-category discipline",
  who: "Colorblind-safe · uncertainty-aware",
  ibm: "Task-driven charts · strict palette order",
  ebay: "Exacting copy · semantic color roles",
  shopify: "One-color bars · threshold-based charts",
};

const LAYER_BADGE: Record<string, { text: string; cls: string }> = {
  L1: { text: "L1 Traits", cls: "bg-slate-100 text-slate-700 border-slate-200" },
  L2: { text: "L2 Adaptations", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  L3: { text: "L3 Identity", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  "L3-derived": { text: "L3 Identity", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  user: { text: "User intent", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

// ─── Issue derivation（跨机构 changes → 议题聚合，纯前端）────────────────────────

const DESIGN_OBJECTS = [
  { key: "title", label: "Title & narrative", short: "Title" },
  { key: "color", label: "Color & emphasis", short: "Color" },
  { key: "labels", label: "Labels & annotation", short: "Labels" },
  { key: "axes", label: "Axes & scales", short: "Axes" },
  { key: "layout", label: "Layout & hierarchy", short: "Layout" },
  { key: "typography", label: "Typography", short: "Typography" },
  { key: "other", label: "Overall approach", short: "Overall" },
];

// 机构 taxonomy 分类展示顺序（与研究编码一致）
const TAXONOMY_ORDER = ["Government", "Education", "Non-profit", "News", "Profit"];

// 议题锚点统一中性灰：图表本身承载数据颜色，界面不再引入第二套颜色编码
const ANCHOR_COLOR = "#52525B";
const ANCHOR_COLOR_ACTIVE = "#18181B";

// 议题类别 → 锚点回落位置（百分比估计）。仅在 SVG 语义测量尚未就绪时使用；
// 就绪后一律以 measureAnchorPositions 实测的组件包围盒为准。
const CATEGORY_ANCHOR: Record<string, { left: string; top: string }> = {
  title: { left: "50%", top: "10%" },
  color: { left: "68%", top: "52%" },
  labels: { left: "14%", top: "86%" },
  axes: { left: "10%", top: "44%" },
  layout: { left: "88%", top: "16%" },
  typography: { left: "28%", top: "10%" },
  other: { left: "50%", top: "32%" },
};

// ── 锚点实测：渲染后的 Vega SVG 自带语义分组（role-title / role-axis / role-legend /
// role-mark）。按类别取对应组件的实际包围盒中心，锚点随图表内容走，不再靠估。
interface AnchorPos { left: number; top: number }
interface MeasuredBox { left: number; top: number; right: number; bottom: number; w: number; h: number; cx: number; cy: number }

function measureAnchorPositions(wrapper: HTMLElement): Record<string, AnchorPos> | null {
  const svg = wrapper.querySelector("svg");
  if (!svg) return null;
  const wrapRect = wrapper.getBoundingClientRect();
  if (wrapRect.width < 40 || wrapRect.height < 40) return null;

  const toBox = (r: DOMRect): MeasuredBox => ({
    left: r.left - wrapRect.left,
    top: r.top - wrapRect.top,
    right: r.right - wrapRect.left,
    bottom: r.bottom - wrapRect.top,
    w: r.width,
    h: r.height,
    cx: r.left - wrapRect.left + r.width / 2,
    cy: r.top - wrapRect.top + r.height / 2,
  });
  const boxOf = (el: Element | null): MeasuredBox | null => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return r.width || r.height ? toBox(r) : null;
  };

  const axisBoxes = [...svg.querySelectorAll("g.role-axis")]
    .map(el => boxOf(el))
    .filter((b): b is MeasuredBox => Boolean(b));
  // 横扁的是 x 轴（取最下方），竖长的是 y 轴（取最左侧）
  const xAxis = axisBoxes.filter(b => b.w >= b.h).sort((a, b) => b.bottom - a.bottom)[0] ?? null;
  const yAxis = axisBoxes.filter(b => b.h > b.w).sort((a, b) => a.left - b.left)[0] ?? null;
  const title = boxOf(svg.querySelector("g.role-title"));
  const legend = boxOf(svg.querySelector("g.role-legend"));

  // 数据 marks 的并集 = 绘图区（排除轴/图例/标题内部 mark 与文本层）
  let pl = Infinity, pt = Infinity, pr = -Infinity, pb = -Infinity;
  svg.querySelectorAll("g.role-mark").forEach(el => {
    if (el.closest("g.role-axis") || el.closest("g.role-legend") || el.closest("g.role-title")) return;
    if (el.classList.contains("mark-text")) return;
    const b = boxOf(el);
    if (!b) return;
    pl = Math.min(pl, b.left); pt = Math.min(pt, b.top);
    pr = Math.max(pr, b.right); pb = Math.max(pb, b.bottom);
  });
  let plot: MeasuredBox;
  if (pr > pl && pb > pt) {
    plot = { left: pl, top: pt, right: pr, bottom: pb, w: pr - pl, h: pb - pt, cx: (pl + pr) / 2, cy: (pt + pb) / 2 };
  } else {
    const sb = boxOf(svg);
    if (!sb) return null;
    plot = sb;
  }

  const clamp = (p: AnchorPos): AnchorPos => ({
    left: Math.min(Math.max(p.left, 12), wrapRect.width - 12),
    top: Math.min(Math.max(p.top, 12), wrapRect.height - 12),
  });

  const out: Record<string, AnchorPos> = {
    title: clamp(title
      ? { left: title.left + Math.min(60, title.w * 0.3), top: title.cy }
      : { left: plot.cx, top: plot.top - 16 }),
    typography: clamp(title
      ? { left: title.right - 10, top: title.cy }
      : yAxis
        ? { left: yAxis.cx, top: yAxis.top + 10 }
        : { left: plot.left + 14, top: plot.top + 14 }),
    color: clamp({ left: plot.cx, top: plot.cy }),
    layout: clamp({ left: plot.right - 12, top: plot.top + 12 }),
    axes: clamp(yAxis
      ? { left: yAxis.cx, top: yAxis.cy }
      : xAxis
        ? { left: xAxis.cx, top: xAxis.cy }
        : { left: plot.left - 14, top: plot.cy }),
    labels: clamp(legend
      ? { left: legend.cx, top: legend.cy }
      : xAxis
        ? { left: xAxis.cx, top: xAxis.cy }
        : { left: plot.cx, top: plot.bottom + 14 }),
    other: clamp({ left: plot.cx, top: plot.top + 14 }),
  };

  // 不同类别落点过近时向下错开，保证多个锚点都可点
  const entries = Object.entries(out);
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const a = entries[i][1];
      const b = entries[j][1];
      if (Math.abs(a.left - b.left) < 20 && Math.abs(a.top - b.top) < 20) {
        b.top = Math.min(b.top + 24, wrapRect.height - 12);
      }
    }
  }
  return out;
}

function classifyChange(change: DesignChange) {
  const scope = String(change.scope || "").toLowerCase();
  if (scope === "structure") return "other";
  if (scope === "title" || scope === "color" || scope === "labels" || scope === "axes" || scope === "layout" || scope === "typography") {
    return scope;
  }
  // v1 fallback: label first, then prose. Do not treat "story" as title —
  // L3 story ids would otherwise dump every change into Title.
  const label = (change.label || "").toLowerCase();
  if (/(color|colour|emphasis)/.test(label)) return "color";
  if (/typograph|typeface|font/.test(label)) return "typography";
  if (/title|narrative|headline/.test(label)) return "title";
  if (/label|annotation/.test(label)) return "labels";
  if (/axis|axes|scale/.test(label)) return "axes";
  if (/layout|hierarchy/.test(label)) return "layout";
  const text = [change.id, change.rule_id, change.label, change.reason, change.prompt]
    .join(" ")
    .toLowerCase();
  if (/(color|colour|palette|contrast|hue|highlight)/.test(text)) return "color";
  if (/(title|headline|subtitle|takeaway|narrative)/.test(text)) return "title";
  if (/(label|annotation|callout|legend|tooltip|source|caption)/.test(text)) return "labels";
  if (/(axis|axes|scale|grid|tick|baseline|zero)/.test(text)) return "axes";
  if (/(layout|spacing|position|align|margin|padding|size|hierarchy)/.test(text)) return "layout";
  if (/(font|typeface|typography|weight|text size)/.test(text)) return "typography";
  return "other";
}

// ops action → 受影响 spec 节点（与后端 composer 的冲突粒度对齐，见接口文档 §7）
const ACTION_NODE: Record<string, string> = {
  set_mark_type: "mark.type",
  set_mark_color: "mark.color",
  set_color_range: "color.range",
  highlight_category: "mark.color",
  set_background: "background",
  set_title_anchor: "title.anchor",
  set_title_text: "title.text",
  set_subtitle: "title.subtitle",
  set_font: "font",
  set_font_sizes: "font.sizes",
  set_legend: "legend",
  set_size: "size",
  merge_config: "config",
  remove_encoding_channel: "encoding",
  sort_categories: "encoding.sort",
  set_orientation: "encoding.orientation",
  add_value_labels: "value_labels",
  remove_value_labels: "value_labels",
  direct_label: "legend",
  set_axis_zero: "scale.zero",
  set_grid_style: "axis.grid",
  set_band_padding: "scale.band",
  set_axis: "axis",
  thin_axis_labels: "axis.labels",
  set_source_note: "title.source",
  set_mark_style: "mark.style",
  set_text_style: "text.style",
  normalize_axis_title_layout: "axis.title_layout",
  reassemble_components: "layout",
};

function changeNodes(change: DesignChange): string[] {
  const nodes = new Set<string>();
  const detailPaths = change.component_detail?.spec_paths ?? [];
  change.ops.forEach(op => {
    const action = typeof op.action === "string" ? op.action : "";
    if (action === "compose_component") {
      const paths = Array.isArray(op.spec_paths) ? op.spec_paths : detailPaths;
      if (Array.isArray(paths) && paths.length) {
        paths.forEach(path => {
          if (typeof path === "string" && path.startsWith("/")) {
            nodes.add(`spec${path.replaceAll("/", ".")}`);
          }
        });
        return;
      }
      if (typeof op.component === "string" && op.component) {
        nodes.add(`component.${op.component}`);
      }
      return;
    }
    const node = ACTION_NODE[action];
    if (node) nodes.add(node);
  });
  return [...nodes];
}

// change.id 契约格式为 "{persona_id}:{rule_id}"（接口文档 §6）
function personaIdOfChange(changeId: string) {
  const idx = changeId.indexOf(":");
  return idx > 0 ? changeId.slice(0, idx) : "";
}

// ─── 改动说明：问题 / 处理 / 依据 ──────────────────────────────────────────────
// v2 用 compose_component 承载改动，opEffect 认不出来，于是右栏只能退回到组件类别
// 名（"Color and emphasis"）——设计师读到的是标签，不是说明。可读的自然语言其实一直
// 在 reason / component_detail / warrant 里，这里把三者组装成能直接读的三句话。

const APPLIED_PREFIX = /^(applied|proposed|suggested|change)\s*[:：—–]\s*/i;
/** 快道自述与 spec 内部话，不是给设计师看的改动说明 */
const ENGINE_JARGON = /l1 signature|fast[- ]lane|re-verified|violated the institution|title\s*=\s*null|orient\s*=|r\s*==\s*1|defaults applied|no explicit/i;

function isDesignerFacing(change: DesignChange): boolean {
  const after = change.component_detail?.after ?? "";
  const before = change.component_detail?.before ?? "";
  return !ENGINE_JARGON.test(`${change.reason} ${before} ${after}`);
}

function cleanSentence(text?: string | null): string {
  // 剥掉 "Applied:" / "Applied—" 这类流程前缀后句子会从小写起头，补回首字母大写
  const trimmed = (text ?? "").replace(APPLIED_PREFIX, "").replace(/\s+/g, " ").trim();
  return trimmed ? trimmed[0].toUpperCase() + trimmed.slice(1) : "";
}

function distinctLines(values: (string | undefined)[], limit: number): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  values.forEach(raw => {
    const value = cleanSentence(raw);
    const key = value.toLowerCase();
    if (!value || seen.has(key)) return;
    seen.add(key);
    out.push(value);
  });
  return out.slice(0, limit);
}

interface NamedColor {
  name: string;
  value: string;
}

interface KnowledgeLine {
  layer: "L1" | "L2" | "L3";
  text: string;
}

interface TreatmentSummary {
  /** 怎么处理的（自然语言） */
  treatment: string;
  /** 这一改兑现的各层机构知识；一条改动可以同时有 Traits / Adaptations / Identity */
  knowledge: KnowledgeLine[];
}

const TOKEN_ACRONYMS = new Set(["bbc", "cmu", "who", "ibm", "uk", "vat", "nhs"]);

function tokenLabel(name: string): string {
  return name.split(/[-_]/).filter(Boolean).map(part => (
    TOKEN_ACRONYMS.has(part.toLowerCase()) ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)
  )).join(" ");
}

function explainHex(text: string, tokens: NamedColor[]): string {
  const byHex = new Map(tokens.map(t => [t.value.toUpperCase(), tokenLabel(t.name)]));
  return text.replace(/(?<!\()#[0-9A-Fa-f]{6}\b/g, hex => {
    const name = byHex.get(hex.toUpperCase());
    return name ? `${name} (${hex.toUpperCase()})` : hex.toUpperCase();
  });
}

function collectTokens(changes: DesignChange[]): NamedColor[] {
  const seen = new Set<string>();
  const out: NamedColor[] = [];
  changes.forEach(change => {
    (change.knowledge?.tokens ?? []).forEach(token => {
      const key = token.value.toUpperCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ name: token.name, value: key });
    });
  });
  return out;
}

/** 把一层机构知识念成可理解的句子，而不只是标签。 */
function knowledgeText(knowledge: ChangeKnowledge | undefined): string {
  if (!knowledge) return "";
  if (knowledge.layer === "L3" && knowledge.philosophy) {
    const quote = cleanSentence(knowledge.quote);
    return quote ? `For ${knowledge.philosophy}: ${quote}` : `For ${knowledge.philosophy} design identity.`;
  }
  if (knowledge.layer === "L2" && knowledge.condition) {
    const story = cleanSentence(knowledge.quote);
    const lead = `When ${knowledge.condition}.`;
    return story && !lead.toLowerCase().includes(story.toLowerCase().slice(0, 24)) ? `${lead} ${story}` : lead;
  }
  const tokens = knowledge.tokens ?? [];
  const bits: string[] = [];
  if (knowledge.applied) bits.push(explainHex(cleanSentence(knowledge.applied), tokens));
  else if (tokens.length) {
    bits.push(`House colors: ${tokens.map(t => `${tokenLabel(t.name)} (${t.value.toUpperCase()})`).join(", ")}.`);
  }
  if (knowledge.rule) bits.push(cleanSentence(knowledge.rule));
  return bits.join(" ");
}

function knowledgeOf(change: DesignChange): ChangeKnowledge[] {
  if (change.knowledge_layers?.length) return change.knowledge_layers;
  return change.knowledge ? [change.knowledge] : [];
}

/** 把一个机构在某议题下的全部改动，压成设计师可快速读懂的说明 */
function treatmentSummary(bundle: IssueSolution[], agendaLine?: string, agendaWhy?: string): TreatmentSummary {
  const changes = bundle.map(s => s.change);
  // 同一议题下的多条改动可能各自回应不同的审阅结论。若把它们的问题与处理混在
  // 一起讲，就会出现「问题说字体、处理说图例」这类对不上号的卡片。按被引用的
  // 结论分组，主线取覆盖最多的一组，其余只报数量。
  const threads = new Map<string, DesignChange[]>();
  changes.forEach(change => {
    const key = change.rule_id || change.id;
    threads.set(key, [...(threads.get(key) ?? []), change]);
  });
  const primary = [...threads.values()].sort((a, b) => b.length - a.length)[0] ?? changes;

  // 记下哪几条改动贡献了展示出来的处理说明。知识必须出自它们，否则会出现
  // "说明讲坐标轴灰度、依据却挂在高亮条上"这种对不上号的卡片。
  const spoken: DesignChange[] = [];
  const said = new Set<string>();
  primary.forEach(change => {
    if (!isDesignerFacing(change)) return;
    const line = cleanSentence(change.reason).toLowerCase();
    if (!line || said.has(line) || spoken.length >= 2) return;
    said.add(line);
    spoken.push(change);
  });
  const source = spoken.length ? spoken : primary;
  const tokens = collectTokens(source);
  const treatment = explainHex(
    (agendaLine ? cleanSentence(agendaLine) : spoken.map(c => cleanSentence(c.reason)).join(" "))
      || primary[0]?.label
      || "",
    tokens,
  );
  const normalize = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const seen = new Set<string>();
  const knowledge: KnowledgeLine[] = [];
  source.forEach(change => {
    knowledgeOf(change).forEach(item => {
      const text = knowledgeText(item);
      const key = `${item.layer}:${normalize(text)}`;
      if (!text || seen.has(key) || normalize(treatment).includes(normalize(text))) return;
      seen.add(key);
      knowledge.push({ layer: item.layer, text });
    });
  });

  return { treatment, knowledge };
}

interface IssueSolution {
  personaId: string;
  change: DesignChange;
  nodes: string[];
}

interface DerivedIssue {
  key: string;
  n: number;
  label: string;
  short: string;
  /** 锚点类别（DESIGN_OBJECTS key）；本地派生时与 key 相同 */
  category: string;
  personaIds: string[];
  solutions: IssueSolution[];
  /** 被 ≥2 个机构同时修改的 spec 节点（Compose 时后端将按采纳数消解） */
  conflictNodes: string[];
  /** 以下叙事字段来自后端主持人议程合成（live）；本地派生时为空 */
  blurb?: string;
  discussionIntro?: string;
  quickAsks?: string[];
  treatmentLines?: Record<string, string>;
}

/** 议题标题只用可视化设计元素名（Title / Color / Labels…），问题细节放进各机构 Change。 */
function issueHeadline(short: string, _solutions: IssueSolution[]): string {
  return short;
}

function deriveIssues(runPersonas: PersonaMeta[], proposals: Record<string, Proposal>): DerivedIssue[] {
  const byKey = new Map<string, IssueSolution[]>();
  runPersonas.forEach(persona => {
    proposals[persona.id]?.changes.forEach(change => {
      if (!isDesignerFacing(change)) return;
      const key = classifyChange(change);
      const list = byKey.get(key) ?? [];
      list.push({ personaId: persona.id, change, nodes: changeNodes(change) });
      byKey.set(key, list);
    });
  });

  const issues = DESIGN_OBJECTS.filter(obj => byKey.has(obj.key)).map(obj => {
    const solutions = byKey.get(obj.key) ?? [];
    const personaIds = runPersonas.map(p => p.id).filter(id => solutions.some(s => s.personaId === id));
    const nodeOwners = new Map<string, Set<string>>();
    solutions.forEach(s =>
      s.nodes.forEach(node => {
        const owners = nodeOwners.get(node) ?? new Set<string>();
        owners.add(s.personaId);
        nodeOwners.set(node, owners);
      }),
    );
    const conflictNodes = [...nodeOwners.entries()].filter(([, owners]) => owners.size >= 2).map(([node]) => node);
    return { key: obj.key, label: issueHeadline(obj.short, solutions), short: obj.short, category: obj.key, personaIds, solutions, conflictNodes, n: 0 };
  });

  issues.sort((a, b) => b.personaIds.length - a.personaIds.length || b.solutions.length - a.solutions.length);
  issues.forEach((issue, index) => {
    issue.n = index + 1;
  });
  return issues;
}

/** 后端主持人议程（live）→ DerivedIssue：change id 映射回实际 changes，叙事字段透传 */
function issuesFromAgenda(
  agenda: AgendaPayload,
  runPersonas: PersonaMeta[],
  proposals: Record<string, Proposal>,
): DerivedIssue[] {
  const changeById = new Map<string, DesignChange>();
  runPersonas.forEach(p => proposals[p.id]?.changes.forEach(c => changeById.set(c.id, c)));
  const shortByCat = new Map(DESIGN_OBJECTS.map(o => [o.key, o.short]));

  const issues: DerivedIssue[] = [];
  agenda.issues.forEach((ai, idx) => {
    const solutions: IssueSolution[] = [];
    const treatmentLines: Record<string, string> = {};
    const personaIds: string[] = [];
    ai.treatments.forEach(t => {
      const changes = t.change_ids
        .map(id => changeById.get(id))
        .filter((c): c is DesignChange => Boolean(c) && isDesignerFacing(c));
      if (!changes.length) return;
      // 后端已按机构合并 treatment；这里再兜底去重，避免同机构渲染两行
      if (!personaIds.includes(t.persona_id)) personaIds.push(t.persona_id);
      if (t.line) {
        const prev = treatmentLines[t.persona_id];
        treatmentLines[t.persona_id] = prev ? `${prev}; ${t.line}` : t.line;
      }
      changes.forEach(c => solutions.push({ personaId: t.persona_id, change: c, nodes: changeNodes(c) }));
    });
    if (!solutions.length) return;

    const nodeOwners = new Map<string, Set<string>>();
    solutions.forEach(s =>
      s.nodes.forEach(node => {
        const owners = nodeOwners.get(node) ?? new Set<string>();
        owners.add(s.personaId);
        nodeOwners.set(node, owners);
      }),
    );
    const conflictNodes = [...nodeOwners.entries()].filter(([, owners]) => owners.size >= 2).map(([node]) => node);
    const category = shortByCat.has(ai.category) ? ai.category : "other";
    issues.push({
      key: `agenda-${idx}`,
      n: issues.length + 1,
      label: issueHeadline(shortByCat.get(category) ?? "Issue", solutions),
      short: shortByCat.get(category) ?? "Issue",
      category,
      personaIds,
      solutions,
      conflictNodes,
      blurb: ai.blurb || undefined,
      discussionIntro: ai.discussion_intro || undefined,
      quickAsks: ai.quick_asks.length ? ai.quick_asks : undefined,
      treatmentLines: Object.keys(treatmentLines).length ? treatmentLines : undefined,
    });
  });
  return issues;
}

/** 议程 why 缺席时的降级：取机构 reason 的第一句作为决策依据行 */
function firstSentence(text: string): string {
  const t = (text || "").trim();
  const match = t.match(/^[\s\S]{15,}?[.!?](?=\s|$)/);
  return (match ? match[0] : t).trim();
}

// ─── Small components ─────────────────────────────────────────────────────────

function PersonaBadge({ persona, size = 28 }: { persona: PersonaMeta; size?: number }) {
  const logo = institutionLogoPresentation(persona);
  const logoPath = logo?.path;
  const [logoFailed, setLogoFailed] = useState(false);
  const showLogo = Boolean(logoPath && !logoFailed);

  useEffect(() => {
    setLogoFailed(false);
  }, [logoPath]);

  return (
    <div
      title={persona.name}
      style={{
        width: size, height: size, background: showLogo ? "#FFFFFF" : persona.brand_color,
        borderRadius: showLogo && logo?.shape === "circle" ? "50%" : Math.round(size * 0.22),
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        border: showLogo ? "1px solid rgba(15, 23, 42, 0.10)" : "1px solid transparent",
        overflow: "hidden",
      }}
    >
      {showLogo && logoPath ? (
        <img
          src={logoPath}
          alt=""
          aria-hidden="true"
          onError={() => setLogoFailed(true)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "contain",
            padding: logo?.paddingRatio === 0 ? 0 : Math.max(1, Math.round(size * (logo?.paddingRatio ?? 0.08))),
          }}
        />
      ) : (
        <span style={{ fontSize: size * 0.31, color: "#fff", fontWeight: 700, letterSpacing: "-0.02em", fontFamily: "'DM Sans', sans-serif" }}>
          {persona.abbr}
        </span>
      )}
    </div>
  );
}

function ModeratorBadge({ size = 22 }: { size?: number }) {
  return (
    <div
      style={{
        width: size, height: size, borderRadius: size / 2, background: "#6257D9",
        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
      }}
    >
      <span style={{ fontSize: size * 0.45, color: "#fff", fontWeight: 700 }}>L</span>
    </div>
  );
}

function ProgressRing({ progress, color, size = 32 }: { progress: number; color: string; size?: number }) {
  const r = (size - 4) / 2;
  const circ = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} style={{ position: "absolute", top: 0, left: 0, transform: "rotate(-90deg)" }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth={2} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={2}
        strokeDasharray={circ} strokeDashoffset={circ * (1 - progress)}
        style={{ transition: "stroke-dashoffset 0.4s ease" }} strokeLinecap="round" />
    </svg>
  );
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block w-[11px] h-[11px] rounded-[3px] border border-black/10 shrink-0 align-text-bottom"
      style={{ background: color }}
      title={color}
    />
  );
}

/** 句子里的 hex 配上色块；馆定色名已经写在括号前，不再单独再挂一排色。 */
function ColorCopy({ text }: { text: string }) {
  const parts = text.split(/(#[0-9A-Fa-f]{6}\b)/g);
  return (
    <>
      {parts.map((part, index) => (
        /^#[0-9A-Fa-f]{6}$/.test(part)
          ? <span key={`${part}-${index}`} className="inline-flex items-center gap-0.5 mx-0.5 whitespace-nowrap">
              <Swatch color={part} />
              <span className="font-mono text-[10px]">{part}</span>
            </span>
          : <span key={`${part}-${index}`}>{part}</span>
      ))}
    </>
  );
}

/** 带标签的说明行：Change / Knowledge。全文展示，不用省略号截断。 */
function SummaryRow({ label, text, tone = "plain" }: {
  label: string;
  text: string;
  tone?: "plain" | "basis";
}) {
  const textCls = tone === "basis"
    ? "text-[11px] text-muted-foreground leading-relaxed"
    : "text-[11.5px] text-foreground/90 leading-relaxed";
  return (
    <div className="flex items-start gap-2 min-w-0">
      <span className="shrink-0 w-[68px] pt-px text-[8.5px] font-bold uppercase tracking-wide text-muted-foreground/70">{label}</span>
      <p className={`${textCls} min-w-0 flex-1`}>
        <ColorCopy text={text} />
      </p>
    </div>
  );
}

function LayerMark({ layer }: { layer: string }) {
  const badge = LAYER_BADGE[layer] ?? LAYER_BADGE.L3;
  return (
    <span className={`text-[8px] font-semibold border rounded px-1 py-px shrink-0 ${badge.cls}`}>{badge.text}</span>
  );
}

function AdoptButton({ accepted, onClick, disabled = false, title }: { accepted: boolean; onClick: () => void; disabled?: boolean; title?: string }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`shrink-0 px-2 py-1 rounded-md text-[11px] font-semibold flex items-center gap-1 border transition-colors disabled:cursor-not-allowed ${disabled ? "bg-amber-50 text-amber-700 border-amber-200 opacity-80" : accepted ? "bg-[#EAF7F0] text-[#21875A] border-[#B7E2CB]" : "bg-white text-[#52525B] border-[#D4D4D8] hover:bg-[#F4F4F5]"}`}
    >
      <CheckCircle2 size={11} />
      {disabled ? "Unverified" : accepted ? "Adopted" : "Adopt"}
    </button>
  );
}

// ─── Top Bar ──────────────────────────────────────────────────────────────────

function TopBar() {
  return (
    <div className="viz-topbar h-11 flex items-center px-5 border-b border-border bg-card shrink-0">
      <div className="flex items-baseline gap-2.5">
        <span className="text-sm font-semibold tracking-tight">VisPrism</span>
        <span className="text-xs text-muted-foreground">Institutional design persona agents</span>
      </div>
    </div>
  );
}

// ─── Input Panel ──────────────────────────────────────────────────────────────

interface InputPanelProps {
  personas: PersonaMeta[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  agents: Record<string, AgentView>;
  stage: Stage;
  onGenerate: () => void;
  specText: string;
  onSpecChange: (text: string) => void;
  communicationGoal: string;
  onCommunicationGoalChange: (text: string) => void;
  parsingAgents: ParsingAgent[];
  onAddPersonaFile: (file: File) => void;
  error: string | null;
}

function InputPanel({
  personas, selected, onToggle, agents, stage, onGenerate,
  specText, onSpecChange, communicationGoal, onCommunicationGoalChange,
  parsingAgents, onAddPersonaFile, error,
}: InputPanelProps) {
  const [specTab, setSpecTab] = useState<"code" | "file">("code");
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isAgentDragOver, setIsAgentDragOver] = useState(false);
  const [editorFullscreen, setEditorFullscreen] = useState(false);
  const [advisorQuery, setAdvisorQuery] = useState("");
  const [advisorCategory, setAdvisorCategory] = useState<string>("all");

  const parsedSpec = useMemo(() => {
    try { return JSON.parse(specText) as object; } catch { return null; }
  }, [specText]);

  const allSelected = personas.length > 0 && personas.every(p => selected.has(p.id));
  const someSelected = selected.size > 0;
  const specLines = specText.split("\n");

  // 机构库筛选：taxonomy 分类 chips + 名称搜索（Government/Education/Non-profit/News/Profit）
  const categories = useMemo(() => {
    const present = new Set(personas.map(p => p.category || "Other"));
    const ordered = TAXONOMY_ORDER.filter(c => present.has(c));
    // taxonomy 之外的（如自定义 persona 的 Other）排在末尾
    const extras = [...present].filter(c => !TAXONOMY_ORDER.includes(c)).sort();
    return [...ordered, ...extras];
  }, [personas]);
  const visiblePersonas = useMemo(() => {
    const q = advisorQuery.trim().toLowerCase();
    return personas.filter(p => {
      if (advisorCategory !== "all" && (p.category || "Other") !== advisorCategory) return false;
      if (!q) return true;
      return `${p.name} ${p.full_name}`.toLowerCase().includes(q);
    });
  }, [personas, advisorQuery, advisorCategory]);

  const formatSpec = () => {
    try { onSpecChange(JSON.stringify(JSON.parse(specText), null, 2)); } catch { /* validation message already shown */ }
  };

  const loadFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = ev => { onSpecChange((ev.target?.result as string) ?? ""); setUploadedFile(file.name); setSpecTab("code"); };
    reader.readAsText(file);
  };

  return (
    <div className="h-full min-w-0 bg-card border-r border-border flex flex-col">
      <div className="viz-panel-header px-4 h-11 flex items-center border-b border-border shrink-0">
        <span className="text-[16px] font-semibold">Settings</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto" style={{ scrollbarWidth: "thin" }}>

        {/* Chart spec */}
        <div className="border-b border-border">
          <div className="flex items-center px-3 pt-2 gap-0.5">
            <span className="text-xs font-semibold mr-3">Chart Spec</span>
            <button onClick={() => setSpecTab("code")} className={`flex items-center gap-1 px-2.5 py-1 text-[10px] font-medium transition-colors border-b-2 ${specTab === "code" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <Code2 size={11} />Paste JSON
            </button>
            <button onClick={() => setSpecTab("file")} className={`flex items-center gap-1 px-2.5 py-1 text-[10px] font-medium transition-colors border-b-2 ${specTab === "file" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
              <FileJson size={11} />Upload
            </button>
          </div>
          {specTab === "code" ? (
            <div className="px-3 py-2">
              <div className={`border border-border bg-[#f8f9fb] rounded-lg overflow-hidden ${editorFullscreen ? "fixed inset-6 z-50 shadow-2xl flex flex-col" : ""}`}>
                <div className="h-7 px-2.5 flex items-center border-b border-border bg-white">
                  <span className={`text-[11px] font-medium ${parsedSpec ? "text-emerald-700" : "text-red-600"}`}>
                    {parsedSpec ? "Valid Vega-Lite JSON" : "JSON syntax error"}
                  </span>
                  <div className="ml-auto flex items-center gap-1">
                    <button onClick={formatSpec} disabled={!parsedSpec} title="Format JSON" className="p-1.5 rounded hover:bg-secondary disabled:opacity-30"><AlignLeft size={13} /></button>
                    <button onClick={() => setEditorFullscreen(v => !v)} title={editorFullscreen ? "Exit fullscreen" : "Fullscreen editor"} className="p-1.5 rounded hover:bg-secondary"><Maximize2 size={13} /></button>
                  </div>
                </div>
                <div className={`flex min-h-0 overflow-hidden ${editorFullscreen ? "flex-1" : "viz-spec-editor"}`}>
                  <div className="py-2 px-2 overflow-hidden shrink-0 text-right select-none text-[11px] leading-[1.55] font-mono text-muted-foreground/60 bg-secondary/35 border-r border-border">
                    {specLines.map((_, i) => <div key={i}>{i + 1}</div>)}
                  </div>
                  <textarea value={specText} onChange={e => onSpecChange(e.target.value)}
                    className="h-full flex-1 min-w-0 overflow-y-auto text-[11px] font-mono bg-transparent p-2 resize-none text-foreground focus:outline-none leading-[1.55]"
                    rows={editorFullscreen ? undefined : 10} spellCheck={false} />
                </div>
              </div>
              {uploadedFile && <p className="text-[9px] text-muted-foreground mt-1 flex items-center gap-1"><FileJson size={9} />Loaded: {uploadedFile}</p>}
              {!parsedSpec && <p className="text-[11px] text-red-600 mt-1.5 flex items-center gap-1"><CircleAlert size={11} />Check the syntax near brackets, commas, or quotation marks.</p>}
            </div>
          ) : (
            <div className="px-3 pt-2 pb-3">
              <label className={`flex flex-col items-center justify-center gap-2 w-full rounded-lg border-2 border-dashed cursor-pointer transition-all py-7 ${isDragOver ? "border-primary bg-[#F0EEFF]" : "border-border hover:border-[#D4D4D8] hover:bg-[#FAFAFB]"}`}
                onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
                onDragLeave={() => setIsDragOver(false)}
                onDrop={e => { e.preventDefault(); setIsDragOver(false); const f = e.dataTransfer.files[0]; if (f) loadFile(f); }}>
                <div className={`w-8 h-8 rounded-xl flex items-center justify-center ${isDragOver ? "bg-[#E7E3FF]" : "bg-secondary"}`}>
                  <Upload size={15} className={isDragOver ? "text-primary" : "text-muted-foreground"} />
                </div>
                <div className="text-center">
                  <p className="text-[11px] font-medium">Drop file here</p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">or click to browse</p>
                </div>
                <span className="text-[9px] text-muted-foreground/60">Vega-Lite v5 JSON</span>
                <input type="file" accept=".json,.vl.json" className="hidden" onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f); e.target.value = ""; }} />
              </label>
              {uploadedFile && (
                <div className="mt-2 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200">
                  <FileJson size={11} className="text-emerald-600 shrink-0" />
                  <span className="text-[10px] text-emerald-700 font-medium truncate">{uploadedFile}</span>
                  <button onClick={() => setUploadedFile(null)} className="ml-auto text-emerald-500 hover:text-emerald-700"><X size={11} /></button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Communication goal（原图预览已移至中间视图，settings 专注输入） */}
        <div className="px-3 py-2 border-b border-border">
          <label htmlFor="communication-goal" className="block text-[11px] font-semibold text-muted-foreground">
            Communication goal
          </label>
          <textarea
            id="communication-goal"
            value={communicationGoal}
            onChange={e => onCommunicationGoalChange(e.target.value)}
            placeholder="For example: Highlight that Product C has the highest sales while Product B trails the others."
            rows={2}
            className="mt-1.5 w-full resize-none rounded-lg border border-[#E4E4E7] bg-[#FAFAFB] px-2.5 py-2 text-[11px] leading-relaxed text-foreground placeholder:text-[#A1A1AA] focus:outline-none focus:border-[#7569E8] focus:ring-2 focus:ring-[#F0EEFF]"
          />
        </div>

        {/* Advisor selector */}
        <div className="px-4 pt-3 pb-2">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] text-muted-foreground font-semibold uppercase tracking-wide">Agents</p>
            <button
              onClick={() => personas.forEach(p => {
                if (allSelected ? selected.has(p.id) : !selected.has(p.id)) onToggle(p.id);
              })}
              className="text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            >
              {allSelected ? "Deselect All" : "Select All"}
            </button>
          </div>

          {/* 搜索 + 领域筛选：机构库扩展到 20+ persona 时的入口 */}
          <div className="relative mb-1.5">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              value={advisorQuery}
              onChange={e => setAdvisorQuery(e.target.value)}
              placeholder="Search institutions…"
              className="w-full rounded-lg border border-[#E4E4E7] bg-[#FAFAFB] pl-7 pr-2.5 py-1.5 text-[11px] text-foreground placeholder:text-[#A1A1AA] focus:outline-none focus:border-[#7569E8] focus:ring-2 focus:ring-[#F0EEFF]"
            />
          </div>
          {categories.length > 1 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {["all", ...categories].map(c => (
                <button
                  key={c}
                  onClick={() => setAdvisorCategory(c)}
                  className={`px-2 py-0.5 rounded-full text-[10px] font-medium border transition-colors ${advisorCategory === c ? "bg-[#F0EEFF] text-[#5146C7] border-[#CFC9FA]" : "bg-white text-muted-foreground border-border hover:text-foreground"}`}
                >
                  {c === "all" ? "All" : c}
                </button>
              ))}
            </div>
          )}

          <div
            className={`grid gap-1.5 max-h-[320px] overflow-y-auto pr-0.5 ${isAgentDragOver ? "ring-2 ring-primary/20 ring-offset-2 rounded-xl" : ""}`}
            style={{ gridTemplateColumns: "1fr", scrollbarWidth: "thin" }}
            onDragOver={e => { e.preventDefault(); setIsAgentDragOver(true); }}
            onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsAgentDragOver(false); }}
            onDrop={e => { e.preventDefault(); setIsAgentDragOver(false); const f = e.dataTransfer.files[0]; if (f) onAddPersonaFile(f); }}
          >
            {visiblePersonas.map(p => {
              const isSelected = selected.has(p.id);
              const agent = agents[p.id];
              return (
                <button key={p.id} onClick={() => onToggle(p.id)}
                  title={`${p.full_name} · L1 ${p.layers.l1_rules} / L2 ${p.layers.l2_adaptations} / L3 ${p.layers.l3_philosophy + p.layers.l3_stories}`}
                  className={`relative flex items-center gap-2.5 px-2.5 py-2 rounded-lg border text-left transition-all ${isSelected ? "border-[#CFC9FA] bg-[#F7F5FF]" : "border-border bg-white text-muted-foreground hover:border-[#D4D4D8] hover:bg-[#FAFAFB]"}`}>
                  <div className="relative shrink-0" style={{ width: 22, height: 22 }}>
                    <PersonaBadge persona={p} size={22} />
                    {agent && agent.status !== "done" && agent.status !== "error" && (
                      <ProgressRing progress={agent.progress} color={p.brand_color} size={22} />
                    )}
                  </div>
                  <div className="min-w-0">
                    <span className="block text-[12px] font-semibold truncate" style={{ color: isSelected ? p.brand_color : undefined }}>{p.name}</span>
                    <span className="block text-[10px] text-muted-foreground truncate">
                      {PERSONA_TAGLINES[p.id] || p.full_name || "Custom institutional design logic"}
                    </span>
                  </div>
                  <span className={`ml-auto w-4 h-4 rounded border flex items-center justify-center ${isSelected ? "bg-primary border-primary" : "bg-white border-border"}`}>{isSelected && <Check size={10} color="white" />}</span>
                </button>
              );
            })}
            {visiblePersonas.length === 0 && (
              <p className="text-[10px] text-muted-foreground text-center py-3">No institutions match the filter.</p>
            )}

            {parsingAgents.map(a => (
              <div key={a.tempId} className="relative flex items-center gap-2 px-2 py-1.5 rounded-lg border border-border opacity-55">
                <div className="shrink-0 w-[22px] h-[22px] rounded-[5px] bg-gray-200 flex items-center justify-center">
                  <Loader2 size={11} className="text-muted-foreground animate-spin" />
                </div>
                <span className="text-[10px] font-semibold truncate text-muted-foreground">Parsing {a.name}…</span>
              </div>
            ))}

            <label className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-dashed cursor-pointer transition-all border-border hover:border-foreground/25 hover:bg-secondary/40">
              <div className="w-[22px] h-[22px] rounded-[5px] bg-secondary flex items-center justify-center shrink-0">
                <Plus size={11} className="text-muted-foreground" />
              </div>
              <span className="text-[10px] text-muted-foreground truncate">Parse new guideline (.md)</span>
              <input
                type="file"
                accept=".md,.markdown,text/markdown,text/plain"
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) onAddPersonaFile(f); e.target.value = ""; }}
              />
            </label>
          </div>
          {isAgentDragOver && (
            <p className="text-[9px] text-primary text-center mt-1.5">Drop Markdown guideline to parse a new agent</p>
          )}
        </div>
      </div>

      {/* Pinned bottom */}
      <div className="shrink-0 border-t border-border px-4 py-4">
        {error && (
          <p className="text-[10px] text-red-600 mb-2 flex items-start gap-1"><CircleAlert size={11} className="shrink-0 mt-0.5" />{error}</p>
        )}
        <button onClick={onGenerate} disabled={stage === "generating" || !someSelected || !parsedSpec}
          className={`w-full py-2 rounded-lg text-xs font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed ${stage === "generated" ? "bg-white text-[#52525B] border border-[#D4D4D8] hover:bg-[#F4F4F5]" : "bg-primary text-primary-foreground hover:bg-[#5146C7]"}`}>
          {stage === "generating" ? "Generating proposals…" : "Generate Proposals"}
        </button>
        {someSelected && (
          <p className="text-center text-[10px] text-muted-foreground mt-1.5">
            {selected.size} agent{selected.size !== 1 ? "s" : ""} selected
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Gallery：原图锚点卡 + 减负后的提案卡 ────────────────────────────────────────

function AnchorOverlay({ issues, selectedKey, onSelect, positions }: {
  issues: DerivedIssue[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  /** SVG 语义实测的类别落点；null = 测量未就绪，回落百分比估计 */
  positions: Record<string, AnchorPos> | null;
}) {
  const seen = new Map<string, number>();
  return (
    <>
      {issues.map(issue => {
        const measured = positions?.[issue.category] ?? positions?.other ?? null;
        const fallback = CATEGORY_ANCHOR[issue.category] ?? CATEGORY_ANCHOR.other;
        // 同类别多个议题时锚点向下错开，避免重叠
        const dup = seen.get(issue.category) ?? 0;
        seen.set(issue.category, dup + 1);
        const active = selectedKey === issue.key;
        const pos = measured
          ? { left: measured.left, top: measured.top + dup * 26 }
          : { left: fallback.left, top: dup ? `calc(${fallback.top} + ${dup * 13}%)` : fallback.top };
        return (
          <button
            key={issue.key}
            onClick={e => { e.stopPropagation(); onSelect(issue.key); }}
            title={`#${issue.n} ${issue.label} · ${issue.personaIds.length} agent${issue.personaIds.length > 1 ? "s" : ""}`}
            className="absolute z-10 flex items-center justify-center rounded-full text-white font-bold transition-transform"
            style={{
              ...pos,
              width: 22, height: 22, marginLeft: -11, marginTop: -11,
              background: active ? ANCHOR_COLOR_ACTIVE : ANCHOR_COLOR, fontSize: 11,
              border: "2px solid #fff",
              boxShadow: active ? "0 0 0 3px rgba(24,24,27,0.22)" : "0 1px 3px rgba(0,0,0,0.25)",
              transform: active ? "scale(1.15)" : undefined,
            }}
          >
            {issue.n}
          </button>
        );
      })}
    </>
  );
}

function OriginalCard({ spec, issues, selectedKey, onSelect }: {
  spec: object | null;
  issues: DerivedIssue[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [anchorPositions, setAnchorPositions] = useState<Record<string, AnchorPos> | null>(null);

  const remeasure = useCallback(() => {
    // 等一帧让 vega-embed 完成 viewBox 缩放后再量
    requestAnimationFrame(() => {
      if (wrapRef.current) setAnchorPositions(measureAnchorPositions(wrapRef.current));
    });
  }, []);
  const handleViewReady = useCallback((view: VegaViewHandle | null) => {
    if (view) remeasure();
    else setAnchorPositions(null);
  }, [remeasure]);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => remeasure());
    ro.observe(el);
    return () => ro.disconnect();
  }, [remeasure]);

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
      <div className="px-4 pt-3 pb-2 flex items-center gap-2">
        <p className="text-[13px] font-semibold">Original chart</p>
      </div>
      <div ref={wrapRef} className="mx-4 mb-3 rounded-lg border border-border bg-white p-2 relative">
        <VegaLiteChart spec={spec} maxHeight={190} onViewReady={handleViewReady} />
        <AnchorOverlay issues={issues} selectedKey={selectedKey} onSelect={onSelect} positions={anchorPositions} />
      </div>
    </div>
  );
}

function groupAdoptedChanges(changes: DesignChange[]): { personaId: string; short: string; items: DesignChange[] }[] {
  const groups: { personaId: string; short: string; items: DesignChange[] }[] = [];
  const index = new Map<string, number>();
  changes.forEach(change => {
    const personaId = personaIdOfChange(change.id);
    const category = classifyChange(change);
    const short = DESIGN_OBJECTS.find(obj => obj.key === category)?.short ?? change.label;
    const key = `${personaId}\0${category}`;
    const at = index.get(key);
    if (at === undefined) {
      index.set(key, groups.length);
      groups.push({ personaId, short, items: [change] });
    } else {
      groups[at].items.push(change);
    }
  });
  return groups;
}

function GalleryCard({ persona, agent, proposal, issues, selectedIssueKey, onSelectIssue, onFocus, dragHandle, className = "" }: {
  persona: PersonaMeta;
  agent: AgentView | undefined;
  proposal: Proposal | undefined;
  issues: DerivedIssue[];
  selectedIssueKey: string | null;
  onSelectIssue: (key: string) => void;
  onFocus?: () => void;
  dragHandle?: ReactNode;
  className?: string;
}) {
  const status = agent?.status ?? "pending";

  if (status === "error") {
    return (
      <div className={`viz-proposal-card rounded-xl border border-red-200 bg-card overflow-hidden ${className}`}>
        <div className="px-3 pt-3 pb-2 flex items-center gap-2">
          <PersonaBadge persona={persona} size={22} />
          <div><p className="text-xs font-semibold">{persona.name}</p><p className="text-[9px] text-red-500">Agent error</p></div>
          {dragHandle}
        </div>
        <p className="px-3 pb-3 text-[9px] text-red-500 break-all">Reasoning failed. Check the backend logs.</p>
      </div>
    );
  }

  if (status !== "done" || !proposal) {
    return (
      <div className={`viz-proposal-card rounded-xl border border-border bg-card overflow-hidden ${className}`}>
        <div className="px-3 pt-3 pb-2 flex items-center gap-2">
          <PersonaBadge persona={persona} size={22} />
          <div><p className="text-xs font-semibold">{persona.name}</p><p className="text-[9px] text-muted-foreground">{persona.full_name}</p></div>
          <span className="ml-auto text-[9px] text-muted-foreground">{STATUS_LABEL[status]}</span>
          {dragHandle}
        </div>
        <div className="mx-3 mb-3 rounded-md bg-secondary/50 animate-pulse" style={{ height: 100 }} />
        <div className="mx-3 mb-3 flex gap-1">
          {[56, 44, 68].map((w, i) => <div key={i} className="h-4 rounded-full bg-secondary/60 animate-pulse" style={{ width: w }} />)}
        </div>
      </div>
    );
  }

  const addressed = issues.filter(issue => issue.personaIds.includes(persona.id));
  // 未点锚点时卡片保持原样；点了就只讲那一处，其余 chips 淡出而不是消失，
  // 免得卡片高度跳动打断对比阅读。
  const focusMode = Boolean(selectedIssueKey);
  const focused = focusMode ? addressed.find(issue => issue.key === selectedIssueKey) : undefined;
  const focusedSummary = focused
    ? treatmentSummary(focused.solutions.filter(s => s.personaId === persona.id), focused.treatmentLines?.[persona.id])
    : null;

  return (
    <div className={`viz-proposal-card rounded-xl border border-border bg-card overflow-hidden flex flex-col transition-all duration-150 shadow-[0_1px_2px_rgba(0,0,0,0.03)] hover:border-[#CFCFD6] ${className}`}>
      <div className="px-3.5 pt-3 pb-2.5 flex items-center gap-2">
        <PersonaBadge persona={persona} size={24} />
        <p className="text-[14px] font-semibold truncate flex-1 min-w-0">{persona.name}</p>
        {onFocus && <button onClick={e => { e.stopPropagation(); onFocus(); }} title="Enlarge chart" className="p-1.5 rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground shrink-0"><Maximize2 size={14} /></button>}
        {dragHandle}
      </div>

      <div className="mx-3.5 rounded-lg border border-border overflow-hidden bg-[#FAFAFB] p-2">
        <VegaLiteChart spec={proposal.modified_spec} maxHeight={null} />
      </div>

      {/* 议题引用 chips：完整问题细节在右栏，卡片只保留定位入口 */}
      <div className={`px-3.5 pt-2.5 mt-auto flex items-center gap-1.5 flex-wrap ${focusMode ? "pb-1.5" : "pb-2.5"}`}>
        {addressed.map(issue => {
          const active = selectedIssueKey === issue.key;
          return (
            <button
              key={issue.key}
              onClick={() => onSelectIssue(issue.key)}
              title={issue.label}
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-all ${
                active
                  ? "border-[#A1A1AA] bg-secondary text-foreground"
                  : focusMode
                    ? "border-border bg-white text-muted-foreground/50 opacity-40 hover:opacity-100"
                    : "border-border bg-white text-muted-foreground hover:text-foreground hover:border-[#D4D4D8]"
              }`}
            >
              #{issue.n} {issue.short}
            </button>
          );
        })}
        {addressed.length === 0 && <span className="text-[10px] text-muted-foreground">No issues raised</span>}
      </div>

      {/* 点选锚点后的联动：这张卡片就该锚点给一句话的处理说明 */}
      {focusMode && (
        <div className="px-3.5 pb-2.5">
          {focusedSummary ? (
            <>
              <p
                className="text-[10.5px] text-foreground/85 leading-snug"
                style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
                title={focusedSummary.treatment}
              >
                {firstSentence(focusedSummary.treatment)}
              </p>
              {focusedSummary.knowledge[0] && (
                <p className="mt-0.5 text-[9.5px] text-muted-foreground leading-snug" title={focusedSummary.knowledge.map(line => line.text).join(" ")}>
                  {focusedSummary.knowledge[0].text}
                </p>
              )}
            </>
          ) : (
            <p className="text-[10px] text-muted-foreground/60 italic">No change here</p>
          )}
        </div>
      )}
    </div>
  );
}

function moveIdBefore(order: string[], fromId: string, toId: string): string[] {
  if (fromId === toId) return order;
  const from = order.indexOf(fromId);
  const to = order.indexOf(toId);
  if (from < 0 || to < 0) return order;
  const next = [...order];
  next.splice(from, 1);
  next.splice(to, 0, fromId);
  return next;
}

function GalleryPanel({ personas, runPersonaIds, agents, proposals, originalSpec, issues, selectedIssueKey, onSelectIssue, stage }: {
  personas: PersonaMeta[];
  runPersonaIds: string[];
  agents: Record<string, AgentView>;
  proposals: Record<string, Proposal>;
  originalSpec: object | null;
  issues: DerivedIssue[];
  selectedIssueKey: string | null;
  onSelectIssue: (key: string) => void;
  stage: Stage;
}) {
  const visible = runPersonaIds
    .map(id => personas.find(p => p.id === id))
    .filter((p): p is PersonaMeta => Boolean(p));
  const [focusedPersonaId, setFocusedPersonaId] = useState<string | null>(null);
  const focusedPersona = focusedPersonaId ? visible.find(p => p.id === focusedPersonaId) : undefined;
  const [cardOrder, setCardOrder] = useState<string[]>(runPersonaIds);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  useEffect(() => {
    setCardOrder(prev => {
      const kept = prev.filter(id => runPersonaIds.includes(id));
      const added = runPersonaIds.filter(id => !kept.includes(id));
      const next = [...kept, ...added];
      if (next.length === prev.length && next.every((id, i) => id === prev[i])) return prev;
      return next;
    });
  }, [runPersonaIds]);

  const ordered = cardOrder
    .map(id => visible.find(p => p.id === id))
    .filter((p): p is PersonaMeta => Boolean(p));

  const cardProps = (p: PersonaMeta) => ({
    persona: p,
    agent: agents[p.id],
    proposal: proposals[p.id],
    issues,
    selectedIssueKey,
    onSelectIssue,
  });

  const endDrag = useCallback(() => {
    setDraggingId(null);
    setDropTargetId(null);
  }, []);

  const dragHandle = (personaId: string) => (
    <div
      role="button"
      tabIndex={0}
      draggable
      title="Drag to reorder"
      aria-label={`Reorder ${personaId} proposal`}
      className="ml-auto p-1.5 rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground cursor-grab active:cursor-grabbing shrink-0 select-none"
      onDragStart={event => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", personaId);
        const card = (event.currentTarget as HTMLElement).closest(".viz-sortable-card") as HTMLDivElement | null;
        if (card) event.dataTransfer.setDragImage(card, 28, 20);
        setDraggingId(personaId);
        setDropTargetId(null);
      }}
      onDragEnd={endDrag}
    >
      <GripVertical size={14} />
    </div>
  );

  return (
    <div className="proposal-gallery h-full min-w-0 flex flex-col min-h-0 bg-card">
      <div className="viz-panel-header px-5 min-h-14 flex items-center border-b border-border shrink-0 gap-3">
        <span className="text-[16px] font-semibold">Proposals</span>
        {focusedPersona && <button onClick={() => setFocusedPersonaId(null)} className="ml-auto px-2.5 py-1.5 rounded-md border border-border bg-white text-[11px] font-semibold hover:bg-secondary">Back to grid</button>}
      </div>

      {/* 原图固定在上方，作为始终可见的比较基准；提案区在下方独立滚动 */}
      <div className="shrink-0 px-4 pt-4 pb-3 bg-secondary/30 border-b border-border">
        <OriginalCard
          spec={originalSpec}
          issues={issues}
          selectedKey={selectedIssueKey}
          onSelect={onSelectIssue}
        />
      </div>

      <div
        className="viz-gallery-scroll flex-1 min-h-0 overflow-y-auto p-4 bg-secondary/30"
        style={{
          scrollbarWidth: "thin",
          scrollbarColor: "rgba(24,24,42,0.2) transparent",
          scrollbarGutter: "stable",
          overscrollBehavior: "contain",
        }}
      >
        {focusedPersona ? (
          <GalleryCard {...cardProps(focusedPersona)} />
        ) : stage === "idle" ? (
          <div className="flex flex-col items-center justify-center gap-3 text-center py-10">
            <div className="w-12 h-12 rounded-xl bg-card flex items-center justify-center border border-border">
              <Sparkles size={18} className="text-muted-foreground" />
            </div>
            <p className="text-xs font-medium">No agents summoned yet</p>
            <p className="text-[11px] text-muted-foreground max-w-[240px]">Select institutional personas on the left and click Generate Proposals — each runs slow-fast dual-process reasoning on your chart.</p>
          </div>
        ) : (
          <div className="viz-proposal-grid grid gap-3">
            {ordered.map(p => (
              <div
                key={p.id}
                className={`viz-sortable-card ${draggingId === p.id ? "opacity-40" : ""} ${dropTargetId === p.id && draggingId && draggingId !== p.id ? "ring-2 ring-[#7569E8] rounded-xl" : ""}`}
                onDragOver={event => {
                  if (!draggingId || draggingId === p.id) return;
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                  if (dropTargetId !== p.id) setDropTargetId(p.id);
                }}
                onDrop={event => {
                  event.preventDefault();
                  const fromId = event.dataTransfer.getData("text/plain") || draggingId;
                  if (fromId) setCardOrder(prev => moveIdBefore(prev, fromId, p.id));
                  endDrag();
                }}
              >
                <GalleryCard
                  {...cardProps(p)}
                  onFocus={() => setFocusedPersonaId(p.id)}
                  dragHandle={dragHandle(p.id)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Review Board（右栏：议程 / 讨论 / 合成托盘）────────────────────────────────

const CONFIDENCE_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

function IssueCard({ issue, personas, expanded, onToggleExpand, onOpenDiscussion, acceptedChanges, onToggleBundle }: {
  issue: DerivedIssue;
  personas: PersonaMeta[];
  expanded: boolean;
  onToggleExpand: () => void;
  onOpenDiscussion: () => void;
  acceptedChanges: DesignChange[];
  onToggleBundle: (changes: DesignChange[]) => void;
}) {
  const raisedBy = issue.personaIds
    .map(id => personas.find(p => p.id === id))
    .filter((p): p is PersonaMeta => Boolean(p));

  return (
    <div className={`rounded-lg border bg-white overflow-hidden transition-colors ${expanded ? "border-[#C5C2D6]" : "border-border"}`}>
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpand}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") onToggleExpand(); }}
        className="w-full flex items-start gap-2 px-3 py-2.5 cursor-pointer select-none"
      >
        <span className="text-[10px] font-bold text-muted-foreground shrink-0 pt-0.5">#{issue.n}</span>
        <span className="text-[13px] font-semibold flex-1 min-w-0 leading-snug">{issue.label}</span>
        <span className="flex items-center gap-1 shrink-0">
          {raisedBy.map(p => <PersonaBadge key={p.id} persona={p} size={16} />)}
          <span className="text-[10px] text-muted-foreground ml-0.5">{issue.personaIds.length}/{personas.length}</span>
        </span>
        <span className="text-muted-foreground shrink-0">{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
      </div>

      {expanded && (
        <div className="px-3 pb-3 space-y-1.5">
          {issue.blurb && (
            <p className="text-[11px] text-muted-foreground leading-relaxed">{issue.blurb}</p>
          )}
          {/* 每个机构一张处理卡：问题是什么 / 怎么处理的 / 依据哪条指南 */}
          {issue.personaIds.map(pid => {
            const persona = personas.find(p => p.id === pid);
            const bundle = [...issue.solutions.filter(s => s.personaId === pid)].sort((a, b) =>
              a.change.status === b.change.status
                ? (CONFIDENCE_RANK[a.change.confidence] ?? 3) - (CONFIDENCE_RANK[b.change.confidence] ?? 3)
                : a.change.status === "applied" ? -1 : 1,
            );
            const primary = bundle[0];
            if (!primary) return null;
            const changes = bundle.map(s => s.change);
            const adopted = changes.every(ch => acceptedChanges.some(c => c.id === ch.id));
            const adoptable = changes.every(ch => ch.contract?.verified !== false);
            const summary = treatmentSummary(bundle, issue.treatmentLines?.[pid]);
            return (
              <div key={pid} className="rounded-lg border border-border bg-[#FAFAFB] p-2.5 flex items-start gap-2">
                {persona && <PersonaBadge persona={persona} size={18} />}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[11px] font-bold" style={{ color: persona?.brand_color }}>{persona?.name ?? pid}</span>
                    {primary.change.status === "suggested" && (
                      <span className="text-[8px] text-sky-700 border border-sky-200 bg-sky-50 rounded px-1 py-px">suggestion</span>
                    )}
                  </div>
                  <div className="mt-1.5 space-y-1.5">
                    <SummaryRow label="Change" text={summary.treatment} />
                    {summary.knowledge.length > 0 && (
                      <div className="flex items-start gap-2 min-w-0">
                        <span className="shrink-0 w-[68px] pt-px text-[8.5px] font-bold uppercase tracking-wide text-muted-foreground/70">Knowledge</span>
                        <div className="min-w-0 flex-1 space-y-1.5">
                          {summary.knowledge.map(line => (
                            <div key={`${line.layer}:${line.text}`} className="flex items-start gap-1.5">
                              <LayerMark layer={line.layer} />
                              <p className="text-[11px] text-muted-foreground leading-relaxed min-w-0 flex-1">
                                <ColorCopy text={line.text} />
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                <AdoptButton
                  accepted={adopted}
                  disabled={!adoptable}
                  title={!adoptable ? "This change does not match a verified source-to-candidate diff and cannot be composed." : undefined}
                  onClick={() => onToggleBundle(changes)}
                />
              </div>
            );
          })}

          <button
            onClick={onOpenDiscussion}
            className="text-[11px] font-semibold text-[#5146C7] hover:underline flex items-center gap-1"
          >
            <MessageSquare size={11} />
            Open discussion
          </button>
        </div>
      )}
    </div>
  );
}

/** 议题的预设追问：命中率高的通用问题 + 冲突/多机构情境问题 */
function quickAsksFor(issue: DerivedIssue): string[] {
  const asks = ["Why does this matter for my chart?"];
  if (issue.conflictNodes.length > 0) asks.push("Can you find a middle ground?");
  if (issue.personaIds.length > 1) asks.push("Whose approach fits a general audience better?");
  asks.push("What if I keep the original?");
  return asks.slice(0, 3);
}

function DiscussionView({ issue, personas, acceptedChanges, onToggleBundle, onBack, thread, onSend }: {
  issue: DerivedIssue;
  personas: PersonaMeta[];
  acceptedChanges: DesignChange[];
  onToggleBundle: (changes: DesignChange[]) => void;
  onBack: () => void;
  thread: DiscussAsk[];
  onSend: (question: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  const pending = thread.some(a => a.pending);
  const askedQuestions = new Set(thread.map(a => a.question));
  // 议程合成的预设问题贴合具体议题；缺席时回落通用模板
  const quickAsks = (issue.quickAsks?.length ? issue.quickAsks : quickAsksFor(issue)).filter(
    q => !askedQuestions.has(q),
  );

  // 新消息出现时滚到底部（仅讨论线程内）
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [thread]);

  const submit = (question: string) => {
    if (!question.trim() || pending) return;
    onSend(question.trim());
    setDraft("");
  };

  const raisedNames = issue.personaIds
    .map(id => personas.find(p => p.id === id)?.name ?? id)
    .join(" and ");
  // 主持人开场白：优先用议程合成的叙事（概括机构策略如何分歧/一致），缺席时回落模板
  const intro =
    issue.discussionIntro ??
    (issue.personaIds.length > 1
      ? `${raisedNames} both raised this issue${issue.conflictNodes.length ? ` and disagree on ${issue.conflictNodes.join(", ")}` : ""}. Each position below cites its guideline warrant — adopt directly, or ask a follow-up.`
      : `Raised by ${raisedNames} alone. The position below cites its guideline warrant — adopt it, or ask a follow-up.`);

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <button onClick={onBack} className="px-2 py-1 rounded-md border border-border bg-white text-[10px] font-semibold flex items-center gap-1 hover:bg-secondary shrink-0">
          <ArrowLeft size={11} />Agenda
        </button>
        <span className="text-[10px] font-bold text-muted-foreground shrink-0">#{issue.n}</span>
        <span className="text-[13px] font-semibold leading-snug">{issue.label}</span>
      </div>

      <div className="flex items-start gap-2">
        <ModeratorBadge size={20} />
        <div className="flex-1 rounded-xl bg-secondary/50 px-3 py-2">
          <p className="text-[9px] font-bold text-muted-foreground tracking-wide mb-0.5">LEAD · MODERATOR</p>
          <p className="text-[11px] leading-relaxed">{intro}</p>
        </div>
      </div>

      {/* 每个机构一条立场气泡：理由（机构声音）+ 效果行 + 指南逐字引用 */}
      {issue.personaIds.map(pid => {
        const persona = personas.find(p => p.id === pid);
        const bundle = [...issue.solutions.filter(s => s.personaId === pid)].sort((a, b) =>
          a.change.status === b.change.status
            ? (CONFIDENCE_RANK[a.change.confidence] ?? 3) - (CONFIDENCE_RANK[b.change.confidence] ?? 3)
            : a.change.status === "applied" ? -1 : 1,
        );
        const primary = bundle[0];
        if (!primary) return null;
        const changes = bundle.map(s => s.change);
        const adopted = changes.every(ch => acceptedChanges.some(c => c.id === ch.id));
        const adoptable = changes.every(ch => ch.contract?.verified !== false);
        const summary = treatmentSummary(bundle, issue.treatmentLines?.[pid]);
        return (
          <div key={pid} className="flex items-start gap-2">
            {persona ? <PersonaBadge persona={persona} size={20} /> : <div className="w-5" />}
            <div className="flex-1 min-w-0 rounded-xl border border-border bg-white px-3 py-2">
              <div className="flex items-center gap-1.5 flex-wrap mb-1">
                <span className="text-[10px] font-bold" style={{ color: persona?.brand_color }}>{persona?.name ?? pid}</span>
                <span className="ml-auto">
                  <AdoptButton
                    accepted={adopted}
                    disabled={!adoptable}
                    title={!adoptable ? "This change does not match a verified source-to-candidate diff and cannot be composed." : undefined}
                    onClick={() => onToggleBundle(changes)}
                  />
                </span>
              </div>
              <p className="text-[11px] leading-relaxed"><ColorCopy text={summary.treatment} /></p>
              {summary.knowledge.length > 0 && (
                <div className="mt-1.5 space-y-1">
                  {summary.knowledge.map(line => (
                    <p key={`${line.layer}:${line.text}`} className="text-[10px] text-muted-foreground/90 leading-relaxed flex items-start gap-1.5">
                      <LayerMark layer={line.layer} />
                      <span className="min-w-0 flex-1"><ColorCopy text={line.text} /></span>
                    </p>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* 问答线程：用户提问 → 各机构回复 → 主持人合成 */}
      {thread.map((ask, askIdx) => (
        <div key={askIdx} className="flex flex-col gap-2.5">
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-xl bg-[#F0EEFF] border border-[#E0DBFA] px-3 py-2">
              <p className="text-[9px] font-bold text-[#5146C7] tracking-wide mb-0.5">YOU</p>
              <p className="text-[11px] leading-relaxed">{ask.question}</p>
            </div>
          </div>

          {ask.pending && (
            <div className="flex items-center gap-2 text-muted-foreground pl-1">
              <Loader2 size={12} className="animate-spin shrink-0" />
              <span className="text-[10px]">Agents are considering…</span>
            </div>
          )}
          {ask.error && (
            <p className="text-[10px] text-red-600 pl-1 flex items-start gap-1">
              <CircleAlert size={11} className="shrink-0 mt-0.5" />{ask.error}
            </p>
          )}

          {ask.replies.map(reply => {
            const persona = personas.find(p => p.id === reply.persona_id);
            return (
              <div key={`${askIdx}-${reply.persona_id}`} className="flex items-start gap-2">
                {persona ? <PersonaBadge persona={persona} size={20} /> : <div className="w-5" />}
                <div className="flex-1 min-w-0 rounded-xl border border-border bg-white px-3 py-2">
                  <p className="text-[10px] font-bold mb-0.5" style={{ color: persona?.brand_color }}>
                    {persona?.name ?? reply.persona_name}
                  </p>
                  <p className="text-[11px] leading-relaxed">{reply.text}</p>
                  {reply.citations.map((cite, i) => (
                    <div key={i} className="mt-1.5">
                      <p className="text-[10px] italic text-muted-foreground/90 border-l-2 border-border pl-2 leading-relaxed">{cite.quote}</p>
                      <p className="text-[9px] text-muted-foreground/70 mt-0.5 pl-2">
                        {cite.source_file || "guideline"}
                        {cite.src.length > 0 && ` · ${cite.src.join(", ")}`}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}

          {ask.synthesis && (
            <div className="flex items-start gap-2">
              <ModeratorBadge size={20} />
              <div className="flex-1 rounded-xl bg-secondary/50 px-3 py-2">
                <p className="text-[9px] font-bold text-muted-foreground tracking-wide mb-0.5">LEAD · SYNTHESIS</p>
                <p className="text-[11px] leading-relaxed">{ask.synthesis}</p>
              </div>
            </div>
          )}
        </div>
      ))}
      <div ref={endRef} />

      {/* 预设追问 + 自由输入（POST /api/advisor/discuss） */}
      <div className="rounded-xl border border-border bg-white px-3 py-2.5 space-y-2">
        {quickAsks.length > 0 && (
          <div>
            <p className="text-[8px] font-bold text-muted-foreground/70 tracking-[0.08em] mb-1">SUGGESTED QUESTIONS — CLICK TO SEND</p>
            <div className="flex flex-wrap gap-1">
              {quickAsks.map(q => (
                <button
                  key={q}
                  onClick={() => submit(q)}
                  disabled={pending}
                  className="rounded-full border border-border bg-[#FAFAFB] px-2 py-1 text-[10px] text-foreground/80 hover:border-[#CFC9FA] hover:bg-[#F7F5FF] hover:text-[#5146C7] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <input
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") submit(draft); }}
            disabled={pending}
            placeholder="Ask the agents a follow-up…"
            className="flex-1 min-w-0 rounded-lg border border-[#E4E4E7] bg-[#FAFAFB] px-2.5 py-1.5 text-[11px] text-foreground placeholder:text-[#A1A1AA] focus:outline-none focus:border-[#7569E8] focus:ring-2 focus:ring-[#F0EEFF] disabled:opacity-60"
          />
          <button
            onClick={() => submit(draft)}
            disabled={pending || !draft.trim()}
            title="Send"
            className="shrink-0 w-7 h-7 rounded-lg bg-primary text-white flex items-center justify-center hover:bg-[#5146C7] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {pending ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
          </button>
        </div>
      </div>
    </div>
  );
}

interface ReviewBoardProps {
  stage: Stage;
  runPersonas: PersonaMeta[];
  issues: DerivedIssue[];
  selectedIssueKey: string | null;
  onSelectIssue: (key: string | null) => void;
  discussionIssueKey: string | null;
  onOpenDiscussion: (key: string | null) => void;
  acceptedChanges: DesignChange[];
  onToggleBundle: (changes: DesignChange[]) => void;
  onRemoveAccepted: (id: string | string[]) => void;
  discussThreads: Record<string, DiscussAsk[]>;
  onSendQuestion: (issue: DerivedIssue, question: string) => void;
  instructions: string;
  onInstructionsChange: (text: string) => void;
  onCompose: () => void;
  applying: boolean;
  composeResult: ApplyResult | null;
  personasById: (id: string) => PersonaMeta | undefined;
}

function ReviewBoardPanel({
  stage, runPersonas, issues, selectedIssueKey, onSelectIssue,
  discussionIssueKey, onOpenDiscussion,
  acceptedChanges, onToggleBundle, onRemoveAccepted,
  discussThreads, onSendQuestion,
  instructions, onInstructionsChange, onCompose, applying, composeResult,
  personasById,
}: ReviewBoardProps) {
  const exportViewRef = useRef<VegaViewHandle | null>(null);
  const [viewReady, setViewReady] = useState(false);
  const [exporting, setExporting] = useState<"png" | "svg" | "json" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [skippedOpen, setSkippedOpen] = useState(false);

  const discussionIssue = discussionIssueKey ? issues.find(i => i.key === discussionIssueKey) : undefined;

  const handleExportView = useCallback((view: VegaViewHandle | null) => {
    exportViewRef.current = view;
    setViewReady(Boolean(view));
  }, []);

  const exportResult = useCallback(async (format: "png" | "svg" | "json") => {
    if (!composeResult) return;
    const filename = "visprism-composed";
    setExporting(format);
    setExportError(null);
    try {
      if (format === "json") {
        downloadTextFile(JSON.stringify(composeResult.final_spec, null, 2), `${filename}.json`, "application/json;charset=utf-8");
        return;
      }
      const view = exportViewRef.current;
      if (!view) throw new Error("The chart is still rendering. Please try again in a moment.");
      if (format === "svg") {
        const svg = await view.toSVG();
        downloadTextFile(svg, `${filename}.svg`, "image/svg+xml;charset=utf-8");
      } else {
        const pngUrl = await view.toImageURL("png", 2);
        downloadUrl(pngUrl, `${filename}.png`);
      }
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Export failed. Please try again.");
    } finally {
      setExporting(null);
    }
  }, [composeResult]);

  // 采纳来源统计（provenance）：每条被采纳修改可追溯至机构
  const provenance = useMemo(() => {
    const counts = new Map<string, number>();
    acceptedChanges.forEach(c => {
      const pid = personaIdOfChange(c.id);
      counts.set(pid, (counts.get(pid) ?? 0) + 1);
    });
    return [...counts.entries()]
      .map(([pid, n]) => `${personasById(pid)?.name ?? pid} ×${n}`)
      .join(" · ");
  }, [acceptedChanges, personasById]);

  const adoptedGroups = useMemo(() => groupAdoptedChanges(acceptedChanges), [acceptedChanges]);

  return (
    <div className="h-full min-w-0 border-l border-border bg-card flex flex-col">
      <div className="viz-panel-header px-5 min-h-14 flex items-center border-b border-border shrink-0 gap-2">
        <div className="flex-1 min-w-0">
          <span className="text-[16px] font-semibold">Agendas</span>
        </div>
        {acceptedChanges.length > 0 && (
          <span className="text-[11px] text-emerald-700 font-semibold bg-emerald-50 border border-emerald-200 rounded-full px-2 py-1 shrink-0">
            {acceptedChanges.length} adopted
          </span>
        )}
      </div>

      <ResizablePanelGroup direction="vertical" autoSaveId="viz-agenda-split" className="flex-1 min-h-0">
      <ResizablePanel defaultSize={55} minSize={20}>
      <div className="h-full min-h-0 overflow-y-auto p-3" style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(24,24,42,0.12) transparent" }}>
        {issues.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
            <div className="w-10 h-10 rounded-xl bg-secondary flex items-center justify-center">
              <Sparkles size={18} className="text-muted-foreground" />
            </div>
            <p className="text-[14px] font-semibold">{stage === "generating" ? "Agents are reasoning…" : "Agenda will appear here"}</p>
            <p className="text-[13px] text-muted-foreground leading-relaxed">
              {stage === "generating"
                ? "Issues are aggregated across institutions as proposals complete."
                : "Run agents to aggregate their findings into a prioritized issue agenda, ordered by cross-institution coverage."}
            </p>
          </div>
        ) : discussionIssue ? (
          <DiscussionView
            issue={discussionIssue}
            personas={runPersonas}
            acceptedChanges={acceptedChanges}
            onToggleBundle={onToggleBundle}
            onBack={() => onOpenDiscussion(null)}
            thread={discussThreads[discussionIssue.key] ?? []}
            onSend={question => onSendQuestion(discussionIssue, question)}
          />
        ) : (
          <div className="space-y-2">
            {issues.map(issue => (
              <IssueCard
                key={issue.key}
                issue={issue}
                personas={runPersonas}
                expanded={selectedIssueKey === issue.key}
                onToggleExpand={() => onSelectIssue(selectedIssueKey === issue.key ? null : issue.key)}
                onOpenDiscussion={() => onOpenDiscussion(issue.key)}
                acceptedChanges={acceptedChanges}
                onToggleBundle={onToggleBundle}
              />
            ))}
          </div>
        )}
      </div>
      </ResizablePanel>
      <ResizableHandle withHandle />
      <ResizablePanel defaultSize={45} minSize={16}>
      <div className="h-full min-h-0 overflow-y-auto px-3 py-3 space-y-2" style={{ scrollbarWidth: "thin" }}>
        <div className="flex items-center gap-2">
          <p className="text-[12px] font-semibold">Adopted ({acceptedChanges.length})</p>
          <button
            onClick={onCompose}
            disabled={acceptedChanges.length === 0 || applying}
            className="ml-auto px-3 py-1.5 rounded-lg bg-primary text-white text-[11px] font-semibold flex items-center gap-1.5 hover:bg-[#5146C7] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {applying ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />}
            Compose
          </button>
        </div>

        {acceptedChanges.length === 0 ? (
          <p className="text-[10px] text-muted-foreground">
            Adopt solutions from the agenda — they compose into one chart here, with provenance per institution.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1">
            {adoptedGroups.map(group => {
              const persona = personasById(group.personaId);
              return (
                <span
                  key={`${group.personaId}:${group.short}`}
                  className="flex items-center gap-1 bg-white border border-border rounded-md pl-1.5 pr-1 py-0.5"
                  title={group.items.map(item => item.reason).filter(Boolean).join("\n")}
                >
                  {persona && <PersonaBadge persona={persona} size={14} />}
                  <span className="text-[10px] font-medium">{persona?.name ?? group.personaId}</span>
                  <span className="text-[10px] text-muted-foreground">{group.short}</span>
                  <button
                    onClick={() => onRemoveAccepted(group.items.map(item => item.id))}
                    className="w-3.5 h-3.5 rounded-full flex items-center justify-center text-muted-foreground hover:bg-secondary"
                    aria-label={`Remove ${persona?.name ?? group.personaId} ${group.short}`}
                  >
                    <X size={9} />
                  </button>
                </span>
              );
            })}
          </div>
        )}

        {acceptedChanges.length > 0 && (
          <textarea
            value={instructions}
            onChange={e => onInstructionsChange(e.target.value)}
            rows={2}
            placeholder="Optional additional instruction for the final LLM composition…"
            className="w-full resize-none rounded-lg border border-[#E4E4E7] bg-[#FAFAFB] px-2.5 py-2 text-[11px] leading-relaxed text-foreground placeholder:text-[#A1A1AA] focus:outline-none focus:border-[#7569E8] focus:ring-2 focus:ring-[#F0EEFF]"
          />
        )}

        {composeResult && (
          <div className="rounded-lg border border-border bg-white overflow-hidden">
            <div className="p-2">
              <VegaLiteChart spec={composeResult.final_spec} maxHeight={220} onViewReady={handleExportView} />
            </div>
            <div className="px-2.5 pb-2 space-y-1.5">
              {provenance && (
                <p className="text-[9px] text-muted-foreground">Composed from {provenance}</p>
              )}
              {composeResult.conflicts.map(conflict => (
                <div key={`${conflict.node}-${conflict.winner_change_id}`} className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
                  <p className="text-[10px] font-semibold text-amber-800">Conflict on <span className="font-mono">{conflict.node}</span></p>
                  <p className="text-[10px] text-amber-800/90 mt-0.5 leading-relaxed">
                    Kept {personasById(conflict.winner_persona_id)?.name ?? conflict.winner_persona_id}: {conflict.winner_label} · dropped{" "}
                    {personasById(conflict.loser_persona_id)?.name ?? conflict.loser_persona_id}: {conflict.loser_label}
                  </p>
                </div>
              ))}
              {composeResult.skipped.length > 0 && (
                <div>
                  <button onClick={() => setSkippedOpen(v => !v)} className="text-[9px] font-semibold text-muted-foreground hover:text-foreground flex items-center gap-1">
                    {skippedOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                    {composeResult.skipped.length} skipped
                  </button>
                  {skippedOpen && (
                    <ul className="mt-1 space-y-0.5">
                      {composeResult.skipped.map(s => (
                        <li key={s.id} className="text-[9px] text-muted-foreground leading-relaxed">{s.id}: {s.reason}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <div className="grid grid-cols-3 gap-1.5 pt-0.5">
                <button
                  type="button"
                  onClick={() => void exportResult("png")}
                  disabled={!viewReady || Boolean(exporting)}
                  className="flex items-center justify-center gap-1 rounded-md bg-primary px-2 py-1.5 text-[10px] font-semibold text-primary-foreground hover:bg-[#5146C7] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {exporting === "png" ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                  PNG
                </button>
                <button
                  type="button"
                  onClick={() => void exportResult("svg")}
                  disabled={!viewReady || Boolean(exporting)}
                  className="flex items-center justify-center gap-1 rounded-md border border-border bg-white px-2 py-1.5 text-[10px] font-semibold hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {exporting === "svg" ? <Loader2 size={12} className="animate-spin" /> : <Code2 size={12} />}
                  SVG
                </button>
                <button
                  type="button"
                  onClick={() => void exportResult("json")}
                  disabled={Boolean(exporting)}
                  className="flex items-center justify-center gap-1 rounded-md border border-border bg-white px-2 py-1.5 text-[10px] font-semibold hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {exporting === "json" ? <Loader2 size={12} className="animate-spin" /> : <FileJson size={12} />}
                  JSON
                </button>
              </div>
              {exportError && <p role="alert" className="text-[9px] text-red-600">{exportError}</p>}
            </div>
          </div>
        )}
      </div>
      </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [personas, setPersonas] = useState<PersonaMeta[]>([]);
  const [stage, setStage] = useState<Stage>("idle");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [specText, setSpecText] = useState(DEFAULT_SPEC);
  const [communicationGoal, setCommunicationGoal] = useState("");
  const [agents, setAgents] = useState<Record<string, AgentView>>({});
  const [proposals, setProposals] = useState<Record<string, Proposal>>({});
  const [agenda, setAgenda] = useState<AgendaPayload | null>(null);
  const [runPersonaIds, setRunPersonaIds] = useState<string[]>([]);
  const [selectedIssueKey, setSelectedIssueKey] = useState<string | null>(null);
  const [discussionIssueKey, setDiscussionIssueKey] = useState<string | null>(null);
  const [discussThreads, setDiscussThreads] = useState<Record<string, DiscussAsk[]>>({});
  const [acceptedChanges, setAcceptedChanges] = useState<DesignChange[]>([]);
  const [instructions, setInstructions] = useState("");
  const [composeResult, setComposeResult] = useState<ApplyResult | null>(null);
  const [parsingAgents, setParsingAgents] = useState<ParsingAgent[]>([]);
  const [apiError, setApiError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);
  useEffect(() => () => stopPolling(), [stopPolling]);

  // 启动时拉取 persona 列表
  useEffect(() => {
    api.personas()
      .then(r => setPersonas(r.personas))
      .catch(e => setApiError((e as Error).message));
  }, []);

  const parsedSpec = useMemo(() => {
    try { return JSON.parse(specText) as object; } catch { return null; }
  }, [specText]);

  const runPersonas = useMemo(
    () => runPersonaIds.map(id => personas.find(p => p.id === id)).filter((p): p is PersonaMeta => Boolean(p)),
    [runPersonaIds, personas],
  );

  // 议题：优先用后端主持人议程（live 的自然叙事）；缺席/为空回落本地确定性派生
  const issues = useMemo(() => {
    if (agenda?.issues?.length) {
      const fromAgenda = issuesFromAgenda(agenda, runPersonas, proposals);
      if (fromAgenda.length) return fromAgenda;
    }
    return deriveIssues(runPersonas, proposals);
  }, [agenda, runPersonas, proposals]);

  const personasById = useCallback(
    (id: string) => personas.find(p => p.id === id),
    [personas],
  );

  const handleToggle = useCallback((id: string) => {
    setSelected(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }, []);

  // 轮询一个已经启动的 run，直到它跑完。真实咨询与历史复现走的是同一个端点，
  // 因此也共用这一段：复现之所以能在界面上"重演"，靠的就是它。
  const followRun = useCallback(async (runId: string) => {
    const poll = async () => {
      try {
        const r = await api.getRun(runId);
        setAgents(Object.fromEntries(r.agents.map(a => [a.persona_id, { status: a.status, progress: a.progress }])));
        setProposals(prev => {
          const next = { ...prev };
          r.agents.forEach(a => { if (a.proposal) next[a.persona_id] = a.proposal; });
          return next;
        });
        if (r.agenda) setAgenda(r.agenda);
        const failed = r.agents.filter(a => a.status === "error");
        if (failed.length) {
          setApiError(failed.map(a => `${a.persona_id}: ${a.error ?? "agent error"}`).join("；"));
        }
        if (r.status === "done") {
          stopPolling();
          setStage("generated");
        }
      } catch (e) {
        stopPolling();
        setStage("generated");
        setApiError((e as Error).message);
      }
    };
    await poll();
    pollRef.current = setInterval(poll, 650);
  }, [stopPolling]);

  // `?replay=<run_id>` 进入时复现一次历史咨询：把当初的原图、传播目标与参与机构
  // 装回界面，再沿用真实运行同一条轮询链路重演四拍。用户实验因此可以给每位被试
  // 发一个链接，打开即看同一段过程，而界面上与一次真实咨询没有分别。
  // `&pace=<毫秒>` 可临时调整每一拍的停留时间，便于预实验时校准节奏。
  // 位置必须在 followRun 声明之后：依赖数组在渲染时求值，提前引用会整页白屏。
  const replayStarted = useRef(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sourceRunId = params.get("replay");
    if (!sourceRunId || replayStarted.current) return;
    replayStarted.current = true;

    const pace = Number(params.get("pace"));
    (async () => {
      try {
        const run = await api.replayRun(sourceRunId, Number.isFinite(pace) && pace >= 0 ? pace : undefined);
        const ids = run.agents.map(a => a.persona_id);
        if (run.spec) setSpecText(JSON.stringify(run.spec, null, 2));
        setCommunicationGoal(run.context?.communication_goal ?? "");
        setSelected(new Set(ids));
        setRunPersonaIds(ids);
        setAgents(Object.fromEntries(ids.map(id => [id, { status: "pending" as AgentStatus, progress: 0.05 }])));
        setStage("generating");
        await followRun(run.run_id);
      } catch (e) {
        setApiError((e as Error).message);
      }
    })();
  }, [followRun]);

  const handleGenerate = useCallback(async () => {
    if (stage === "generated" && acceptedChanges.length > 0) {
      const confirmed = window.confirm("Regenerating will clear the agenda and your adopted decisions. Continue?");
      if (!confirmed) return;
    }
    setApiError(null);
    let spec: object;
    try {
      spec = JSON.parse(specText);
    } catch {
      setApiError("Chart Spec is not valid JSON");
      return;
    }
    const ids = personas.filter(p => selected.has(p.id)).map(p => p.id);
    if (!ids.length) return;

    stopPolling();
    setStage("generating");
    setAcceptedChanges([]);
    setInstructions("");
    setSelectedIssueKey(null);
    setDiscussionIssueKey(null);
    setDiscussThreads({});
    setComposeResult(null);
    setProposals({});
    setAgenda(null);
    setRunPersonaIds(ids);
    setAgents(Object.fromEntries(ids.map(id => [id, { status: "pending" as AgentStatus, progress: 0.05 }])));

    try {
      const context = communicationGoal.trim()
        ? { communication_goal: communicationGoal.trim() }
        : {};
      const run = await api.runAdvisor(spec, ids, context);
      await followRun(run.run_id);
    } catch (e) {
      setStage("idle");
      setApiError((e as Error).message);
    }
  }, [personas, selected, specText, communicationGoal, stopPolling, stage, acceptedChanges.length, followRun]);

  const handleAddPersonaFile = useCallback(async (file: File) => {
    const tempId = `parsing-${Date.now()}`;
    const rawName = file.name.replace(/\.(md|markdown|txt)$/i, "");
    setParsingAgents(prev => [...prev, { tempId, name: rawName.slice(0, 12) }]);
    setApiError(null);
    try {
      const { persona, warnings } = await api.parsePersona(file, rawName);
      setPersonas(prev => [...prev, persona]);
      setSelected(prev => new Set(prev).add(persona.id));
      if (warnings.length) setApiError(warnings.join("；"));
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setParsingAgents(prev => prev.filter(a => a.tempId !== tempId));
    }
  }, []);

  // 锚点 / 议题 chip / 议程卡共用的选中入口；打开讨论时自动切回议程视图
  const handleSelectIssue = useCallback((key: string | null) => {
    setSelectedIssueKey(key);
    setDiscussionIssueKey(null);
  }, []);

  const handleRemoveAccepted = useCallback((id: string | string[]) => {
    const ids = new Set(Array.isArray(id) ? id : [id]);
    setAcceptedChanges(prev => prev.filter(c => !ids.has(c.id)));
  }, []);

  // 议程行的打包采纳：一次采纳/撤销某机构在该议题下的全部修改，冲突节点仍二选一
  const handleToggleBundle = useCallback((changes: DesignChange[]) => {
    if (!changes.length || changes.some(change => change.contract?.verified === false)) return;
    setAcceptedChanges(prev => {
      const allIn = changes.every(ch => prev.some(c => c.id === ch.id));
      if (allIn) {
        const ids = new Set(changes.map(c => c.id));
        return prev.filter(c => !ids.has(c.id));
      }
      const bundlePersona = personaIdOfChange(changes[0].id);
      const nodes = new Set(changes.flatMap(changeNodes));
      const kept = nodes.size === 0
        ? prev
        : prev.filter(c => personaIdOfChange(c.id) === bundlePersona || !changeNodes(c).some(n => nodes.has(n)));
      const keptIds = new Set(kept.map(c => c.id));
      return [...kept, ...changes.filter(c => !keptIds.has(c.id))];
    });
  }, []);

  // 讨论区追问：调用 /api/advisor/discuss，回复按议题存入线程
  const handleSendQuestion = useCallback(async (issue: DerivedIssue, rawQuestion: string) => {
    const question = rawQuestion.trim();
    if (!question) return;
    let spec: object;
    try {
      spec = JSON.parse(specText);
    } catch {
      setApiError("Chart Spec is not valid JSON");
      return;
    }
    const issueKey = issue.key;
    const prior = discussThreads[issueKey] ?? [];
    const history: DiscussHistoryItem[] = prior.flatMap(ask => [
      { role: "user", text: ask.question },
      ...ask.replies.map(r => ({ role: r.persona_id, text: r.text })),
      ...(ask.synthesis ? [{ role: "moderator", text: ask.synthesis }] : []),
    ]);
    setDiscussThreads(prev => ({
      ...prev,
      [issueKey]: [...(prev[issueKey] ?? []), { question, replies: [], synthesis: null, pending: true, error: null }],
    }));
    try {
      const res = await api.discuss(
        spec,
        issue.personaIds,
        { key: issue.key, label: issue.label, changes: issue.solutions.map(s => s.change) },
        question,
        history,
        communicationGoal.trim() ? { communication_goal: communicationGoal.trim() } : {},
      );
      setDiscussThreads(prev => {
        const asks = [...(prev[issueKey] ?? [])];
        const last = asks.length - 1;
        if (last >= 0 && asks[last].pending) {
          asks[last] = { ...asks[last], replies: res.replies, synthesis: res.synthesis?.text ?? null, pending: false };
        }
        return { ...prev, [issueKey]: asks };
      });
    } catch (e) {
      setDiscussThreads(prev => {
        const asks = [...(prev[issueKey] ?? [])];
        const last = asks.length - 1;
        if (last >= 0 && asks[last].pending) {
          asks[last] = { ...asks[last], pending: false, error: (e as Error).message };
        }
        return { ...prev, [issueKey]: asks };
      });
    }
  }, [specText, discussThreads, communicationGoal]);

  const handleCompose = useCallback(async () => {
    if (!acceptedChanges.length || applying) return;
    let spec: object;
    try {
      spec = JSON.parse(specText);
    } catch {
      setApiError("Chart Spec is not valid JSON");
      return;
    }
    setApplying(true);
    setApiError(null);
    try {
      const context = communicationGoal.trim()
        ? { communication_goal: communicationGoal.trim() }
        : {};
      const res = await api.applyDesign(spec, acceptedChanges, instructions.trim(), context);
      setComposeResult(res);
    } catch (e) {
      setApiError((e as Error).message);
    } finally {
      setApplying(false);
    }
  }, [acceptedChanges, applying, specText, instructions, communicationGoal]);

  return (
    <div className="viz-app h-screen flex flex-col bg-background overflow-hidden" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <TopBar />
      <ResizablePanelGroup direction="horizontal" className="flex-1 min-h-0">
        <ResizablePanel defaultSize={24} minSize={18} maxSize={38}>
          <InputPanel
            personas={personas}
            selected={selected}
            onToggle={handleToggle}
            agents={agents}
            stage={stage}
            onGenerate={handleGenerate}
            specText={specText}
            onSpecChange={setSpecText}
            communicationGoal={communicationGoal}
            onCommunicationGoalChange={setCommunicationGoal}
            parsingAgents={parsingAgents}
            onAddPersonaFile={handleAddPersonaFile}
            error={apiError}
          />
        </ResizablePanel>
        <ResizableHandle withHandle className="hover:bg-primary/40" />
        <ResizablePanel defaultSize={44} minSize={25}>
          <GalleryPanel
            personas={personas}
            runPersonaIds={runPersonaIds}
            agents={agents}
            proposals={proposals}
            originalSpec={parsedSpec}
            issues={issues}
            selectedIssueKey={selectedIssueKey}
            onSelectIssue={handleSelectIssue}
            stage={stage}
          />
        </ResizablePanel>
        <ResizableHandle withHandle className="hover:bg-primary/40" />
        <ResizablePanel defaultSize={32} minSize={24} maxSize={46}>
          <ReviewBoardPanel
            stage={stage}
            runPersonas={runPersonas}
            issues={issues}
            selectedIssueKey={selectedIssueKey}
            onSelectIssue={handleSelectIssue}
            discussionIssueKey={discussionIssueKey}
            onOpenDiscussion={setDiscussionIssueKey}
            acceptedChanges={acceptedChanges}
            onToggleBundle={handleToggleBundle}
            onRemoveAccepted={handleRemoveAccepted}
            discussThreads={discussThreads}
            onSendQuestion={handleSendQuestion}
            instructions={instructions}
            onInstructionsChange={setInstructions}
            onCompose={handleCompose}
            applying={applying}
            composeResult={composeResult}
            personasById={personasById}
          />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
