import { useCallback, useEffect, useRef, useState } from "react";
import { getScan, listScans, listSites } from "../api/client";
import type { ScanOut, ScanSummaryOut, SiteOut } from "../api/types";

// Shared site -> scan -> scan-detail drill-down, identical logic needed by
// both ViolationsView and ReviewApproveView.
export function useScanSelector() {
  const [sites, setSites] = useState<SiteOut[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null);
  const [scans, setScans] = useState<ScanSummaryOut[]>([]);
  const [selectedScanId, setSelectedScanId] = useState<number | null>(null);
  const [scan, setScan] = useState<ScanOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSites().then(setSites).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (selectedSiteId === null) {
      setScans([]);
      return;
    }
    setSelectedScanId(null);
    setScan(null);
    // Guards against a stale response: if selectedSiteId changes again
    // before this listScans() call resolves, this effect's own cleanup
    // fires first and marks the in-flight response cancelled so it can't
    // clobber the newer selection's state.
    let cancelled = false;
    listScans(selectedSiteId)
      .then((result) => {
        if (!cancelled) setScans(result);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSiteId]);

  // A ref, not an effect-cleanup flag: refetchScan is also invoked
  // imperatively (e.g. after an approval/generate action) outside the
  // effect that originally triggered it, so "is this response still
  // current" has to survive across separate calls, not just one effect's
  // closure.
  const latestScanRequestId = useRef(0);

  const refetchScan = useCallback(() => {
    if (selectedScanId === null) {
      latestScanRequestId.current += 1;
      setScan(null);
      return;
    }
    const requestId = ++latestScanRequestId.current;
    getScan(selectedScanId)
      .then((result) => {
        if (latestScanRequestId.current === requestId) setScan(result);
      })
      .catch((e) => {
        if (latestScanRequestId.current === requestId) setError(String(e));
      });
  }, [selectedScanId]);

  useEffect(() => {
    refetchScan();
  }, [refetchScan]);

  return {
    sites,
    selectedSiteId,
    setSelectedSiteId,
    scans,
    selectedScanId,
    setSelectedScanId,
    scan,
    refetchScan,
    error,
  };
}
