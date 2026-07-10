import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TrendLineChart from "./TrendLineChart";

describe("TrendLineChart", () => {
  it("renders the empty-state message and no svg when points is empty", () => {
    render(<TrendLineChart title="Score trend" points={[]} />);
    expect(screen.getByText("No completed scans yet.")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "Score trend" })).not.toBeInTheDocument();
  });

  it("renders a single-point series centered, without a second axis label", () => {
    render(<TrendLineChart title="Score trend" points={[{ x: "2026-01-01", y: 5 }]} />);
    const svg = screen.getByRole("img", { name: "Score trend" });
    // Single point: only the first-point axis label text renders, per the
    // `points.length > 1` guard on the last-point label.
    expect(svg.querySelectorAll("text.chart-axis-label")).toHaveLength(1);
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
  });

  it("renders both endpoint labels for a multi-point series", () => {
    render(
      <TrendLineChart
        title="Score trend"
        points={[
          { x: "2026-01-01", y: 2 },
          { x: "2026-01-02", y: 4 },
          { x: "2026-01-03", y: 8 },
        ]}
      />,
    );
    const svg = screen.getByRole("img", { name: "Score trend" });
    expect(svg.querySelectorAll("text.chart-axis-label")).toHaveLength(2);
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
    expect(screen.getByText("2026-01-03")).toBeInTheDocument();
  });

  it("floors maxY at 1 so an all-zero series still renders a flat line without dividing by zero", () => {
    render(
      <TrendLineChart
        title="Score trend"
        points={[
          { x: "2026-01-01", y: 0 },
          { x: "2026-01-02", y: 0 },
        ]}
      />,
    );
    const svg = screen.getByRole("img", { name: "Score trend" });
    const path = svg.querySelector("path.chart-line");
    expect(path).toBeInTheDocument();
    expect(path?.getAttribute("d")).not.toContain("NaN");
  });
});
