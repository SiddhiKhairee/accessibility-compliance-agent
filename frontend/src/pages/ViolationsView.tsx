import { useState } from "react";
import StatusBadge from "../components/StatusBadge";
import ViolationDiff from "../components/ViolationDiff";
import { useScanSelector } from "../hooks/useScanSelector";

export default function ViolationsView() {
  const { sites, selectedSiteId, setSelectedSiteId, scans, selectedScanId, setSelectedScanId, scan, error } =
    useScanSelector();
  const [expandedViolationId, setExpandedViolationId] = useState<number | null>(null);

  return (
    <div>
      <h2>Violations</h2>
      {error && <p className="badge badge-error">{error}</p>}

      <div className="layout-columns">
        <div className="card">
          <h3>Sites</h3>
          <div className="select-list">
            {sites.length === 0 && <p className="muted">No sites scanned yet.</p>}
            {sites.map((site) => (
              <button
                key={site.id}
                className={site.id === selectedSiteId ? "selected" : ""}
                onClick={() => setSelectedSiteId(site.id)}
              >
                <div>{site.url}</div>
                <StatusBadge value={site.latest_scan_status} />
              </button>
            ))}
          </div>

          {selectedSiteId !== null && (
            <>
              <h3 style={{ marginTop: 16 }}>Scans</h3>
              <div className="select-list">
                {scans.length === 0 && <p className="muted">No scans for this site.</p>}
                {scans.map((s) => (
                  <button
                    key={s.id}
                    className={s.id === selectedScanId ? "selected" : ""}
                    onClick={() => setSelectedScanId(s.id)}
                  >
                    <div>Scan #{s.id}</div>
                    <StatusBadge value={s.status} />
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        <div>
          {!scan && <p className="muted">Select a site and scan to see violations.</p>}
          {scan &&
            scan.pages.map((page) => (
              <div className="card" key={page.id}>
                <h3>{page.url}</h3>
                <p>
                  <StatusBadge value={page.status} />{" "}
                  {page.combined_verification_status && (
                    <>
                      fixed-page status: <StatusBadge value={page.combined_verification_status} />
                    </>
                  )}
                </p>
                {page.violations.length === 0 && <p className="muted">No violations detected.</p>}
                {page.violations.map((v) => (
                  <div key={v.id} style={{ borderTop: "1px solid var(--border)", paddingTop: 8, marginTop: 8 }}>
                    <button
                      onClick={() => setExpandedViolationId(expandedViolationId === v.id ? null : v.id)}
                      style={{ background: "none", border: "none", textAlign: "left", width: "100%", padding: 0 }}
                    >
                      <strong>{v.wcag_rule}</strong> @ <code>{v.element_selector}</code>{" "}
                      <span className="badge badge-neutral">{v.severity}</span>{" "}
                      <StatusBadge value={v.status} />{" "}
                      {v.fix && <StatusBadge value={v.fix.verification_status} />}
                    </button>
                    {v.message && <p className="muted">{v.message}</p>}
                    {expandedViolationId === v.id && (
                      <ViolationDiff before={v.html_snippet} after={v.fix?.proposed_code_diff ?? null} />
                    )}
                  </div>
                ))}
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
