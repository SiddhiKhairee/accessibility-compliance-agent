import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ViolationsView from "./ViolationsView";
import { useScanSelector } from "../hooks/useScanSelector";
import type { PageOut, ScanOut, SiteOut, ViolationOut } from "../api/types";

vi.mock("../hooks/useScanSelector");

function makeViolation(overrides: Partial<ViolationOut> = {}): ViolationOut {
  return {
    id: 1,
    wcag_rule: "image-alt",
    element_selector: "img.hero",
    severity: "serious",
    confidence: 0.9,
    status: "open",
    html_snippet: "<img>",
    message: "Image is missing alt text",
    detection_confidence: "confirmed",
    impact_assessment: null,
    fix: null,
    ...overrides,
  };
}

function makePage(overrides: Partial<PageOut> = {}): PageOut {
  return {
    id: 100,
    url: "https://example.test/",
    raw_html_snapshot_path: null,
    status: "loaded",
    failure_reason: null,
    violations: [],
    fixed_html_snapshot_path: null,
    combined_verification_status: null,
    combined_verification_detail: null,
    combined_verified_at: null,
    ...overrides,
  };
}

function makeScan(pages: PageOut[]): ScanOut {
  return { id: 1, site_id: 1, status: "done", started_at: null, completed_at: null, pages };
}

function baseHookReturn(overrides: Partial<ReturnType<typeof useScanSelector>> = {}) {
  return {
    sites: [] as SiteOut[],
    selectedSiteId: null,
    setSelectedSiteId: vi.fn(),
    scans: [],
    selectedScanId: null,
    setSelectedScanId: vi.fn(),
    scan: null as ScanOut | null,
    refetchScan: vi.fn(),
    error: null as string | null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(useScanSelector).mockReturnValue(baseHookReturn());
});

describe("ViolationsView empty states", () => {
  it("shows 'No sites scanned yet' when there are no sites", () => {
    render(<ViolationsView />);
    expect(screen.getByText("No sites scanned yet.")).toBeInTheDocument();
  });

  it("shows 'No scans for this site' once a site is selected with zero scans", () => {
    vi.mocked(useScanSelector).mockReturnValue(
      baseHookReturn({ sites: [{ id: 1, url: "https://a.test", last_scanned_at: null, latest_scan_status: null }], selectedSiteId: 1 }),
    );
    render(<ViolationsView />);
    expect(screen.getByText("No scans for this site.")).toBeInTheDocument();
  });

  it("prompts to select a site/scan when no scan is loaded", () => {
    render(<ViolationsView />);
    expect(screen.getByText("Select a site and scan to see violations.")).toBeInTheDocument();
  });

  it("renders the error badge when the hook reports an error", () => {
    vi.mocked(useScanSelector).mockReturnValue(baseHookReturn({ error: "boom" }));
    render(<ViolationsView />);
    expect(screen.getByText("boom")).toHaveClass("badge-error");
  });
});

describe("ViolationsView selection interactions", () => {
  it("selecting a site calls setSelectedSiteId with that site's id", async () => {
    const setSelectedSiteId = vi.fn();
    vi.mocked(useScanSelector).mockReturnValue(
      baseHookReturn({ sites: [{ id: 42, url: "https://a.test", last_scanned_at: null, latest_scan_status: "done" }], setSelectedSiteId }),
    );
    render(<ViolationsView />);
    await userEvent.click(screen.getByText("https://a.test"));
    expect(setSelectedSiteId).toHaveBeenCalledWith(42);
  });

  it("selecting a scan calls setSelectedScanId with that scan's id", async () => {
    const setSelectedScanId = vi.fn();
    vi.mocked(useScanSelector).mockReturnValue(
      baseHookReturn({
        sites: [{ id: 1, url: "https://a.test", last_scanned_at: null, latest_scan_status: "done" }],
        selectedSiteId: 1,
        scans: [{ id: 9, site_id: 1, status: "done", started_at: null, completed_at: null }],
        setSelectedScanId,
      }),
    );
    render(<ViolationsView />);
    await userEvent.click(screen.getByText("Scan #9"));
    expect(setSelectedScanId).toHaveBeenCalledWith(9);
  });
});

describe("ViolationsView scan detail rendering", () => {
  it("shows 'No violations detected' for a page with zero violations", () => {
    vi.mocked(useScanSelector).mockReturnValue(baseHookReturn({ scan: makeScan([makePage({ violations: [] })]) }));
    render(<ViolationsView />);
    expect(screen.getByText("No violations detected.")).toBeInTheDocument();
  });

  it("only renders the fixed-page status badge when combined_verification_status is present", () => {
    const { rerender } = render(<ViolationsView />);

    vi.mocked(useScanSelector).mockReturnValue(
      baseHookReturn({ scan: makeScan([makePage({ combined_verification_status: null })]) }),
    );
    rerender(<ViolationsView />);
    expect(screen.queryByText(/fixed-page status:/)).not.toBeInTheDocument();

    vi.mocked(useScanSelector).mockReturnValue(
      baseHookReturn({ scan: makeScan([makePage({ combined_verification_status: "clean" })]) }),
    );
    rerender(<ViolationsView />);
    expect(screen.getByText(/fixed-page status:/)).toBeInTheDocument();
  });

  it("only renders a fix-status badge when the violation has a fix", () => {
    const withFix = makeViolation({
      id: 1,
      fix: { id: 1, proposed_code_diff: null, target_selector: null, verification_status: "verified", failure_reason: null, retry_count: 0, latest_approval_decision: null },
    });
    const withoutFix = makeViolation({ id: 2, wcag_rule: "html-has-lang", fix: null });
    vi.mocked(useScanSelector).mockReturnValue(baseHookReturn({ scan: makeScan([makePage({ violations: [withFix, withoutFix] })]) }));
    render(<ViolationsView />);
    expect(screen.getByText("verified")).toBeInTheDocument();
  });

  it("toggles a violation's diff open and closed on click", async () => {
    const violation = makeViolation({ html_snippet: "<img>", fix: null });
    vi.mocked(useScanSelector).mockReturnValue(baseHookReturn({ scan: makeScan([makePage({ violations: [violation] })]) }));
    render(<ViolationsView />);

    expect(screen.queryByText("Detected (before)")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("image-alt"));
    expect(screen.getByText("Detected (before)")).toBeInTheDocument();
    await userEvent.click(screen.getByText("image-alt"));
    expect(screen.queryByText("Detected (before)")).not.toBeInTheDocument();
  });
});
