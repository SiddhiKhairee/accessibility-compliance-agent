import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the 'unknown' fallback for null", () => {
    render(<StatusBadge value={null} />);
    expect(screen.getByText("unknown")).toHaveClass("badge-neutral");
  });

  it("renders the 'unknown' fallback for undefined", () => {
    render(<StatusBadge value={undefined} />);
    expect(screen.getByText("unknown")).toHaveClass("badge-neutral");
  });

  it("maps a known ok-tone value to badge-ok", () => {
    render(<StatusBadge value="verified" />);
    expect(screen.getByText("verified")).toHaveClass("badge-ok");
  });

  it("maps a known warn-tone value to badge-warn", () => {
    render(<StatusBadge value="violations_remain" />);
    expect(screen.getByText("violations_remain")).toHaveClass("badge-warn");
  });

  it("maps a known error-tone value to badge-error", () => {
    render(<StatusBadge value="rejected" />);
    expect(screen.getByText("rejected")).toHaveClass("badge-error");
  });

  it("falls back to neutral tone for an unrecognized value", () => {
    render(<StatusBadge value="some-future-status" />);
    expect(screen.getByText("some-future-status")).toHaveClass("badge-neutral");
  });
});
