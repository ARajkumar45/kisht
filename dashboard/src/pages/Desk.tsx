import { useState } from "react";
import { api, type Answer, type Assist, type DeskItem } from "../api";
import { Badge, Card, CallLink, LANG, Loading, Page, human, rupees, time, useLoad } from "../ui";

const STATUS_TONE: Record<string, string> = { open: "bad", in_progress: "warn", resolved: "good" };

const hours = (h: number) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`);

/** How the case stands against the team's deadline. The clock stops when it is resolved. */
function Sla({ d }: { d: DeskItem }) {
  if (d.status === "resolved") return <span className="muted small">resolved in {hours(d.age_hours)}{d.breached ? " (late)" : ""}</span>;
  if (d.breached) return <Badge tone="bad">overdue by {hours(d.age_hours - d.sla_hours)}</Badge>;
  return <span className="muted small">{hours(d.sla_hours - d.age_hours)} left of {hours(d.sla_hours)}</span>;
}

export default function Desk() {
  const { data, error, refresh } = useLoad(api.desk, [], 8000);
  const [sel, setSel] = useState<string | null>(null);
  const [team, setTeam] = useState("");
  if (!data) return <Page title="Human desk"><Loading error={error} /></Page>;
  const teams = [...new Set(data.map((d) => d.team))];
  const shown = data.filter((d) => !team || d.team === team);
  const late = data.filter((d) => d.breached && d.status !== "resolved").length;
  const current = data.find((d) => d.id === sel) ?? null;
  return (
    <Page title="Human desk" sub="Cases the AI handed over, routed to the right team. Open one for an AI brief, suggested replies and agreement answers.">
      <div className="filters">
        <select value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">All teams ({data.length})</option>
          {teams.map((t) => <option key={t} value={t}>{t} ({data.filter((d) => d.team === t).length})</option>)}
        </select>
        {late > 0 && <Badge tone="bad">{late} past deadline</Badge>}
      </div>
      <div className="grid-2">
        <Card title="Queue">
          {!shown.length && <div className="muted">No hand-offs yet.</div>}
          <ul className="queue">
            {shown.map((d) => (
              <li key={d.id} className={d.id === sel ? "sel" : ""} onClick={() => setSel(d.id)}>
                <div className="queue-head">
                  <b>{d.borrower_name}</b>
                  <Badge tone={STATUS_TONE[d.status]}>{human(d.status)}</Badge>
                </div>
                <div className="small">{human(d.reason)} · {d.team} · {LANG[d.language]} · <Sla d={d} /></div>
                <div className="muted small clamp">{d.summary}</div>
              </li>
            ))}
          </ul>
        </Card>
        {current ? <CaseView key={current.id} item={current} onChange={refresh} /> : <Card><div className="muted">Pick a case from the queue.</div></Card>}
      </div>
    </Page>
  );
}

function CaseView({ item, onChange }: { item: DeskItem; onChange: () => void }) {
  const [assist, setAssist] = useState<Assist | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [assignee, setAssignee] = useState(item.assignee ?? "");
  const [resolution, setResolution] = useState(item.resolution ?? "");
  const run = async (f: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await f();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      <Card title={item.borrower_name} right={<Badge tone={STATUS_TONE[item.status]}>{human(item.status)}</Badge>}>
        <div className="kv">
          <span>Reason</span><b>{human(item.reason)}</b>
          <span>Team</span><b>{item.team}</b>
          <span>EMI</span><b>{rupees(item.emi)}</b>
          <span>Language</span><b>{LANG[item.language]} · {item.city}</b>
          <span>Handed over</span><b>{time(item.created_utc)}</b>
          <span>Deadline</span><b><Sla d={item} /></b>
          {item.call_id && <><span>Conversation</span><b><CallLink id={item.call_id}>open transcript and trace</CallLink></b></>}
        </div>
        <p><b>AI's hand-off note:</b> {item.summary}</p>
        {item.review && <p className="muted">Review: {item.review.summary} (mood: {item.review.sentiment})</p>}
        <div className="form-row">
          <input placeholder="Assign to (name)" value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          <button disabled={busy} onClick={() => run(async () => { await api.updateDesk(item.id, { status: "in_progress", assignee }); onChange(); })}>Take case</button>
        </div>
        <div className="form-row">
          <input placeholder="Resolution (what was agreed)" value={resolution} onChange={(e) => setResolution(e.target.value)} />
          <button disabled={busy || !resolution} onClick={() => run(async () => { await api.updateDesk(item.id, { status: "resolved", resolution }); onChange(); })}>Resolve</button>
        </div>
        <p className="note">The resolution is saved with the borrower's case notes, so the AI knows what was agreed the next time it talks to them.</p>
        {err && <div className="error">{err}</div>}
      </Card>
      <Card title="Agent assist" right={<button disabled={busy} onClick={() => run(async () => setAssist(await api.assist(item.id)))}>{busy ? "Thinking…" : assist ? "Refresh" : "Brief me"}</button>}>
        {!assist ? <div className="muted">The AI reads the conversation, dues, policy and past notes, and prepares you for the call back.</div> : (
          <>
            {assist.brief && <p>{assist.brief}</p>}
            {assist.next_best_action && <p><b>Next best action:</b> {assist.next_best_action}</p>}
            {assist.suggested_replies && (
              <>
                <b>You could say:</b>
                <ul className="replies">{assist.suggested_replies.map((r, i) => <li key={i}>{r}</li>)}</ul>
              </>
            )}
            {assist.watch_out && <p className="warn-text"><b>Watch out:</b> {assist.watch_out}</p>}
            <p className="muted small">Model: {assist.model}</p>
          </>
        )}
      </Card>
      <AskAgreement />
    </div>
  );
}

function AskAgreement() {
  const [q, setQ] = useState("");
  const [a, setA] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Card title="Ask the loan agreement">
      <form className="form-row" onSubmit={async (e) => { e.preventDefault(); setBusy(true); try { setA(await api.ask(q)); } finally { setBusy(false); } }}>
        <input placeholder="e.g. What is the late fee? Can they foreclose early?" value={q} onChange={(e) => setQ(e.target.value)} />
        <button disabled={busy || !q}>{busy ? "…" : "Ask"}</button>
      </form>
      {a && (
        <>
          <p>{a.answer}</p>
          <details><summary className="muted small">Sections used ({a.sections.map((s) => s.id).join(", ")})</summary>
            {a.sections.map((s) => <p key={s.id} className="small"><b>{s.id}. {s.title}</b> {s.text}</p>)}
          </details>
        </>
      )}
    </Card>
  );
}
