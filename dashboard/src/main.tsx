import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import CallDetail from "./pages/CallDetail";
import Calls from "./pages/Calls";
import Chat from "./pages/Chat";
import Desk from "./pages/Desk";
import Live from "./pages/Live";
import Overview from "./pages/Overview";
import Plan from "./pages/Plan";
import Quality from "./pages/Quality";
import Rules from "./pages/Rules";
import { api } from "./api";
import { useLoad } from "./ui";

const NAV = [
  ["/", "Overview"],
  ["/plan", "Today's plan"],
  ["/live", "Live"],
  ["/calls", "Call log"],
  ["/desk", "Human desk"],
  ["/quality", "Quality"],
  ["/rules", "Rules"],
  ["/chat", "Test chat"],
] as const;

/** Is everything the dashboard depends on up? Asked every 10 seconds. */
function Status() {
  const { data: h, error } = useLoad(api.health, [], 10000);
  if (!h) return <div className="status">{error ? <Row ok={false} label="Server not reachable" /> : null}</div>;
  return (
    <div className="status">
      <Row ok={h.model.ok} label={h.model.ok ? `Model: ${h.model.name}` : "Model server is down"} />
      <Row ok={h.call_state.ok} label={h.call_state.ok ? "Call state: up" : "Redis is down"} />
      <Row ok={h.clock.open} warn label={`Calling hours ${h.clock.window}: ${h.clock.open ? "open" : "closed"}`} />
      {h.clock.fixed && <div className="status-note">Demo clock: {h.clock.now.replace("T", " ").slice(0, 16)}</div>}
    </div>
  );
}

function Row({ ok, label, warn }: { ok: boolean; label: string; warn?: boolean }) {
  return (
    <div className="status-row" title={label}>
      <span className={`dot ${ok ? "ok" : warn ? "warn" : "down"}`} />
      <span>{label}</span>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <nav className="side">
          <div className="brand">
            <div className="logo">K</div>
            <div>
              <b>Kisht</b>
              <div className="small">EMI contact centre</div>
            </div>
          </div>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>
          ))}
          <div className="side-foot small">
            <Status />
            Synthetic borrowers only.<br />AI decides, code guards.
          </div>
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/plan" element={<Plan />} />
            <Route path="/live" element={<Live />} />
            <Route path="/calls" element={<Calls />} />
            <Route path="/calls/:id" element={<CallDetail />} />
            <Route path="/desk" element={<Desk />} />
            <Route path="/quality" element={<Quality />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="/chat" element={<Chat />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
