import { useState } from "react";
import { createApproval, downloadFixedPageUrl, generateFixedPage } from "../api/client";
import type { GenerateFixedPageResponse, PageOut } from "../api/types";
import StatusBadge from "../components/StatusBadge";
import ViolationDiff from "../components/ViolationDiff";
import { useScanSelector } from "../hooks/useScanSelector";

const APPROVER = "dashboard-user"; // no auth/multi-tenancy in this project — see CLAUDE.md.

function approvableViolations(page: PageOut) {
  return page.violations.filter((v) => v.fix?.verification_status === "verified");
}

export default function ReviewApproveView() {
  const { sites, selectedSiteId, setSelectedSiteId, scans, selectedScanId, setSelectedScanId, scan, refetchScan, error } =
    useScanSelector();
  const [busyFixId, setBusyFixId] = useState<number | null>(null);
  const [busyPageId, setBusyPageId] = useState<number | null>(null);
  const [generateResults, setGenerateResults] = useState<Record<number, GenerateFixedPageResponse>>({});

  async function decide(fixId: number, decision: "approved" | "rejected") {
    setBusyFixId(fixId);
    try {
      await createApproval(fixId, decision, APPROVER);
      refetchScan();
    } finally {
      setBusyFixId(null);
    }
  }

  async function bulkApprove(page: PageOut) {
    const undecided = approvableViolations(page).filter((v) => v.fix?.latest_approval_decision == null);
    for (const v of undecided) {
      if (v.fix) await createApproval(v.fix.id, "approved", APPROVER);
    }
    refetchScan();
  }

  async function generate(page: PageOut) {
    setBusyPageId(page.id);
    try {
      const result = await generateFixedPage(page.id);
      setGenerateResults((prev) => ({ ...prev, [page.id]: result }));
      refetchScan();
    } finally {
      setBusyPageId(null);
    }
  }

  return (
    <div>
      <h2>Review &amp; Approve</h2>
      {error && <p className="badge badge-error">{error}</p>}

      <div className="layout-columns">
        <div className="card">
          <h3>Sites</h3>
          <div className="select-list">
            {sites.map((site) => (
              <button
                key={site.id}
                className={site.id === selectedSiteId ? "selected" : ""}
                onClick={() => setSelectedSiteId(site.id)}
              >
                {site.url}
              </button>
            ))}
          </div>
          {selectedSiteId !== null && (
            <>
              <h3 style={{ marginTop: 16 }}>Scans</h3>
              <div className="select-list">
                {scans.map((s) => (
                  <button
                    key={s.id}
                    className={s.id === selectedScanId ? "selected" : ""}
                    onClick={() => setSelectedScanId(s.id)}
                  >
                    Scan #{s.id}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <div>
          {!scan && <p className="muted">Select a site and scan to review fixes.</p>}
          {scan &&
            scan.pages.map((page) => {
              const approvable = approvableViolations(page);
              if (approvable.length === 0) return null;

              const approvedCount = approvable.filter((v) => v.fix?.latest_approval_decision === "approved").length;
              const totalCount = approvable.length;
              const result = generateResults[page.id];
              const canDownload = page.combined_verification_status !== "clean";

              return (
                <div className="card" key={page.id}>
                  <h3>{page.url}</h3>

                  {approvable.map((v) => (
                    <div key={v.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                      <p>
                        <strong>{v.wcag_rule}</strong> @ <code>{v.element_selector}</code>{" "}
                        {v.fix?.latest_approval_decision ? (
                          <StatusBadge value={v.fix.latest_approval_decision} />
                        ) : (
                          <span className="badge badge-neutral">pending</span>
                        )}
                      </p>
                      <ViolationDiff before={v.html_snippet} after={v.fix?.proposed_code_diff ?? null} />
                      <div className="button-row">
                        <button
                          className="button-primary"
                          disabled={busyFixId === v.fix?.id || v.fix?.latest_approval_decision === "approved"}
                          onClick={() => v.fix && decide(v.fix.id, "approved")}
                        >
                          Approve
                        </button>
                        <button
                          className="button-secondary"
                          disabled={busyFixId === v.fix?.id || v.fix?.latest_approval_decision === "rejected"}
                          onClick={() => v.fix && decide(v.fix.id, "rejected")}
                        >
                          Reject
                        </button>
                      </div>
                    </div>
                  ))}

                  <div className="button-row" style={{ marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                    <button className="button-secondary" onClick={() => bulkApprove(page)}>
                      Approve all on this page
                    </button>
                    <button
                      className="button-primary"
                      disabled={busyPageId === page.id || approvedCount === 0}
                      onClick={() => generate(page)}
                    >
                      {approvedCount === totalCount
                        ? `Generate fixed page (${approvedCount}/${totalCount} approved)`
                        : `Generate partial fix (${approvedCount}/${totalCount} approved)`}
                    </button>
                    {canDownload && (
                      <a className="button-secondary" href={downloadFixedPageUrl(page.id)} download>
                        Download fixed page
                      </a>
                    )}
                  </div>
                  {result && <p className="muted">{result.detail}</p>}
                  {page.combined_verification_status && !result && (
                    <p className="muted">
                      Last generation result: <StatusBadge value={page.combined_verification_status} />{" "}
                      {page.combined_verification_detail}
                    </p>
                  )}
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
}
