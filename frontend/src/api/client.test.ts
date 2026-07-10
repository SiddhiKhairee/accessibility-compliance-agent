import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  downloadFixedPageUrl,
  getPerformanceSummary,
  listScans,
} from "./client";

function mockFetchOnce(init: { ok: boolean; status?: number; json?: unknown; text?: string }) {
  const response = {
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 500),
    statusText: "Error",
    json: () => Promise.resolve(init.json),
    text: () => Promise.resolve(init.text ?? ""),
  } as unknown as Response;
  vi.mocked(fetch).mockResolvedValueOnce(response);
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api/client request wrapper", () => {
  it("resolves with the parsed JSON body on a 2xx response", async () => {
    mockFetchOnce({ ok: true, json: [{ id: 1 }] });
    const result = await listScans();
    expect(result).toEqual([{ id: 1 }]);
  });

  it("throws an ApiError carrying the status and response body text on a non-ok response", async () => {
    mockFetchOnce({ ok: false, status: 404, text: "scan not found" });
    await expect(listScans()).rejects.toBeInstanceOf(ApiError);
    mockFetchOnce({ ok: false, status: 404, text: "scan not found" });
    await expect(listScans()).rejects.toMatchObject({ status: 404, message: "scan not found" });
  });

  it("falls back to statusText when the error response body is empty", async () => {
    mockFetchOnce({ ok: false, status: 500, text: "" });
    await expect(listScans()).rejects.toMatchObject({ status: 500, message: "Error" });
  });

  it("builds no query string when siteId is omitted", async () => {
    mockFetchOnce({ ok: true, json: [] });
    await listScans();
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toBe("http://localhost:8000/scans");
  });

  it("appends site_id to the query string when provided", async () => {
    mockFetchOnce({ ok: true, json: [] });
    await listScans(7);
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toBe("http://localhost:8000/scans?site_id=7");
  });

  it("getPerformanceSummary appends site_id only when provided", async () => {
    mockFetchOnce({ ok: true, json: {} });
    await getPerformanceSummary(3);
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toBe("http://localhost:8000/performance/summary?site_id=3");
  });
});

describe("downloadFixedPageUrl", () => {
  it("builds the download URL without making a network request", () => {
    expect(downloadFixedPageUrl(42)).toBe("http://localhost:8000/pages/42/download-fixed");
    expect(fetch).not.toHaveBeenCalled();
  });
});
