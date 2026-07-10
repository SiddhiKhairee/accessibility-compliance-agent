import { useCallback, useEffect, useState } from "react";
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
    listScans(selectedSiteId).then(setScans).catch((e) => setError(String(e)));
  }, [selectedSiteId]);

  const refetchScan = useCallback(() => {
    if (selectedScanId === null) {
      setScan(null);
      return;
    }
    getScan(selectedScanId).then(setScan).catch((e) => setError(String(e)));
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
