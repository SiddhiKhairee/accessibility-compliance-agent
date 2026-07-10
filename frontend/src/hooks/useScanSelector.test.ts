import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useScanSelector } from "./useScanSelector";
import { getScan, listScans, listSites } from "../api/client";
import type { ScanOut, ScanSummaryOut, SiteOut } from "../api/types";

vi.mock("../api/client", () => ({
  listSites: vi.fn(),
  listScans: vi.fn(),
  getScan: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeSite(id: number): SiteOut {
  return { id, url: `https://example${id}.test`, last_scanned_at: null, latest_scan_status: null };
}

function makeScanSummary(id: number, siteId: number): ScanSummaryOut {
  return { id, site_id: siteId, status: "done", started_at: null, completed_at: null };
}

function makeScan(id: number): ScanOut {
  return { id, site_id: 1, status: "done", started_at: null, completed_at: null, pages: [] };
}

beforeEach(() => {
  vi.mocked(listSites).mockReset().mockResolvedValue([]);
  vi.mocked(listScans).mockReset().mockResolvedValue([]);
  vi.mocked(getScan).mockReset();
});

describe("useScanSelector", () => {
  it("loads sites on mount", async () => {
    vi.mocked(listSites).mockResolvedValue([makeSite(1), makeSite(2)]);
    const { result } = renderHook(() => useScanSelector());
    await waitFor(() => expect(result.current.sites).toHaveLength(2));
  });

  it("propagates a listSites rejection to the error state", async () => {
    vi.mocked(listSites).mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useScanSelector());
    await waitFor(() => expect(result.current.error).toContain("network down"));
  });

  it("selecting a site resets scan selection and loads that site's scans", async () => {
    vi.mocked(listScans).mockResolvedValue([makeScanSummary(10, 1)]);
    const { result } = renderHook(() => useScanSelector());

    act(() => result.current.setSelectedSiteId(1));

    await waitFor(() => expect(result.current.scans).toHaveLength(1));
    expect(listScans).toHaveBeenCalledWith(1);
    expect(result.current.selectedScanId).toBeNull();
    expect(result.current.scan).toBeNull();
  });

  it("selecting a scan loads its detail", async () => {
    vi.mocked(getScan).mockResolvedValue(makeScan(5));
    const { result } = renderHook(() => useScanSelector());

    act(() => result.current.setSelectedScanId(5));

    await waitFor(() => expect(result.current.scan?.id).toBe(5));
  });

  it("guards against a stale site->scans response (R1): switching sites again before the first listScans resolves must not let the stale response win", async () => {
    const forSiteA = deferred<ScanSummaryOut[]>();
    const forSiteB = deferred<ScanSummaryOut[]>();
    vi.mocked(listScans).mockImplementation((siteId?: number) =>
      siteId === 1 ? forSiteA.promise : forSiteB.promise,
    );

    const { result } = renderHook(() => useScanSelector());

    act(() => result.current.setSelectedSiteId(1));
    act(() => result.current.setSelectedSiteId(2));

    // Resolve the *current* selection's request first, then the stale one.
    await act(async () => forSiteB.resolve([makeScanSummary(20, 2)]));
    await act(async () => forSiteA.resolve([makeScanSummary(10, 1)]));

    await waitFor(() => {
      expect(result.current.scans.map((s) => s.id)).toEqual([20]);
    });
  });

  it("guards against a stale getScan response (R1): reselecting a scan before the first getScan resolves must not let the stale response win", async () => {
    const forScanA = deferred<ScanOut>();
    const forScanB = deferred<ScanOut>();
    vi.mocked(getScan).mockImplementation((scanId: number) =>
      scanId === 1 ? forScanA.promise : forScanB.promise,
    );

    const { result } = renderHook(() => useScanSelector());

    act(() => result.current.setSelectedScanId(1));
    act(() => result.current.setSelectedScanId(2));

    // The earlier request (scan 1) settles *after* the current one (scan
    // 2) — without a guard this would silently overwrite the newer state.
    await act(async () => forScanB.resolve(makeScan(2)));
    await act(async () => forScanA.resolve(makeScan(1)));

    await waitFor(() => {
      expect(result.current.scan?.id).toBe(2);
    });
  });

  it("guards a stale response from an imperative refetchScan() call made outside the selection effect", async () => {
    const initial = deferred<ScanOut>();
    const staleManual = deferred<ScanOut>();
    const freshManual = deferred<ScanOut>();
    vi.mocked(getScan)
      .mockImplementationOnce(() => initial.promise)
      .mockImplementationOnce(() => staleManual.promise)
      .mockImplementationOnce(() => freshManual.promise);

    const { result } = renderHook(() => useScanSelector());
    // Selection effect fires getScan #1 (left pending — this test only
    // cares about the two imperative calls below, not this one).
    act(() => result.current.setSelectedScanId(1));

    // Two imperative refetches for the same scan id, in flight together —
    // the first of the two (now stale) must not win if it resolves last.
    act(() => result.current.refetchScan()); // getScan #2 (stale)
    act(() => result.current.refetchScan()); // getScan #3 (current)

    const staleResult: ScanOut = { ...makeScan(1), status: "failed" };
    const freshResult: ScanOut = { ...makeScan(1), status: "done" };
    await act(async () => freshManual.resolve(freshResult));
    await act(async () => staleManual.resolve(staleResult));

    await waitFor(() => {
      expect(result.current.scan?.status).toBe("done");
    });
  });
});
