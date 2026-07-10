import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ViolationDiff from "./ViolationDiff";

describe("ViolationDiff", () => {
  it("renders the 'no HTML captured' message when both before and after are null", () => {
    render(<ViolationDiff before={null} after={null} />);
    expect(screen.getByText("No HTML captured for this violation.")).toBeInTheDocument();
  });

  it("renders the diff viewer when only 'before' is present", () => {
    render(<ViolationDiff before="<img>" after={null} />);
    expect(screen.queryByText("No HTML captured for this violation.")).not.toBeInTheDocument();
    expect(screen.getByText("Detected (before)")).toBeInTheDocument();
    expect(screen.getByText("Proposed fix (after)")).toBeInTheDocument();
  });

  it("renders the diff viewer when only 'after' is present", () => {
    render(<ViolationDiff before={null} after='<img alt="Hero">' />);
    expect(screen.queryByText("No HTML captured for this violation.")).not.toBeInTheDocument();
    expect(screen.getByText("Detected (before)")).toBeInTheDocument();
  });

  it("renders the diff viewer when both before and after are present", () => {
    render(<ViolationDiff before="<img>" after='<img alt="Hero">' />);
    expect(screen.queryByText("No HTML captured for this violation.")).not.toBeInTheDocument();
  });
});
