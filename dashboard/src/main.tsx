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

const NAV = [
  ["/", "Overview"],
  ["/plan", "Today's plan"],
  ["/live", "Live"],
  ["/calls", "Call log"],
  ["/desk", "Human desk"],
  ["/quality", "Quality"],
  ["/chat", "Test chat"],
] as const;

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
