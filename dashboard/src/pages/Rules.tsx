import { useState } from "react";
import { api, type Rule } from "../api";
import { Badge, Card, Loading, Page, Tile, useLoad } from "../ui";

const STATUS: Record<Rule["status"], [string, string]> = {
  enforced: ["Enforced", "good"],
  partly: ["Partly", "warn"],
  gap: ["Not built", "bad"],
  not_applicable: ["Not applicable", "neutral"],
};

function Row({ r }: { r: Rule }) {
  const [open, setOpen] = useState(false);
  const [label, tone] = STATUS[r.status];
  return (
    <>
      <tr onClick={() => setOpen(!open)} className={r.status === "not_applicable" ? "dim" : ""}>
        <td className="nowrap"><b>{r.para}</b><div className="muted small">{r.source}</div></td>
        <td className="wrap-wide">{r.requires}</td>
        <td><Badge tone={tone}>{label}</Badge></td>
        <td className="wrap-wide">
          {r.how}
          {r.gap && <div className="warn-text small">Missing: {r.gap}</div>}
        </td>
        <td className="num">{r.codes.length ? r.blocked : "–"}</td>
      </tr>
      {open && (r.guard.length > 0 || r.tests.length > 0) && (
        <tr className="detail">
          <td />
          <td colSpan={4}>
            <div className="kv small">
              <span>Code</span><div>{r.guard.map((g) => <code key={g}>{g.split(":")[1]}</code>)}</div>
              {r.config && <><span>Set in</span><div><code>{r.config}</code></div></>}
              {r.codes.length > 0 && <><span>Block codes</span><div>{r.codes.map((c) => <code key={c}>{c}</code>)}</div></>}
              <span>Tests</span><div>{r.tests.map((t) => <code key={t}>{t.split("::")[1]}</code>)}</div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Rules() {
  const { data, error } = useLoad(api.rules, [], 30000);
  if (!data) return <Page title="Rules"><Loading error={error} /></Page>;
  const main = data.sources[data.rules[0].source];
  const s = data.summary;
  const days = Math.ceil((new Date(main.effective).getTime() - Date.now()) / 86400000);
  const table = (rows: Rule[]) => (
    <table className="clickable rules">
      <thead><tr><th>Paragraph</th><th>What it requires</th><th>Status</th><th>How Kisht enforces it</th><th>Stopped so far</th></tr></thead>
      <tbody>{rows.map((r) => <Row key={r.id} r={r} />)}</tbody>
    </table>
  );
  return (
    <Page
      title="Rules"
      stale={error}
      sub={`RBI's recovery-conduct directions (${main.number}) take effect on ${new Date(main.effective).toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" })}. Each rule below is traced to the code that enforces it and the tests that prove it; a test run fails if a row points at something that does not exist. Click a row for the code and tests.`}
    >
      <div className="tiles">
        <Tile label="In force from" value={days > 0 ? `${days} days` : "Now"} hint={days > 0 ? "until the new rules apply" : "the new rules apply"} />
        <Tile label="Enforced by code" value={s.enforced ?? 0} hint="with tests" tone="good" />
        <Tile label="Partly" value={s.partly ?? 0} hint="each says what is missing" tone="warn" />
        <Tile label="Not built" value={s.gap ?? 0} hint="listed, not hidden" tone="bad" />
        <Tile label="Not applicable" value={s.not_applicable ?? 0} hint="visits, possession, agencies" />
        <Tile label="Breaches stopped" value={data.rules.filter((r) => r.kind === "rbi").reduce((n, r) => n + r.blocked, 0)} hint="attempts blocked by code so far" />
      </div>
      <Card title="RBI rules">{table(data.rules.filter((r) => r.kind === "rbi"))}</Card>
      <Card title="Kisht's own policy, beside the rules">{table(data.rules.filter((r) => r.kind === "kisht"))}</Card>
      <p className="note">
        Not legal advice. "What it requires" is a paraphrase; the source is <a href={main.url} target="_blank" rel="noreferrer">{main.number}</a>. {main.note} The lender is fictional and the borrowers are synthetic.
      </p>
    </Page>
  );
}
