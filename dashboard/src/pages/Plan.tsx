import { api } from "../api";
import { Badge, CallLink, Card, LANG, Loading, OutcomeBadge, Page, human, rupees, useLoad } from "../ui";

const TONE: Record<string, string> = { high: "bad", medium: "warn", low: "neutral" };

export default function Plan() {
  const { data, error } = useLoad(api.plan, [], 15000);
  if (!data) return <Page title="Today's plan"><Loading error={error} /></Page>;
  return (
    <Page
      title="Today's plan"
      sub={data.date ? `The planner agent read every due account on ${data.date} and decided who to contact, how, and why. Code then checked each against calling hours, attempt limits and opt-outs.` : "No plan yet. Run: uv run kisht simulate"}
    >
      <Card title={`${data.items.length} accounts`} right={<div className="chips">{Object.entries(data.counts).map(([k, v]) => <Badge key={k} tone={TONE[k]}>{human(k)} {v}</Badge>)}</div>}>
        <table>
          <thead>
            <tr><th>Priority</th><th>Borrower</th><th>Language</th><th>Overdue</th><th>Channel</th><th>Why (the planner's words)</th><th>Approach</th><th>Result</th></tr>
          </thead>
          <tbody>
            {data.items.map((i) => (
              <tr key={i.loan_id} className={i.status.startsWith("blocked") ? "dim" : ""}>
                <td><Badge tone={TONE[i.priority]}>{human(i.priority)}</Badge></td>
                <td><b>{i.name}</b><div className="muted small">{i.city} · {i.loan_id}</div></td>
                <td>{LANG[i.language] ?? i.language}</td>
                <td>{i.days_past_due ? <>{rupees(i.overdue_amount)}<div className="muted small">{i.days_past_due} days late</div></> : <span className="muted">due soon</span>}</td>
                <td>{human(i.channel)}</td>
                <td className="wrap">{i.reason}</td>
                <td className="wrap muted">{i.approach}</td>
                <td>{i.call_id ? <CallLink id={i.call_id}><OutcomeBadge outcome={i.outcome} /></CallLink> : i.status.startsWith("blocked") ? <Badge tone="bad">{human(i.status.split(":")[1] ?? "blocked")}</Badge> : <span className="muted">queued</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </Page>
  );
}
