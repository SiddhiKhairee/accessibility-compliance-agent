import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import "./App.css";
import ViolationsView from "./pages/ViolationsView";
import PerformanceView from "./pages/PerformanceView";
import ReviewApproveView from "./pages/ReviewApproveView";

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Accessibility Compliance Agent</h1>
        <nav className="app-nav">
          <NavLink to="/violations" className={({ isActive }) => (isActive ? "active" : "")}>
            Violations
          </NavLink>
          <NavLink to="/performance" className={({ isActive }) => (isActive ? "active" : "")}>
            System Performance
          </NavLink>
          <NavLink to="/review" className={({ isActive }) => (isActive ? "active" : "")}>
            Review &amp; Approve
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/violations" replace />} />
          <Route path="/violations" element={<ViolationsView />} />
          <Route path="/performance" element={<PerformanceView />} />
          <Route path="/review" element={<ReviewApproveView />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
