import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Card, LANG, Loading, OutcomeBadge, Page, duration, human, press, time, useDebounced, useLoad } from "../ui";

export default function Calls() {
  const [typed, setQ] = useState("");
  const q = useDebounced(typed); // one request when typing stops, not one per key
  const [outcome, setOutcome] = useState("");
  const [language, setLanguage] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const params: Record<string, string> = {};
  if (q) params.q = q;
  if (outcome) params.outcome = outcome;
  if (language) params.language = language;
  if (flagged) params.flagged = "true";
  const { data, error } = useLoad(() => api.calls(params), [q, outcome, language, flagged], 10000);
  const nav = useNavigate();
  return (
    <Page title="Call log" sub="Every conversation, with its transcript, step-by-step trace and QA review. Click a row.">
      <div className="filters">
        <input aria-label="Search calls" placeholder="Search name, words said, call id…" value={typed} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Filter by outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">All outcomes</option>
          {["promise", "link_sent", "escalated", "opted_out", "not_verified", "talked"].map((o) => <option key={o} value={o}>{human(o)}</option>)}
        </select>
        <select aria-label="Filter by language" value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="">All languages</option>
          {Object.entries(LANG).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} /> Only calls where code blocked something</label>
        <button className="secondary" onClick={() => { setExportError(null); api.callsCsv(params).catch((e: Error) => setExportError(e.message)); }}>Export CSV</button>
      </div>
      {exportError && <div className="banner" role="alert">The call log was not exported: {exportError}</div>}
      <Card>
        {!data ? <Loading error={error} /> : (
          <table className="clickable">
            <thead>
              <tr><th scope="col">When</th><th scope="col">Borrower</th><th scope="col">Language</th><th scope="col">Channel</th><th scope="col">Turns</th><th scope="col">Length</th><th scope="col">Outcome</th><th scope="col">Reason</th><th scope="col">Mood</th><th scope="col">QA</th><th scope="col">Blocked</th></tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.call_id} {...press(() => nav(`/calls/${c.call_id}`))}>
                  <td>{time(c.started_utc)}</td>
                  <td><b>{c.borrower_name}</b><div className="muted small">{c.source?.replace("simulated:", "sim · ")}</div></td>
                  <td>{LANG[c.language ?? ""] ?? c.language}</td>
                  <td>{human(c.channel)}</td>
                  <td>{c.turns}</td>
                  <td>{duration(c.started_utc, c.ended_utc)}</td>
                  <td><OutcomeBadge outcome={c.status === "live" ? null : c.outcome} /></td>
                  <td>{c.reason ? human(c.reason) : <span className="muted">–</span>}</td>
                  <td>{c.sentiment ? human(c.sentiment) : <span className="muted">–</span>}</td>
                  <td>{c.qa_score ?? <span className="muted">–</span>}</td>
                  <td>{c.blocks ? <Badge tone="bad">{c.blocks}</Badge> : <span className="muted">0</span>}</td>
                </tr>
              ))}
              {!data.length && <tr><td colSpan={11} className="muted">No calls match.</td></tr>}
            </tbody>
          </table>
        )}
      </Card>
    </Page>
  );
}
