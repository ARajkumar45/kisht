import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Borrower } from "../api";
import { Card, LANG, Page, human, rupees, useLoad } from "../ui";

type Msg = { from: "agent" | "me"; text: string; meta?: string[]; bad?: string[] };

export default function Chat() {
  const [q, setQ] = useState("");
  const { data: people } = useLoad(() => api.borrowers(q), [q]);
  const [who, setWho] = useState<Borrower | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [msgs, busy]);

  const start = async (b: Borrower) => {
    setWho(b); setMsgs([]); setEnded(null); setErr(null); setBusy(true);
    try {
      const r = await api.chatStart(b.id);
      setCallId(r.call_id);
      setMsgs([{ from: "agent", text: r.greeting }]);
    } catch (e) {
      setErr((e as Error).message); setCallId(null);
    } finally { setBusy(false); }
  };
  const send = async () => {
    if (!callId || !text.trim()) return;
    const said = text.trim();
    setText(""); setMsgs((m) => [...m, { from: "me", text: said }]); setBusy(true);
    try {
      const r = await api.chatSay(callId, said);
      setMsgs((m) => [...m, { from: "agent", text: r.reply, meta: [...r.tools, `${r.seconds}s`], bad: [...r.refused, ...r.replaced] }]);
      if (r.ended) await finish();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const finish = async () => {
    if (!callId) return;
    const r = await api.chatEnd(callId);
    setEnded(r.outcome);
  };

  return (
    <Page title="Test chat" sub="Be the borrower. The real agent, guard and ledger answer; the conversation appears in the call log with its trace and review.">
      <div className="grid-chat">
        <Card title="Pick a synthetic borrower">
          <input placeholder="Search name or city…" value={q} onChange={(e) => setQ(e.target.value)} />
          <ul className="people">
            {(people ?? []).map((b) => (
              <li key={b.id} className={who?.id === b.id ? "sel" : ""} onClick={() => start(b)}>
                <b>{b.name}</b> <span className="muted small">{b.city} · {LANG[b.language]} · {human(b.product)} · EMI {rupees(b.emi)}</span>
              </li>
            ))}
          </ul>
        </Card>
        <div className="phone">
          <div className="phone-head">
            <div className="avatar">A</div>
            <div><b>Asha · Demo Finance</b><div className="small">{who ? `chatting as ${who.name}` : "pick a borrower"}</div></div>
          </div>
          <div className="phone-body">
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.from}`}>
                {m.text}
                {(m.meta?.length || m.bad?.length) ? (
                  <div className="bubble-meta">
                    {m.meta?.map((x, j) => <span key={j}>{x}</span>)}
                    {m.bad?.map((x, j) => <span key={"b" + j} className="bad">blocked: {x}</span>)}
                  </div>
                ) : null}
              </div>
            ))}
            {busy && <div className="bubble agent typing">typing…</div>}
            {err && <div className="error">{err}</div>}
            {ended && callId && (
              <div className="ended">Conversation ended: {human(ended.split(":")[0])}. <Link to={`/calls/${callId}`}>See the trace and review</Link></div>
            )}
            <div ref={end} />
          </div>
          <form className="phone-input" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <input disabled={!callId || !!ended || busy} placeholder={callId ? "Type as the borrower… (e.g. Haan, main hoon)" : ""} value={text} onChange={(e) => setText(e.target.value)} />
            <button disabled={!callId || !!ended || busy || !text.trim()}>Send</button>
            <button type="button" className="secondary" disabled={!callId || !!ended} onClick={finish}>End</button>
          </form>
        </div>
      </div>
    </Page>
  );
}
