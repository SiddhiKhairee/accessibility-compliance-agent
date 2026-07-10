// client.ts — thin fetch wrapper against the FastAPI backend. No codegen,
// no client library dependency — see types.ts's own note on why.

import type {
  ApprovalDecision,
  ApprovalOut,
  GenerateFixedPageResponse,
  PerformanceSummary,
  ScanCreateResponse,
  ScanOut,
  ScanSummaryOut,
  SiteOut,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new ApiError(resp.status, body || resp.statusText);
  }
  return resp.json() as Promise<T>;
}

export function listSites(): Promise<SiteOut[]> {
  return request<SiteOut[]>("/sites");
}

export function listScans(siteId?: number): Promise<ScanSummaryOut[]> {
  const query = siteId !== undefined ? `?site_id=${siteId}` : "";
  return request<ScanSummaryOut[]>(`/scans${query}`);
}

export function getScan(scanId: number): Promise<ScanOut> {
  return request<ScanOut>(`/scan/${scanId}`);
}

export function createScan(
  url: string,
  maxPages?: number,
  maxDepth?: number,
): Promise<ScanCreateResponse> {
  return request<ScanCreateResponse>("/scan", {
    method: "POST",
    body: JSON.stringify({ url, max_pages: maxPages, max_depth: maxDepth }),
  });
}

export function createApproval(
  fixId: number,
  decision: ApprovalDecision,
  approver: string,
): Promise<ApprovalOut> {
  return request<ApprovalOut>(`/fixes/${fixId}/approval`, {
    method: "POST",
    body: JSON.stringify({ decision, approver }),
  });
}

export function generateFixedPage(pageId: number): Promise<GenerateFixedPageResponse> {
  return request<GenerateFixedPageResponse>(`/pages/${pageId}/generate-fixed-page`, {
    method: "POST",
  });
}

export function downloadFixedPageUrl(pageId: number): string {
  return `${API_BASE_URL}/pages/${pageId}/download-fixed`;
}

export function getPerformanceSummary(siteId?: number): Promise<PerformanceSummary> {
  const query = siteId !== undefined ? `?site_id=${siteId}` : "";
  return request<PerformanceSummary>(`/performance/summary${query}`);
}

export { ApiError };
