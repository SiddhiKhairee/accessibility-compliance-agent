import { useEffect, useState } from "react";
import { getPerformanceSummary } from "../api/client";
import type { PerformanceSummary } from "../api/types";
import BarChart from "../components/BarChart";
import StatTile from "../components/StatTile";
import TrendLineChart from "../components/TrendLineChart";

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const ms = (v: number | null) => (v === null ? "—" : `${v.toFixed(0)}ms`);
const s = (v: number | null) => (v === null ? "—" : `${v.toFixed(1)}s`);

export default function PerformanceView() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPerformanceSummary().then(setSummary).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="badge badge-error">{error}</p>;
  if (!summary) return <p className="muted">Loading…</p>;

  const agentNames = Object.keys(summary.agent_cost_summary.by_agent);
  const trendPoints = summary.accessibility_score_trend
    .filter((p) => p.open_violations_per_page !== null && p.completed_at !== null)
    .map((p) => ({
      x: new Date(p.completed_at as string).toLocaleDateString(),
      y: p.open_violations_per_page as number,
    }));

  return (
    <div>
      <h2>System Performance</h2>

      <div className="stat-tile-row">
        <StatTile label="Total scans" value={summary.scan_performance_summary.total_scans.toLocaleString()} />
        <StatTile label="Scan success rate" value={pct(summary.scan_performance_summary.scan_success_rate)} />
        <StatTile label="Pipeline time (median)" value={s(summary.scan_performance_summary.pipeline_time_median_s)} />
        <StatTile label="Pipeline time (p95)" value={s(summary.scan_performance_summary.pipeline_time_p95_s)} />
        <StatTile label="Total fixes" value={summary.agent_cost_summary.total_fixes.toLocaleString()} />
        <StatTile label="Fix retry rate" value={pct(summary.agent_cost_summary.fix_retry_rate)} />
      </div>

      <div className="card">
        <BarChart
          title="LLM calls per agent"
          data={agentNames.map((name) => ({
            label: name,
            value: summary.agent_cost_summary.by_agent[name].call_count,
          }))}
        />
      </div>

      <div className="card">
        <h3>Per-agent detail</h3>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Calls</th>
              <th>Avg tokens</th>
              <th>Cache hit %</th>
              <th>Latency (median)</th>
              <th>Latency (p95)</th>
              <th>Success %</th>
              <th>Models used</th>
            </tr>
          </thead>
          <tbody>
            {agentNames.map((name) => {
              const a = summary.agent_cost_summary.by_agent[name];
              return (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{a.call_count}</td>
                  <td>{a.avg_tokens_per_call.toFixed(0)}</td>
                  <td>{pct(a.cache_hit_rate)}</td>
                  <td>{ms(a.latency_ms_median)}</td>
                  <td>{ms(a.latency_ms_p95)}</td>
                  <td>{pct(a.success_rate)}</td>
                  <td>{a.models_used.join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Fix verification breakdown</h3>
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(summary.agent_cost_summary.fix_verification_status_counts).map(([status, count]) => (
              <tr key={status}>
                <td>{status}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <TrendLineChart title="Accessibility score trend (open violations per page, lower is better)" points={trendPoints} />
      </div>

      <div className="card">
        <h3>PR metrics</h3>
        <p className="muted">
          N/A — Phase 4 doesn't open real GitHub PRs (approval produces a verified, downloadable
          fixed page instead). Real PR metrics are Phase 6 scope, once a real target repo is chosen.
        </p>
      </div>
    </div>
  );
}
