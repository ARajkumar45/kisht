import { api, type ClaimRow } from "../api";
import { Badge, Card, CallLink, LANG, Loading, Page, Tile, human, useLoad } from "../ui";

const QA_LABEL: Record<string, string> = {
  introduced: "Introduced self and lender", verified_first: "Verified identity first", explained_dues: "Explained dues clearly",
  asked_reason: "Asked the reason first", fitting_option: "Offered a fitting option", clear_commitment: "Read back the commitment",
  respectful: "Respectful, no pressure", right_handoff: "Handed over when needed", clear_close: "Clear next step",
};

export default function Quality() {
  const { data, error } = useLoad(api.quality, []);
  if (!data) return <Page title="Quality"><Loading error={error} /></Page>;
  const cal = data.calibration;
  return (
    <Page title="Quality" sub="Three views of quality: the QA scorecard on real conversations, how far the AI reviewer agrees with a human, and the offline eval suite (simulated borrowers graded by code).">
      <Card title="QA scorecard pass rate (all reviewed calls)">
        <div className="bars">
          {data.qa_items.map((q) => (
            <div className="bar-row" key={q.id}>
              <div className="bar-label">{QA_LABEL[q.id] ?? human(q.id)}</div>
              <div className="bar-track"><div className={`bar-fill ${q.pass_rate != null && q.pass_rate < 70 ? "low" : ""}`} style={{ width: `${q.pass_rate ?? 0}%` }} /></div>
              <div className="bar-value">{q.pass_rate == null ? "n/a" : `${q.pass_rate}%`}<span className="muted small"> ({q.pass}/{q.pass + q.fail})</span></div>
              {q.failing_calls.length > 0 && (
                <div className="bar-foot muted small">Failed in: {q.failing_calls.map((id) => <CallLink key={id} id={id} />)}</div>
              )}
            </div>
          ))}
          {!data.qa_items.length && <div className="muted">No reviewed calls yet.</div>}
        </div>
      </Card>
      <Card title="Can we trust the AI reviewer?" right={<span className="muted small">a human marks the same calls; this is how often they agree</span>}>
        {!cal.items ? (
          <div className="muted">No call has a human review yet. Open any call from the call log and use "Check this review" to mark it yourself.</div>
        ) : (
          <>
            <div className="tiles three">
              <Tile label="AI agrees with the human" value={`${cal.agreement_pct}%`} hint={`${cal.items} scorecard items`} tone={cal.agreement_pct != null && cal.agreement_pct >= 85 ? "good" : "warn"} />
              <Tile label="Calls checked by a human" value={cal.calls} />
              <Tile label="Disagreements" value={cal.disagreements.length} tone={cal.disagreements.length ? "warn" : "good"} />
            </div>
            {cal.disagreements.length > 0 && (
              <table>
                <thead><tr><th>Call</th><th>Scorecard item</th><th>AI said</th><th>Human said</th><th>Reviewer</th></tr></thead>
                <tbody>
                  {cal.disagreements.map((d, i) => (
                    <tr key={i}>
                      <td><CallLink id={d.call_id} /></td><td>{QA_LABEL[d.item] ?? human(d.item)}</td>
                      <td><Badge>{d.ai}</Badge></td><td><Badge tone="warn">{d.human}</Badge></td><td>{d.by}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Card>
      <ClaimsCard title="Does the agent do what it says? (eval runs)" rows={data.claims.evals} kinds={data.claims.kinds}
        note={`From ${data.claims.eval_runs.join(" and ")}. A claim is the model saying it did something (saved a promise, sent a link, waived a charge, "let me check") with no tool call behind it.`} />
      <ClaimsCard title="Does the agent do what it says? (call log)" rows={data.claims.calls} kinds={data.claims.kinds}
        note="Every conversation in the call log, counted the same way. Old calls can show claims that reached the borrower: the checks were narrower then." />
      <Card title="Eval runs">
        <table>
          <thead><tr><th>Run</th><th>Personas</th><th>Runs</th><th>pass^1</th><th>pass^k</th><th>Median turn</th><th>By category (pass^1)</th></tr></thead>
          <tbody>
            {data.evals.map((e) => (
              <tr key={e.run}>
                <td><b>{e.run}</b></td>
                <td>{e.personas}</td>
                <td>{e.runs}</td>
                <td>{Math.round(e.pass_1 * 100)}%</td>
                <td>{Math.round(e.pass_k * 100)}% <span className="muted small">k={e.k}</span></td>
                <td>{e.median_turn_s}s</td>
                <td className="wrap">
                  <div className="mini-bars">
                    {Object.entries(e.by_category ?? {}).map(([k, v]) => (
                      <div key={k} title={`${k}: ${Math.round(v.pass_1 * 100)}%`} className="mini">
                        <div className="mini-fill" style={{ height: `${v.pass_1 * 100}%` }} />
                        <span>{k.replace("_", " ")}</span>
                      </div>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </Page>
  );
}

function ClaimsCard({ title, rows, kinds, note }: { title: string; rows: Record<string, ClaimRow>; kinds: Record<string, string>; note: string }) {
  const all = rows.all;
  if (!all) return null;
  const langs = Object.keys(rows).filter((k) => k !== "all").sort();
  const p = all.pass;
  return (
    <Card title={title} right={<span className="muted small">{all.per_100_turns ?? "–"} per 100 agent turns</span>}>
      <table>
        <thead><tr><th>Language</th><th>Conversations</th><th>Agent turns</th><th>Claims with nothing behind them</th><th>Fixed by asking again</th><th>Replaced by code</th><th>Reached the borrower</th></tr></thead>
        <tbody>
          {[...langs, "all"].map((k) => (
            <tr key={k}>
              <td><b>{k === "all" ? "All" : LANG[k] ?? k}</b></td><td>{rows[k].conversations}</td><td>{rows[k].turns}</td>
              <td>{rows[k].attempts} <span className="muted small">({rows[k].per_100_turns ?? "–"} per 100)</span></td>
              <td>{rows[k].fixed_by_asking_again}</td><td>{rows[k].replaced}</td>
              <td>{rows[k].reached_borrower ? <Badge tone="bad">{rows[k].reached_borrower}</Badge> : <Badge tone="good">0</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="chips" style={{ marginTop: 10 }}>
        {Object.entries(all.by_kind).map(([k, n]) => <Badge key={k}>{kinds[k] ?? k}: {n}</Badge>)}
      </div>
      {p && (
        <p className="note">
          Pass rate {p.pass_pct}% ({p.passed} of {p.runs}): <b>{p.passed_clean}</b> passed with no such attempt ({p.clean_pct}%), <b>{p.passed_because_code_caught_it}</b> passed because code caught one, <b>{p.passed_with_false_claim_heard}</b> passed although a false claim reached the borrower. Counting those as failures: <b>{p.strict_pct}%</b>.
        </p>
      )}
      {all.examples.length > 0 && (
        <ul className="plain small" style={{ marginTop: 8 }}>
          {all.examples.slice(0, 4).map((e, i) => <li key={i} className="muted">Reached the borrower ({kinds[e.kind] ?? e.kind}): "{e.said.slice(0, 140)}…"</li>)}
        </ul>
      )}
      <p className="note">{note}</p>
    </Card>
  );
}
