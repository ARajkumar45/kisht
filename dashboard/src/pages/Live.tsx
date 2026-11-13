import { useState } from "react";
import { api, type Call } from "../api";
import { Badge, Card, CallLink, LANG, Loading, Page, human, time, useLoad } from "../ui";

const ALERT: Record<string, string> = {
  banned_phrase: "Threat or banned phrase blocked",
  leak_before_identity: "Loan detail before identity blocked",
  guessed_identity: "Agent offered a date of birth or PIN: blocked",
  false_promise_claim: "False 'promise saved' blocked",
  unbacked_link_claim: "False 'link sent' blocked",
  false_claim: "False waiver / payment claim blocked",
  date_out_of_policy: "Promise date outside policy refused",
  amount_out_of_policy: "Amount below minimum refused",
  identity_mismatch: "Wrong date of birth / PIN",
  identity_locked: "Identity locked after 3 tries",
};

/** Supervisor controls for one live conversation. Both go through the guard and the audit log. */
function Controls({ call, onDone }: { call: Call; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const by = "Supervisor";
  const run = async (f: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await f();
      setMsg(ok);
      setNote("");
      onDone();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if ((call.outcome ?? "").startsWith("escalated")) return null;
  return (
    <div className="controls">
      <div className="form-row">
        <input placeholder="Private note to the AI, e.g. offer a part payment" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="secondary" disabled={busy || !note.trim()} onClick={() => run(() => api.coach(call.call_id, note, by), "Note queued for the AI's next reply.")}>Coach</button>
        <button className="danger" disabled={busy} onClick={() => { if (window.confirm("Stop the AI and hand this conversation to the human desk?")) run(() => api.takeOver(call.call_id, note, by), "Taken over. The case is on the human desk."); }}>Take over</button>
      </div>
      {msg && <div className="muted small">{msg}</div>}
    </div>
  );
}

export default function Live() {
  const { data, error, refresh } = useLoad(api.live, [], 2500);
  if (!data) return <Page title="Live"><Loading error={error} /></Page>;
  return (
    <Page title="Live" stale={error} sub="Supervisor view: conversations happening now and every alert. Coach the AI with a private note, or take a conversation over.">
      <div className="grid-2">
        <Card title={`Live conversations (${data.live.length})`}>
          {!data.live.length && <div className="muted">No conversation is live. Start one from Test chat, or run <code>uv run kisht simulate</code>.</div>}
          {data.live.map((c) => (
            <div className="live-call" key={c.call_id}>
              <div className="live-head">
                <span className="pulse" /> <b>{c.borrower_name}</b>
                <span className="muted small">{LANG[c.language ?? ""]} · {human(c.channel)} · {c.turns} turns</span>
                <CallLink id={c.call_id}>open</CallLink>
                {c.blocks > 0 && <Badge tone="bad">{c.blocks} blocked</Badge>}
              </div>
              {c.last_turns.map((t) => (
                <div key={t.idx} className="live-turn">
                  {t.borrower && <div><span className="who">Borrower</span> {t.borrower}</div>}
                  {t.coach && <div className="coach-line">Supervisor note: {t.coach}</div>}
                  <div><span className="who">Agent</span> {t.agent}</div>
                </div>
              ))}
              <Controls call={c} onDone={refresh} />
            </div>
          ))}
        </Card>
        <Card title="Alerts">
          {!data.alerts.length && <div className="muted">No alerts.</div>}
          <ul className="alerts">
            {data.alerts.map((a, i) => {
              const esc = a.kind.startsWith("escalated:");
              return (
                <li key={i} className={esc ? "warn" : "bad"}>
                  <div className="alert-head">
                    <b>{esc ? `Handed to a human: ${human(a.kind.split(":")[1])}` : ALERT[a.kind] ?? human(a.kind)}</b>
                    <span className="muted small">{time(a.at)}</span>
                  </div>
                  <div className="small">{a.borrower_name} · <CallLink id={a.call_id} /></div>
                  {a.said && <div className="muted small clamp">{a.said}</div>}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </Page>
  );
}
