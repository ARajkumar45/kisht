import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Span, type Turn } from "../api";
import { Badge, Card, LANG, Loading, OutcomeBadge, Page, duration, human, rupees, useLoad } from "../ui";

export default function CallDetail() {
  const { id = "" } = useParams();
  const { data, error } = useLoad(() => api.call(id), [id], 4000);
  if (!data) return <Page title="Call"><Loading error={error} /></Page>;
  const { call, turns, spans, review, actions } = data;
  return (
    <Page
      title={call.borrower_name ?? "Call"}
      sub={`${LANG[call.language ?? ""] ?? call.language} · ${human(call.channel)} · ${duration(call.started_utc, call.ended_utc)} · ${call.call_id}`}
      actions={<div className="chips"><Link to="/calls">← All calls</Link><OutcomeBadge outcome={call.status === "live" ? null : call.outcome} /></div>}
    >
      <div className="grid-2">
        <Card title="Conversation">
          <Transcript turns={turns} />
        </Card>
        <div className="stack">
          <Card title="Post-call review" right={review?.qa_score != null && <span className="score">QA {review.qa_score}</span>}>
            {!review ? <div className="muted">{call.status === "live" ? "Reviewed when the call ends." : "Review pending…"}</div> : (
              <>
                <p>{review.summary}</p>
                <div className="chips">
                  <Badge>Reason: {human(review.reason)}</Badge>
                  <Badge tone={review.sentiment === "distressed" || review.sentiment === "negative" ? "warn" : "neutral"}>Mood: {human(review.sentiment)}</Badge>
                </div>
                <ul className="qa">
                  {review.qa.map((q) => (
                    <li key={q.id} className={q.result}>
                      <span className="qa-mark">{q.result === "pass" ? "✓" : q.result === "fail" ? "✗" : "–"}</span>
                      <div><b>{q.check}</b>{q.evidence && <div className="muted small">{q.by === "code" ? "Code: " : ""}{q.evidence}</div>}</div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>
          {review && (
            <Card title="Compliance (counted by code)">
              <ul className="compliance">
                {review.compliance.map((c) => (
                  <li key={c.rule}><span>{c.label}</span>{c.blocked ? <Badge tone="bad">{c.blocked} blocked</Badge> : <Badge tone="good">clean</Badge>}</li>
                ))}
              </ul>
              <p className="note">"Blocked" means the model attempted it and code replaced or refused it before the borrower heard anything.</p>
            </Card>
          )}
          <Card title="What changed in the loan book">
            <Actions actions={actions} note={call.note} />
          </Card>
        </div>
      </div>
      <Card title="Trace" right={<span className="muted small">OpenTelemetry spans · {spans.length} steps · idle gaps shortened · click one</span>}>
        <Trace spans={spans} />
      </Card>
    </Page>
  );
}

function Transcript({ turns }: { turns: Turn[] }) {
  return (
    <div className="transcript">
      {turns.map((t) => (
        <div key={t.idx}>
          {t.borrower && <div className="msg borrower">{t.borrower}</div>}
          <div className="msg agent">
            {t.agent}
            {(t.tools.length > 0 || t.refused.length > 0 || t.replaced.length > 0) && (
              <div className="msg-meta">
                {t.tools.map((x, i) => <span key={i} className="chip tool">{x}</span>)}
                {t.refused.map((x, i) => <span key={"r" + i} className="chip bad">refused: {x}</span>)}
                {t.replaced.map((x, i) => <span key={"p" + i} className="chip bad">reply replaced: {x}</span>)}
                {t.seconds != null && <span className="chip">{t.seconds}s · {t.model_calls} model call{t.model_calls === 1 ? "" : "s"}</span>}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function Actions({ actions, note }: { actions: Record<string, Record<string, unknown>[]>; note: string | null }) {
  const rows: string[] = [];
  for (const p of actions.promises) rows.push(`Promise: ${rupees(p.amount as number)} on ${p.promised_date}`);
  for (const l of actions.links) rows.push(`Payment link: ${rupees(l.amount as number)}`);
  for (const e of actions.escalations) rows.push(`Handed to a human: ${human(String(e.reason))}`);
  for (const f of actions.followups) rows.push(`Follow-up on ${f.on_date}`);
  return (
    <>
      {rows.length ? <ul className="plain">{rows.map((r) => <li key={r}>{r}</li>)}</ul> : <div className="muted">Nothing written to the ledger.</div>}
      {note && <p className="note">Case note for next time: {note}</p>}
    </>
  );
}

const SPAN_LABEL: Record<string, string> = {
  turn: "Borrower turn", chat: "Model call", execute_tool: "Tool", reply_check: "Reply check",
  save_promise: "Save promise (code)", case_note: "Case note", review: "Post-call review",
};

function Trace({ spans }: { spans: Span[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!spans.length) return <div className="muted">No trace recorded.</div>;
  // Idle time between steps (the borrower typing, a review run hours later) would squash every
  // step to a sliver, so any gap longer than GAP_NS is drawn as GAP_NS.
  const GAP_NS = 1.5e9;
  const shift = new Map<string, number>();
  let cut = 0;
  let end = -Infinity;
  for (const s of [...spans].sort((a, b) => a.start_ns - b.start_ns)) {
    const start = s.start_ns - cut;
    if (end !== -Infinity && start - end > GAP_NS) cut += start - end - GAP_NS;
    shift.set(s.span_id, cut);
    end = Math.max(end, s.end_ns - cut);
  }
  const at = (s: Span) => s.start_ns - (shift.get(s.span_id) ?? 0);
  const t0 = Math.min(...spans.map(at));
  const total = Math.max(end - t0, 1);
  const byId = new Map(spans.map((s) => [s.span_id, s]));
  const depth = (s: Span): number => (s.parent_id && byId.has(s.parent_id) ? 1 + depth(byId.get(s.parent_id)!) : 0);
  return (
    <div className="trace">
      {spans.map((s) => {
        const d = depth(s);
        const ms = (s.end_ns - s.start_ns) / 1e6;
        const label = s.name === "execute_tool" ? `Tool · ${s.attrs["gen_ai.tool.name"]}` : SPAN_LABEL[s.name] ?? s.name;
        const bad = s.status === "ERROR" || (s.name === "reply_check" && Array.isArray(s.attrs["kisht.replaced"]) && (s.attrs["kisht.replaced"] as unknown[]).length > 0);
        return (
          <div key={s.span_id}>
            <div className={`span-row ${s.name} ${bad ? "bad" : ""}`} onClick={() => setOpen(open === s.span_id ? null : s.span_id)}>
              <div className="span-name" style={{ paddingLeft: d * 16 }}>{label}</div>
              <div className="span-track">
                <div className="span-bar" style={{ left: `${(100 * (at(s) - t0)) / total}%`, width: `max(2px, ${(100 * (s.end_ns - s.start_ns)) / total}%)` }} />
              </div>
              <div className="span-ms">{ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms.toFixed(0)} ms`}</div>
            </div>
            {open === s.span_id && (
              <pre className="span-attrs">{JSON.stringify(s.attrs, null, 2)}</pre>
            )}
          </div>
        );
      })}
    </div>
  );
}
