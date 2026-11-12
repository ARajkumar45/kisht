import { api } from "../api";
import { Bars, Card, LANG, Loading, Page, Tile, pct, rupees, useLoad } from "../ui";

const REASONS: Record<string, string> = {
  salary_delay: "Salary late", job_loss: "Job loss", medical: "Medical", family_emergency: "Family emergency",
  business_loss: "Business loss", forgot: "Forgot", dispute: "Dispute", already_paid: "Says already paid",
  wants_waiver: "Wants waiver", wrong_person: "Wrong person", refused_to_engage: "Refused to engage",
  no_issue: "No issue", not_stated: "Not stated", other: "Other", unknown: "Not reviewed",
};

export default function Overview() {
  const { data: o, error } = useLoad(api.overview, [], 10000);
  if (!o) return <Page title="Overview"><Loading error={error} /></Page>;
  const r = o.rates;
  return (
    <Page title="Overview" sub="Every conversation the AI agent had, scored after the call. Refreshes every 10 seconds.">
      <div className="tiles">
        <Tile label="Conversations" value={o.calls} hint={o.live ? `${o.live} live now` : "none live"} />
        <Tile label="Right person reached" value={pct(r.right_party_contact)} hint="identity verified" />
        <Tile label="Promise to pay" value={pct(r.promise)} hint={`${o.money.promises} promises · ${rupees(o.money.promised_amount)}`} tone="good" />
        <Tile label="Payment link sent" value={pct(r.link_sent)} hint={`${o.money.links} links · ${rupees(o.money.link_amount)}`} tone="good" />
        <Tile label="Handled without a human" value={pct(r.containment)} hint={`containment · ${pct(r.escalated)} handed over`} tone="warn" />
        <Tile label="QA score" value={o.qa.average == null ? "–" : `${o.qa.average}`} hint={`average of ${o.qa.reviewed} reviewed calls`} />
      </div>
      <div className="grid-3">
        <Card title="Why borrowers are not paying">
          <Bars data={o.reasons} labels={REASONS} />
        </Card>
        <Card title="Borrower mood at the end">
          <Bars data={o.sentiment} />
        </Card>
        <Card title="Outcomes">
          <Bars data={o.outcomes} />
        </Card>
      </div>
      <div className="grid-3">
        <Card title="Blocked by code before the borrower heard it">
          <Bars data={o.blocked} empty="Nothing blocked" />
          <p className="note">The model tried these; the guard stopped them. Each one is in the call's trace.</p>
        </Card>
        <Card title="Languages">
          <Bars data={o.languages} labels={LANG} />
        </Card>
        <Card title="Speed (local model on this Mac)">
          <div className="kv">
            <span>Median conversation length</span><b>{o.handle_time_s == null ? "–" : o.handle_time_s >= 60 ? `${Math.floor(o.handle_time_s / 60)}m ${o.handle_time_s % 60}s` : `${o.handle_time_s}s`}</b>
            <span>Median reply time</span><b>{o.speed.median_turn_s ?? "–"} s</b>
            <span>Model calls per reply</span><b>{o.speed.model_calls_per_turn ?? "–"}</b>
            <span>Prompt tokens served from cache</span><b>{pct(o.speed.cache_hit_pct)}</b>
          </div>
        </Card>
      </div>
      <Card title="By language" right={<span className="muted small">where the agent is weaker shows up here first</span>}>
        <table>
          <thead><tr><th>Language</th><th>Conversations</th><th>Promise or link</th><th>Handed to a human</th><th>QA score</th><th>Blocked by code</th></tr></thead>
          <tbody>
            {o.by_language.map((l) => (
              <tr key={l.language}>
                <td><b>{LANG[l.language] ?? l.language}</b></td><td>{l.calls}</td><td>{pct(l.resolved_pct)}</td>
                <td>{pct(l.escalated_pct)}</td><td>{l.qa ?? "–"}</td><td>{l.blocked}</td>
              </tr>
            ))}
            {!o.by_language.length && <tr><td colSpan={6} className="muted">No finished conversations yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </Page>
  );
}
