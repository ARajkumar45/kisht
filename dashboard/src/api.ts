// Typed client for the Kisht contact-centre API (src/kisht/api.py).

export type Call = {
  call_id: string;
  lender_id: string;
  borrower_id: string | null;
  loan_id: string | null;
  borrower_name: string | null;
  channel: string;
  language: string | null;
  started_utc: string;
  ended_utc: string | null;
  status: "live" | "ended";
  outcome: string | null;
  note: string | null;
  turns: number;
  blocks: number;
  source: string | null;
  reason?: string | null;
  sentiment?: string | null;
  qa_score?: number | null;
};

export type Turn = {
  idx: number;
  at_utc: string;
  language: string | null;
  borrower: string;
  agent: string;
  tools: string[];
  refused: string[];
  replaced: string[];
  seconds: number | null;
  model_calls: number | null;
  prompt_tokens: number | null;
  cached_tokens: number | null;
  coach: string | null;
};

export type Span = {
  span_id: string;
  trace_id: string;
  parent_id: string | null;
  name: string;
  start_ns: number;
  end_ns: number;
  status: string;
  attrs: Record<string, unknown>;
};

export type QAResult = "pass" | "fail" | "na";
export type QAItem = { id: string; check: string; result: QAResult; evidence: string; by: string; human: { result: QAResult; by: string } | null };
export type Compliance = { rule: string; label: string; blocked: number; status: string };

export type Review = {
  reason: string;
  sentiment: string;
  summary: string;
  qa: QAItem[];
  qa_score: number | null;
  compliance: Compliance[];
  model: string;
  seconds: number;
  human_reviewed: boolean;
  final_score: number | null;
};

export type CallDetail = {
  call: Call;
  turns: Turn[];
  spans: Span[];
  review: Review | null;
  actions: Record<"promises" | "links" | "escalations" | "followups", Record<string, unknown>[]>;
  audit: AuditEntry[];
};

export type AuditEntry = { time: string; action: string; outcome: "ok" | "denied" | "error"; detail: string };

export type Overview = {
  calls: number;
  live: number;
  ended: number;
  rates: Record<"right_party_contact" | "promise" | "link_sent" | "escalated" | "opted_out" | "containment", number | null>;
  handle_time_s: number | null;
  by_language: { language: string; calls: number; resolved_pct: number | null; escalated_pct: number | null; qa: number | null; blocked: number }[];
  money: { promises: number; promised_amount: number; links: number; link_amount: number };
  outcomes: Record<string, number>;
  escalations: Record<string, number>;
  reasons: Record<string, number>;
  sentiment: Record<string, number>;
  languages: Record<string, number>;
  qa: { average: number | null; reviewed: number };
  blocked: Record<string, number>;
  speed: { median_turn_s: number | null; model_calls_per_turn: number | null; cache_hit_pct: number | null };
};

export type PlanItem = {
  loan_id: string;
  borrower_id: string;
  name: string;
  language: string;
  city: string;
  emi: number;
  channel: string;
  priority: string;
  reason: string;
  approach: string;
  status: string;
  days_past_due: number;
  overdue_amount: number;
  call_id: string | null;
  outcome: string | null;
};

export type Alert = { call_id: string; at: string; borrower_name: string | null; kind: string; said: string };
export type Live = { live: (Call & { last_turns: Turn[] })[]; alerts: Alert[] };

export type DeskItem = {
  id: string;
  loan_id: string;
  reason: string;
  summary: string;
  call_id: string | null;
  created_utc: string;
  borrower_id: string;
  borrower_name: string;
  language: string;
  city: string;
  emi: number;
  team: string;
  age_hours: number;
  sla_hours: number;
  breached: boolean;
  status: "open" | "in_progress" | "resolved";
  assignee: string | null;
  resolution: string | null;
  review: { summary: string; sentiment: string } | null;
};

export type Assist = {
  brief?: string;
  next_best_action?: string;
  suggested_replies?: string[];
  watch_out?: string;
  dues: Record<string, unknown>;
  model: string;
};

export type Answer = { answer: string; sections: { id: string; title: string; text: string }[] };
export type Borrower = { id: string; name: string; language: string; city: string; loan_id: string; emi: number; product: string };
export type ChatTurn = { reply: string; tools: string[]; refused: string[]; replaced: string[]; promise_saved: boolean; ended: string | null; seconds: number };

export type EvalRun = {
  run: string;
  runs: number;
  personas: number;
  k: number;
  pass_1: number;
  pass_k: number;
  by_category: Record<string, { personas: number; pass_1: number }>;
  median_turn_s: number;
};
export type Calibration = {
  calls: number;
  items: number;
  agreement_pct: number | null;
  disagreements: { call_id: string; item: string; ai: QAResult; human: QAResult; by: string }[];
};
export type Quality = {
  evals: EvalRun[];
  qa_items: { id: string; pass: number; fail: number; na: number; pass_rate: number | null; failing_calls: string[] }[];
  calibration: Calibration;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  overview: () => call<Overview>("/api/overview"),
  plan: () => call<{ date: string | null; items: PlanItem[]; counts: Record<string, number> }>("/api/plan"),
  calls: (params: Record<string, string>) => call<Call[]>("/api/calls?" + new URLSearchParams(params)),
  call: (id: string) => call<CallDetail>(`/api/calls/${id}`),
  callsCsv: (params: Record<string, string>) => "/api/export/calls.csv?" + new URLSearchParams(params),
  coach: (id: string, note: string, by: string) => post<{ queued: boolean }>(`/api/calls/${id}/coach`, { note, by }),
  takeOver: (id: string, note: string, by: string) => post<{ escalation_id: string }>(`/api/calls/${id}/takeover`, { note, by }),
  humanQa: (id: string, labels: Record<string, QAResult>, by: string) => post<Review>(`/api/calls/${id}/qa`, { labels, by }),
  live: () => call<Live>("/api/live"),
  desk: () => call<DeskItem[]>("/api/desk"),
  updateDesk: (id: string, body: Partial<Pick<DeskItem, "status" | "assignee" | "resolution">>) =>
    post<DeskItem>(`/api/desk/${id}`, body),
  assist: (id: string) => post<Assist>(`/api/desk/${id}/assist`),
  ask: (question: string) => post<Answer>("/api/assist/ask", { question }),
  borrowers: (q: string) => call<Borrower[]>("/api/borrowers?" + new URLSearchParams(q ? { q } : {})),
  chatStart: (borrower_id: string) =>
    post<{ call_id: string; greeting: string; borrower: string; language: string }>("/api/chat/start", { borrower_id }),
  chatSay: (id: string, text: string) => post<ChatTurn>(`/api/chat/${id}/say`, { text }),
  chatEnd: (id: string) => post<{ outcome: string; note: string }>(`/api/chat/${id}/end`),
  quality: () => call<Quality>("/api/quality"),
};
