import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewApproveView from "./ReviewApproveView";
import { useScanSelector } from "../hooks/useScanSelector";
import { createApproval, downloadFixedPageUrl, generateFixedPage } from "../api/client";
import type { FixOut, PageOut, ScanOut, ViolationOut } from "../api/types";

vi.mock("../hooks/useScanSelector");
vi.mock("../api/client");

function makeFix(overrides: Partial<FixOut> = {}): FixOut {
  return {
    id: 1,
    proposed_code_diff: '<img alt="Hero">',
    target_selector: "img.hero",
    verification_status: "verified",
    failure_reason: null,
    retry_count: 0,
    latest_approval_decision: null,
    ...overrides,
  };
}

function makeViolation(overrides: Partial<ViolationOut> = {}): ViolationOut {
  return {
    id: 1,
    wcag_rule: "image-alt",
    element_selector: "img.hero",
    severity: "serious",
    confidence: 0.9,
    status: "open",
    html_snippet: "<img>",
    message: null,
    detection_confidence: "confirmed",
    impact_assessment: null,
    fix: makeFix(),
    ...overrides,
  };
}

function makePage(overrides: Partial<PageOut> = {}): PageOut {
  return {
    id: 100,
    url: "https://example.test/",
    raw_html_snapshot_path: "/snap/100.html",
    status: "loaded",
    failure_reason: null,
    violations: [makeViolation()],
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
    sites: [],
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

function mockScan(pages: PageOut[], refetchScan = vi.fn()) {
  vi.mocked(useScanSelector).mockReturnValue(baseHookReturn({ scan: makeScan(pages), refetchScan }));
}

beforeEach(() => {
  vi.mocked(useScanSelector).mockReturnValue(baseHookReturn());
  vi.mocked(createApproval).mockReset().mockResolvedValue({
    id: 1,
    fix_id: 1,
    approver: "dashboard-user",
    decision: "approved",
    decided_at: null,
  });
  vi.mocked(generateFixedPage).mockReset();
  vi.mocked(downloadFixedPageUrl).mockReset().mockImplementation((pageId) => `http://localhost:8000/pages/${pageId}/download-fixed`);
});

describe("approvableViolations filtering", () => {
  it("does not render a page card when it has no verified-fix violations to approve", () => {
    mockScan([
      makePage({
        url: "https://no-approvable.test/",
        violations: [makeViolation({ fix: makeFix({ verification_status: "manual_review" }) }), makeViolation({ id: 2, fix: null })],
      }),
    ]);
    render(<ReviewApproveView />);
    expect(screen.queryByText("https://no-approvable.test/")).not.toBeInTheDocument();
  });

  it("renders a page card for a page with at least one verified-fix violation", () => {
    mockScan([makePage()]);
    render(<ReviewApproveView />);
    expect(screen.getByText("https://example.test/")).toBeInTheDocument();
  });
});

describe("approve/reject actions", () => {
  it("clicking Approve calls createApproval with the fix id and decision, then refetches", async () => {
    const refetchScan = vi.fn();
    mockScan([makePage({ violations: [makeViolation({ fix: makeFix({ id: 7 }) })] })], refetchScan);
    render(<ReviewApproveView />);

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(createApproval).toHaveBeenCalledWith(7, "approved", "dashboard-user");
    expect(refetchScan).toHaveBeenCalled();
  });

  it("disables Approve once a violation is already approved, and Reject once already rejected", () => {
    mockScan([
      makePage({
        violations: [
          makeViolation({ id: 1, fix: makeFix({ id: 1, latest_approval_decision: "approved" }) }),
          makeViolation({ id: 2, fix: makeFix({ id: 2, latest_approval_decision: "rejected" }) }),
        ],
      }),
    ]);
    render(<ReviewApproveView />);
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    const rejectButtons = screen.getAllByRole("button", { name: "Reject" });
    expect(approveButtons[0]).toBeDisabled(); // fix 1: already approved
    expect(rejectButtons[1]).toBeDisabled(); // fix 2: already rejected
  });

  it("'Approve all on this page' only approves violations that aren't already decided", async () => {
    const refetchScan = vi.fn();
    mockScan(
      [
        makePage({
          violations: [
            makeViolation({ id: 1, fix: makeFix({ id: 1, latest_approval_decision: "approved" }) }),
            makeViolation({ id: 2, fix: makeFix({ id: 2, latest_approval_decision: null }) }),
          ],
        }),
      ],
      refetchScan,
    );
    render(<ReviewApproveView />);

    await userEvent.click(screen.getByRole("button", { name: "Approve all on this page" }));
    expect(createApproval).toHaveBeenCalledTimes(1);
    expect(createApproval).toHaveBeenCalledWith(2, "approved", "dashboard-user");
    expect(refetchScan).toHaveBeenCalled();
  });
});

describe("Generate button state and label", () => {
  it("is disabled when zero violations on the page are approved", () => {
    mockScan([makePage({ violations: [makeViolation({ fix: makeFix({ latest_approval_decision: null }) })] })]);
    render(<ReviewApproveView />);
    expect(screen.getByRole("button", { name: /Generate/ })).toBeDisabled();
  });

  it("labels 'Generate fixed page (n/n approved)' when every approvable violation is approved", () => {
    mockScan([makePage({ violations: [makeViolation({ fix: makeFix({ latest_approval_decision: "approved" }) })] })]);
    render(<ReviewApproveView />);
    expect(screen.getByRole("button", { name: "Generate fixed page (1/1 approved)" })).toBeInTheDocument();
  });

  it("labels 'Generate partial fix (n/m approved)' when only some approvable violations are approved", () => {
    mockScan([
      makePage({
        violations: [
          makeViolation({ id: 1, fix: makeFix({ id: 1, latest_approval_decision: "approved" }) }),
          makeViolation({ id: 2, fix: makeFix({ id: 2, latest_approval_decision: null }) }),
        ],
      }),
    ]);
    render(<ReviewApproveView />);
    expect(screen.getByRole("button", { name: "Generate partial fix (1/2 approved)" })).toBeInTheDocument();
  });

  it("calls generateFixedPage with the page id and shows the result detail", async () => {
    vi.mocked(generateFixedPage).mockResolvedValue({
      page_id: 100,
      status: "clean",
      detail: "1 fix applied, page is clean",
      fixes_included_count: 1,
      fixes_pending_count: 0,
      download_available: true,
    });
    mockScan([makePage({ violations: [makeViolation({ fix: makeFix({ latest_approval_decision: "approved" }) })] })]);
    render(<ReviewApproveView />);

    await userEvent.click(screen.getByRole("button", { name: /Generate/ }));
    expect(generateFixedPage).toHaveBeenCalledWith(100);
    expect(await screen.findByText("1 fix applied, page is clean")).toBeInTheDocument();
  });
});

describe("Download link gating — combined_verification_status === 'clean' only", () => {
  it("renders the download link when the page's combined_verification_status is 'clean'", () => {
    mockScan([makePage({ combined_verification_status: "clean" })]);
    render(<ReviewApproveView />);
    const link = screen.getByRole("link", { name: "Download fixed page" });
    expect(link).toHaveAttribute("href", "http://localhost:8000/pages/100/download-fixed");
  });

  it("does NOT render the download link when combined_verification_status is 'violations_remain'", () => {
    mockScan([makePage({ combined_verification_status: "violations_remain" })]);
    render(<ReviewApproveView />);
    expect(screen.queryByRole("link", { name: "Download fixed page" })).not.toBeInTheDocument();
  });

  it("does NOT render the download link when combined_verification_status is null (never generated)", () => {
    mockScan([makePage({ combined_verification_status: null })]);
    render(<ReviewApproveView />);
    expect(screen.queryByRole("link", { name: "Download fixed page" })).not.toBeInTheDocument();
  });
});
