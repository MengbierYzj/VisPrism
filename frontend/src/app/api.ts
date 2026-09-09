// ─── Backend API client（契约见 doc/api/接口文档.md） ────────────────────────

export interface PersonaMeta {
  id: string;
  name: string;
  full_name: string;
  domain: string;
  /** taxonomy 分类：Government / Education / Non-profit / News / Profit；自定义为 Other */
  category?: string;
  kind: "builtin" | "custom";
  source: string;
  brand_color: string;
  palette: string[];
  abbr: string;
  layers: { l1_rules: number; l2_adaptations: number; l3_philosophy: number; l3_stories: number };
  applicability?: Record<string, unknown>;
}

export interface Warrant {
  src: string[];
  story_id: string;
  story: string;
  quote: string;
  source_file: string;
  derived: boolean;
}

export interface DesignChange {
  id: string;
  rule_id: string;
  label: string;
  reason: string;
  prompt: string;
  layer: "L1" | "L2" | "L3-derived" | "user";
  strength: string;
  confidence: "high" | "medium" | "low";
  status: "applied" | "suggested";
  warrant: Warrant;
  ops: Record<string, unknown>[];
  /** v2：这条改动所属的设计部件（title/color/labels/axes/layout/typography/structure） */
  scope?: string;
  /** v2 语义组装：该条改动落到 spec 的哪些节点，改前改后各是什么 */
  component_detail?: ComponentDetail;
  /** v2：这条改动回应的视觉审阅问题（引用不到具体 finding 时缺省） */
  problem?: string;
  problem_evidence?: string;
  severity?: string;
  /** v2：这条改动兑现的主层机构知识 */
  knowledge?: ChangeKnowledge;
  /** v2：同一改动兑现的各层知识（L1 Traits / L2 Adaptations / L3 Identity） */
  knowledge_layers?: ChangeKnowledge[];
  /** Advisor change 与真实 source→candidate diff 的程序核验结果。 */
  contract?: ChangeContract;
}

export interface ChangeContract {
  verified: boolean;
  source: string;
  scope: string;
  actual_paths?: string[];
  set_paths?: string[];
  removed_paths?: string[];
  compatible_scopes?: Record<string, string[]>;
  verification_errors?: string[];
}

export interface ChangeKnowledge {
  layer: "L1" | "L2" | "L3";
  /** L1：规则条文原句 */
  rule?: string;
  /** L1：改后落到图上的具体令牌（"Title color London 10 (#1A1A1A)"） */
  applied?: string;
  /** L1：改后用到的机构命名令牌（色板/品牌色） */
  tokens?: { name: string; value: string }[];
  /** L2：触发这条适应的条件，已念成从句 */
  condition?: string;
  /** L3：机构宣示过的设计哲学关键词 */
  philosophy?: string;
  /** L2/L3：叙事或哲学原文，帮助理解为什么用这一层 */
  quote?: string;
  /** L3：哲学条目标题 */
  title?: string;
}

export interface ComponentDetail {
  before?: string;
  after?: string;
  spec_paths?: string[];
  execution?: string;
}

export interface RejectedItem {
  rule_id: string;
  layer: string;
  label: string;
  reason: string;
  src: string[];
}

export interface TraceBeat {
  beat: number;
  lane: "fast" | "slow";
  name: string;
  ms: number;
  summary: string;
  mode?: string;
}

export interface Proposal {
  persona_id: string;
  persona_name: string;
  facts: Record<string, unknown>;
  original_spec: object;
  modified_spec: object;
  changes: DesignChange[];
  rejected: RejectedItem[];
  invariants: { rule_id: string; ok: boolean; detail: string }[];
  trace: TraceBeat[];
  summary: string;
  elapsed_ms: number;
  /** v2 delivery gate; rejected proposals keep audit metadata but expose no executable changes. */
  delivery_state?: "ready" | "needs_vega_lite_repair" | "rejected_by_visual_gate";
  delivery_reason?: string | null;
}

export type AgentStatus =
  | "pending" | "reading" | "detecting" | "adjudicating" | "compiling" | "done" | "error";

export interface AgentPayload {
  persona_id: string;
  status: AgentStatus;
  progress: number;
  proposal: Proposal | null;
  error: string | null;
}

// 主持人议程合成（live 运行结束时由后端产出；mock/失败为 null，前端回落本地派生）
export interface AgendaTreatment {
  persona_id: string;
  line: string;
  /** 机构决策的规范依据行：L2 统一 "When …, …" 句式，L1 陈述馆规，L3 引哲学原则 */
  why: string;
  change_ids: string[];
}

