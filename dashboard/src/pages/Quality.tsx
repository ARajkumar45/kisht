import { api } from "../api";
import { Badge, Card, CallLink, Loading, Page, Tile, human, useLoad } from "../ui";

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
