import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import BarChart from "./BarChart";

describe("BarChart", () => {
  it("renders an empty chart (baseline, no bars) without dividing by zero", () => {
    render(<BarChart title="Per-agent calls" data={[]} />);
    const svg = screen.getByRole("img", { name: "Per-agent calls" });
    expect(svg.querySelector("line.chart-baseline")).toBeInTheDocument();
    expect(svg.querySelectorAll("rect.chart-bar")).toHaveLength(0);
  });

  it("floors bar height at 1 for a zero-value entry instead of rendering nothing", () => {
    render(<BarChart title="Per-agent calls" data={[{ label: "Reviewer", value: 0 }]} />);
    const bar = document.querySelector("rect.chart-bar");
    expect(bar).toBeInTheDocument();
    expect(Number(bar?.getAttribute("height"))).toBeGreaterThanOrEqual(1);
  });

  it("renders one bar per data point with its label and formatted value", () => {
    render(
      <BarChart
        title="Per-agent calls"
        data={[
          { label: "Reviewer", value: 10 },
          { label: "Developer", value: 25 },
        ]}
      />,
    );
    expect(document.querySelectorAll("rect.chart-bar")).toHaveLength(2);
    expect(screen.getByText("Reviewer")).toBeInTheDocument();
    expect(screen.getByText("Developer")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("25")).toBeInTheDocument();
  });

  it("dims non-hovered bars on hover, and clears on mouse leave", () => {
    render(
      <BarChart
        title="Per-agent calls"
        data={[
          { label: "Reviewer", value: 10 },
          { label: "Developer", value: 25 },
        ]}
      />,
    );
    const bars = document.querySelectorAll("rect.chart-bar");
    const groups = document.querySelectorAll("g");
    fireEvent.mouseEnter(groups[0]);
    expect(bars[0]).toHaveAttribute("opacity", "1");
    expect(bars[1]).toHaveAttribute("opacity", "0.55");

    fireEvent.mouseLeave(groups[0]);
    expect(bars[0]).toHaveAttribute("opacity", "1");
    expect(bars[1]).toHaveAttribute("opacity", "1");
  });
});
