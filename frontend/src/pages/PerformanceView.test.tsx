import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import PerformanceView from "./PerformanceView";
import { getPerformanceSummary } from "../api/client";
import type { PerformanceSummary } from "../api/types";

vi.mock("../api/client");

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeSummary(overrides: Partial<PerformanceSummary> = {}): PerformanceSummary {
  return {
    agent_cost_summary: {
      by_agent: {
        Reviewer: {
          call_count: 12,
          avg_tokens_per_call: 450,
          cache_hit_rate: 0.5,
          models_used: ["qwen/qwen3-32b"],
          latency_ms_median: 800,
          latency_ms_p95: null,
          success_rate: 0.95,
        },
      },
      fix_verification_status_counts: { verified: 8, rejected: 2 },
      fix_retry_rate: 0.1,
      total_fixes: 11,
    },
    scan_performance_summary: {
      total_scans: 5,
      scan_success_rate: 0.8,
      pipeline_time_median_s: 12.3,
      pipeline_time_p95_s: null,
    },
    accessibility_score_trend: [
      { scan_id: 1, site_id: 1, completed_at: "2026-01-01T00:00:00Z", open_violations_per_page: 2 },
      { scan_id: 2, site_id: 1, completed_at: null, open_violations_per_page: 3 },
      { scan_id: 3, site_id: 1, completed_at: "2026-01-03T00:00:00Z", open_violations_per_page: null },
      { scan_id: 4, site_id: 1, completed_at: "2026-01-05T00:00:00Z", open_violations_per_page: 1 },
    ],
    pr_metrics: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(getPerformanceSummary).mockReset();
});

describe("PerformanceView", () => {
  it("shows a loading state, then the summary once the fetch resolves", async () => {
    const d = deferred<PerformanceSummary>();
    vi.mocked(getPerformanceSummary).mockReturnValue(d.promise);
    render(<PerformanceView />);

    expect(screen.getByText("Loading…")).toBeInTheDocument();
    d.resolve(makeSummary());

    expect(await screen.findByText("Total scans")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
  });

  it("shows the error badge when the fetch rejects", async () => {
    vi.mocked(getPerformanceSummary).mockRejectedValue(new Error("summary unavailable"));
    render(<PerformanceView />);
    expect(await screen.findByText(/summary unavailable/)).toHaveClass("badge-error");
  });

  it("formats percentage and null-handling stat tiles correctly", async () => {
    vi.mocked(getPerformanceSummary).mockResolvedValue(makeSummary());
    render(<PerformanceView />);

    expect(await screen.findByText("80.0%")).toBeInTheDocument(); // scan_success_rate
    expect(screen.getByText("12.3s")).toBeInTheDocument(); // pipeline_time_median_s
    // pipeline_time_p95_s is null -> em-dash fallback. There are two "—"
    // stat tiles possible (p95 here, latency p95 in the table) so assert
    // at least one renders rather than a brittle exact count.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders one per-agent table row per entry in by_agent", async () => {
    vi.mocked(getPerformanceSummary).mockResolvedValue(makeSummary());
    render(<PerformanceView />);
    // "Reviewer" also appears as the bar chart's axis label, so scope to
    // the table cell specifically rather than getByText.
    expect(await screen.findByRole("cell", { name: "Reviewer" })).toBeInTheDocument();
    expect(screen.getByText("qwen/qwen3-32b")).toBeInTheDocument();
  });

  it("renders one verification-breakdown row per entry in fix_verification_status_counts", async () => {
    vi.mocked(getPerformanceSummary).mockResolvedValue(makeSummary());
    render(<PerformanceView />);
    await screen.findByText("Total scans");
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });

  it("filters out trend points with a null completed_at or open_violations_per_page before charting", async () => {
    vi.mocked(getPerformanceSummary).mockResolvedValue(makeSummary());
    render(<PerformanceView />);
    await screen.findByText("Total scans");

    const svg = screen.getByRole("img", {
      name: "Accessibility score trend (open violations per page, lower is better)",
    });
    // Of the 4 raw trend points, only scan_id 1 and 4 have both fields
    // non-null -> exactly 2 points survive the filter -> 2 axis labels
    // (first/last), not 4.
    expect(svg.querySelectorAll("text.chart-axis-label")).toHaveLength(2);
  });
});
