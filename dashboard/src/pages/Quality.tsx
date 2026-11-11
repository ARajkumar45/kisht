import { api } from "../api";
import { Card, Loading, Page, human, useLoad } from "../ui";

const QA_LABEL: Record<string, string> = {
  introduced: "Introduced self and lender", verified_first: "Verified identity first", explained_dues: "Explained dues clearly",
  asked_reason: "Asked the reason first", fitting_option: "Offered a fitting option", clear_commitment: "Read back the commitment",
  respectful: "Respectful, no pressure", right_handoff: "Handed over when needed", clear_close: "Clear next step",
};

export default function Quality() {
  const { data, error } = useLoad(api.quality, []);
  if (!data) return <Page title="Quality"><Loading error={error} /></Page>;
  return (
    <Page title="Quality" sub="Two views of quality: the QA scorecard on real conversations, and the offline eval suite (simulated borrowers graded by code).">
      <Card title="QA scorecard pass rate (all reviewed calls)">
        <div className="bars">
          {data.qa_items.map((q) => (
            <div className="bar-row" key={q.id}>
              <div className="bar-label">{QA_LABEL[q.id] ?? human(q.id)}</div>
              <div className="bar-track"><div className={`bar-fill ${q.pass_rate != null && q.pass_rate < 70 ? "low" : ""}`} style={{ width: `${q.pass_rate ?? 0}%` }} /></div>
              <div className="bar-value">{q.pass_rate == null ? "n/a" : `${q.pass_rate}%`}<span className="muted small"> ({q.pass}/{q.pass + q.fail})</span></div>
            </div>
          ))}
          {!data.qa_items.length && <div className="muted">No reviewed calls yet.</div>}
        </div>
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
