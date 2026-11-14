import { useCallback, useEffect, useRef, useState, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

/** Load data once, or every `pollMs` (live views). */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(load, deps);
  const refresh = useCallback(() => {
    let current = true;
    run().then(
      (d) => {
        if (!current) return; // an older request must not overwrite a newer one
        setData(d);
        setError(null);
      },
      (e: Error) => current && setError(e.message),
    );
    return () => {
      current = false;
    };
  }, [run]);
  useEffect(() => {
    let cancel = refresh();
    if (!pollMs) return cancel;
    // No polling while the tab is hidden; one refresh when it comes back.
    const tick = () => {
      if (document.hidden) return;
      cancel();
      cancel = refresh();
    };
    const t = setInterval(tick, pollMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      cancel();
      clearInterval(t);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [refresh, pollMs]);
  return { data, error, refresh };
}

/** The value, a moment after it stops changing (search boxes). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Page({ title, sub, children, actions, stale }: { title: string; sub?: string; children: ReactNode; actions?: ReactNode; stale?: string | null }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {sub && <p className="sub">{sub}</p>}
        </div>
        {actions}
      </header>
      {stale && <div className="banner" role="alert">Cannot reach the server ({stale}). Showing the last data received.</div>}
      {children}
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  if (error) return <div className="banner" role="alert">Could not load: {error}</div>;
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label="Loading">
      <div /><div /><div />
    </div>
  );
}

/** Props that make a row or list item work like a button: click, Enter or Space. */
export function press(fn: () => void) {
  return {
    tabIndex: 0,
    onClick: fn,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return;
      e.preventDefault();
      fn();
    },
  };
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

/** A labelled input with an optional hint and error. The label is always visible; the error
 * is tied to the input so a screen reader reads it with the field. */
export function Field({ label, hint, error, id, ...input }: { label: string; hint?: string; error?: string | null; id: string } & InputHTMLAttributes<HTMLInputElement>) {
  const notes = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-describedby={notes} aria-invalid={error ? true : undefined} {...input} />
      {hint && <div id={`${id}-hint`} className="muted small">{hint}</div>}
      {error && <div id={`${id}-error`} className="error" role="alert">{error}</div>}
    </div>
  );
}

/** Ask before an action that cannot be taken back. The browser's own <dialog> keeps focus
 * inside, closes on Escape and gives focus back to the button that opened it. */
export function Confirm({ open, title, children, action, tone = "danger", onConfirm, onClose }: {
  open: boolean; title: string; children: ReactNode; action: string; tone?: "danger" | "primary"; onConfirm: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="confirm-title" onClose={onClose}>
      <h2 id="confirm-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button className="secondary" autoFocus onClick={onClose}>Cancel</button>
        <button className={tone === "danger" ? "danger" : undefined} onClick={() => { onClose(); onConfirm(); }}>{action}</button>
      </div>
    </dialog>
  );
}
