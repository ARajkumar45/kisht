import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type QAResult, type Review, type Span, type Turn } from "../api";
import { Badge, Card, LANG, Loading, OutcomeBadge, Page, duration, human, rupees, useLoad } from "../ui";

export default function CallDetail() {
  const { id = "" } = useParams();
  // A finished, reviewed call no longer changes: stop asking for it every 4 seconds (each
  // request re-reads the audit files).
  const [settled, setSettled] = useState(false);
  const { data, error, refresh } = useLoad(() => api.call(id), [id], settled ? undefined : 4000);
  const done = data?.call.status === "ended" && !!data.review;
  useEffect(() => setSettled(done), [done]);
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
          <Card title="Post-call review" right={review?.final_score != null && <span className="score">QA {review.final_score}{review.human_reviewed && review.final_score !== review.qa_score ? <span className="muted small"> (AI said {review.qa_score})</span> : null}</span>}>
            {!review ? <div className="muted">{call.status === "live" ? "Reviewed when the call ends." : "Review pending…"}</div> : (
              <>
                <p>{review.summary}</p>
                <div className="chips">
                  <Badge>Reason: {human(review.reason)}</Badge>
                  <Badge tone={review.sentiment === "distressed" || review.sentiment === "negative" ? "warn" : "neutral"}>Mood: {human(review.sentiment)}</Badge>
                </div>
                <ul className="qa">
                  {review.qa.map((q) => {
                    const shown = q.human?.result ?? q.result;
                    return (
                      <li key={q.id} className={shown}>
                        <span className="qa-mark">{shown === "pass" ? "✓" : shown === "fail" ? "✗" : "–"}</span>
                        <div>
                          <b>{q.check}</b>
                          {q.evidence && <div className="muted small">{q.by === "code" ? "Code: " : ""}{q.evidence}</div>}
                          {q.human && q.human.result !== q.result && <div className="small warn-text">{q.human.by} changed this from {q.result} to {q.human.result}</div>}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <HumanReview key={call.call_id} callId={call.call_id} review={review} onSaved={refresh} />
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
      <Card title="Audit trail" right={<span className="muted small">every action and every refusal, as code recorded it</span>}>
        {!data.audit.length ? <div className="muted">No audit entries on disk for this call.</div> : (
          <details>
            <summary>{data.audit.length} entries · {data.audit.filter((a) => a.outcome !== "ok").length} denied or failed</summary>
            <table>
              <tbody>
                {data.audit.map((a, i) => (
                  <tr key={i}>
                    <td className="muted small">{new Date(a.time).toLocaleTimeString("en-IN")}</td>
                    <td><code>{a.action}</code></td>
                    <td><Badge tone={a.outcome === "ok" ? "good" : "bad"}>{a.outcome}</Badge></td>
                    <td className="wrap muted small">{a.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
      </Card>
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
          {t.coach && <div className="coach-line">Supervisor note to the AI: {t.coach}</div>}
          <div className="msg agent">
            {t.agent}
            {(t.tools.length > 0 || t.refused.length > 0 || t.replaced.length > 0) && (
              <div className="msg-meta">
                {t.tools.map((x, i) => <span key={i} className="chip tool">{x}</span>)}
                {t.refused.map((x, i) => <span key={"r" + i} className="chip bad">refused: {x}</span>)}
                {t.replaced.map((x, i) => <span key={"p" + i} className="chip bad">reply replaced: {x}</span>)}
                {t.seconds != null && <span className="chip">{t.first_s != null ? `first words ${t.first_s}s · whole reply ` : ""}{t.seconds}s · {t.model_calls} model call{t.model_calls === 1 ? "" : "s"}</span>}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** A human marks the same scorecard. Saved next to the AI's marks, never over them, so the
 * Quality page can show how often the AI reviewer and a human agree. */
function HumanReview({ callId, review, onSaved }: { callId: string; review: Review; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [by, setBy] = useState(review.qa.find((q) => q.human)?.human?.by ?? "");
  const [marks, setMarks] = useState<Record<string, QAResult>>(() => Object.fromEntries(review.qa.map((q) => [q.id, q.human?.result ?? q.result])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!open) {
    return (
      <div className="form-row">
        <button className="secondary" onClick={() => setOpen(true)}>{review.human_reviewed ? "Edit the human review" : "Check this review"}</button>
        {review.human_reviewed && <span className="muted small">Checked by {by || "a reviewer"}</span>}
      </div>
    );
  }
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.humanQa(callId, marks, by.trim() || "reviewer");
      setOpen(false);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="human-qa">
      <b>Your marks</b> <span className="muted small">start from the AI's; change the ones you disagree with</span>
      {review.qa.filter((q) => q.by !== "code").map((q) => (
        <div className="human-row" key={q.id}>
          <span>{q.check}</span>
          <span className="seg">
            {(["pass", "fail", "na"] as QAResult[]).map((r) => (
              <button key={r} type="button" className={marks[q.id] === r ? `on ${r}` : ""} onClick={() => setMarks({ ...marks, [q.id]: r })}>{r === "na" ? "n/a" : r}</button>
            ))}
          </span>
        </div>
      ))}
      <div className="form-row">
        <input placeholder="Your name" value={by} onChange={(e) => setBy(e.target.value)} />
        <button disabled={busy} onClick={save}>{busy ? "Saving…" : "Save review"}</button>
        <button className="secondary" disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {err && <div className="error">{err}</div>}
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
