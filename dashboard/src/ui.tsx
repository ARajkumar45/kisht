import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

/** Load data once, or every `pollMs` (live views). */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const refresh = useCallback(() => {
    run().then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [run]);
  useEffect(() => {
    refresh();
    if (!pollMs) return;
    const t = setInterval(refresh, pollMs);
    return () => clearInterval(t);
  }, [refresh, pollMs]);
  return { data, error, refresh };
}

export function Page({ title, sub, children, actions }: { title: string; sub?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {actions}
      </header>
      {children}
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return <div className={error ? "error" : "muted"}>{error ? `Could not load: ${error}` : "Loading…"}</div>;
}

export function Tile({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className={`tile ${tone ?? ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value ?? "–"}</div>
      {hint && <div className="tile-hint">{hint}</div>}
    </div>
  );
}

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="card">
      {(title || right) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

/** Horizontal bars for a {label: count} map, largest first. */
export function Bars({ data, labels, empty = "No data yet" }: { data: Record<string, number>; labels?: Record<string, string>; empty?: string }) {
  const rows = Object.entries(data).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (!rows.length) return <div className="muted">{empty}</div>;
  const max = Math.max(...rows.map(([, v]) => v));
  return (
    <div className="bars">
      {rows.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <div className="bar-label">{labels?.[k] ?? human(k)}</div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(100 * v) / max}%` }} />
          </div>
          <div className="bar-value">{v}</div>
        </div>
      ))}
    </div>
  );
}

const OUTCOME_TONE: Record<string, string> = {
  promise: "good",
  link_sent: "good",
  escalated: "warn",
  opted_out: "neutral",
  not_verified: "bad",
  talked: "neutral",
};

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="badge live">live</span>;
  const [kind, detail] = outcome.split(":");
  return <span className={`badge ${OUTCOME_TONE[kind] ?? "neutral"}`}>{human(kind)}{detail ? ` · ${human(detail)}` : ""}</span>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export const LANG: Record<string, string> = { en: "English", hi: "Hindi", ta: "Tamil", te: "Telugu", kn: "Kannada" };

export function human(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function rupees(n: number | null | undefined): string {
  return n == null ? "–" : "₹" + n.toLocaleString("en-IN");
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function duration(a: string | null, b: string | null): string {
  if (!a || !b) return "–";
  const s = Math.round((new Date(b).getTime() - new Date(a).getTime()) / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

export function CallLink({ id, children }: { id: string; children?: ReactNode }) {
  return <Link to={`/calls/${id}`}>{children ?? id.slice(0, 8)}</Link>;
}

export function pct(n: number | null | undefined): string {
  return n == null ? "–" : `${n}%`;
}