export interface AgendaIssue {
  title: string;
  blurb: string;
  category: string;
  discussion_intro: string;
  quick_asks: string[];
  treatments: AgendaTreatment[];
}

export interface AgendaPayload {
  issues: AgendaIssue[];
}

export interface RunPayload {
  run_id: string;
  status: "running" | "done";
  agenda?: AgendaPayload | null;
  agents: AgentPayload[];
  /** 复现历史运行时才有：被复现的原始 run_id，以及当初那张原图与语境。 */
  replay_of?: string;
  spec?: object;
  context?: AdvisorContext;
}

export interface AdvisorContext {
  medium?: string;
  viewport_px?: number;
  communication_goal?: string;
}

export interface ApplyConflict {
  node: string;
  winner_persona_id: string;
  winner_change_id: string;
  winner_label: string;
  loser_persona_id: string;
  loser_change_id: string;
  loser_label: string;
  winner_effect: string;
  loser_effect: string;
  reason: string;
}

export interface ApplyResult {
  final_spec: object;
  applied: string[];
  skipped: { id: string; reason: string }[];
  conflicts: ApplyConflict[];
  notes: string[];
  composition?: {
    mode: "llm_reconstruction" | "deterministic_projection" | "deterministic_ops" | "deterministic_fallback";
    llm_called: boolean;
    decision_count: number;
    realized_count: number;
    implementation?: { change_id: string; realized_paths: string[]; note?: string }[];
    render?: Record<string, unknown>;
    visual_review?: Record<string, unknown> | null;
    fallback_reason?: string;
  };
}

export interface HealthPayload {
  ok: boolean;
  llm_mode: "live" | "mock";
  model: string | null;
  personas: number;
}

// ─── Review Board 议题讨论（POST /api/advisor/discuss） ─────────────────────────

export interface DiscussCitation {
  quote: string;
  src: string[];
  source_file: string;
}

export interface DiscussReply {
  persona_id: string;
  persona_name: string;
  text: string;
  citations: DiscussCitation[];
}

export interface DiscussResult {
  issue_key: string | null;
  replies: DiscussReply[];
  synthesis: { text: string } | null;
  conflict_nodes: string[];
  llm_mode: "live" | "mock";
  outcome: "live" | "live_fallback" | "mock";
}

export interface DiscussIssuePayload {
  key: string;
  label: string;
  changes: DesignChange[];
}

export interface DiscussHistoryItem {
  role: string; // "user" | "moderator" | persona_id
  text: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error("Unable to connect to the backend. Start the backend service first.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = body?.error?.message ?? `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body as T;
}

export const api = {
  health: () => request<HealthPayload>("/api/health"),

  personas: () => request<{ personas: PersonaMeta[] }>("/api/personas"),

  parsePersona: (file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return request<{ persona: PersonaMeta; warnings: string[] }>("/api/personas/parse", {
      method: "POST",
      body: form,
    });
  },

  uploadSpec: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ file_id: string; spec: object; facts: Record<string, unknown> }>(
      "/api/upload",
      { method: "POST", body: form },
    );
  },

  runAdvisor: (spec: object, personaIds: string[], context: AdvisorContext = {}) =>
    request<RunPayload>("/api/advisor/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec, persona_ids: personaIds, context }),
    }),

  getRun: (runId: string) => request<RunPayload>(`/api/advisor/run/${runId}`),

  /** 复现一次已保存的历史运行：只读重放，不调用 LLM，也不改写原记录。 */
  replayRun: (runId: string, beatDelayMs?: number) =>
    request<RunPayload>("/api/v2/advisor/replay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: runId,
        ...(beatDelayMs === undefined ? {} : { beat_delay_ms: beatDelayMs }),
      }),
    }),

  applyDesign: (spec: object, changes: DesignChange[], instructions = "", context: AdvisorContext = {}) =>
    request<ApplyResult>("/api/design/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec, changes, instructions, context }),
    }),

  discuss: (
    spec: object,
    personaIds: string[],
    issue: DiscussIssuePayload,
    question: string,
    history: DiscussHistoryItem[] = [],
    context: AdvisorContext = {},
  ) =>
    request<DiscussResult>("/api/advisor/discuss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec, persona_ids: personaIds, issue, question, history, context }),
    }),
};
