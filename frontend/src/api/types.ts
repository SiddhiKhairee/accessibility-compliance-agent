// types.ts — hand-mirrored against backend/app/main.py's Pydantic response
// models. Not codegen'd (no OpenAPI-client tooling exists in this project
// yet, and adding one is out of scope for Phase 4) — keep in sync by hand
// when main.py's response shapes change.

export type ScanStatus = "queued" | "running" | "done" | "failed";
export type ViolationStatus = "open" | "fixed" | "rejected";
export type FixVerificationStatus = "verified" | "rejected" | "manual_review";
export type FixFailureReason =
  | "invalid_html"
  | "dom_changed"
  | "playwright_timeout"
  | "diff_failed_to_apply";
export type ApprovalDecision = "approved" | "rejected";
// combined_verification_status on PageOut / status on GenerateFixedPageResponse
export type CombinedVerificationStatus = "clean" | "violations_remain" | "error";

export interface ImpactAssessmentOut {
  id: number;
  is_critical_path: boolean;
  business_risk_score: number | null;
  reasoning_text: string | null;
}

export interface FixOut {
  id: number;
  proposed_code_diff: string | null;
  target_selector: string | null;
  verification_status: FixVerificationStatus | null;
  failure_reason: FixFailureReason | null;
  retry_count: number;
  // Most recent Approval decision for this fix, or null if never
  // approved/rejected yet — see main.py's get_scan().
  latest_approval_decision: ApprovalDecision | null;
}

export interface ViolationOut {
  id: number;
  wcag_rule: string;
  element_selector: string;
  severity: string;
  confidence: number | null;
  status: ViolationStatus;
  html_snippet: string | null;
  message: string | null;
  detection_confidence: string | null;
  impact_assessment: ImpactAssessmentOut | null;
  fix: FixOut | null;
}

export interface PageOut {
  id: number;
  url: string;
  raw_html_snapshot_path: string | null;
  status: string | null;
  failure_reason: string | null;
  violations: ViolationOut[];
  fixed_html_snapshot_path: string | null;
  combined_verification_status: CombinedVerificationStatus | null;
  combined_verification_detail: string | null;
  combined_verified_at: string | null;
}

export interface ScanOut {
  id: number;
  site_id: number;
  status: ScanStatus;
  started_at: string | null;
  completed_at: string | null;
  pages: PageOut[];
}

export interface ScanCreateResponse {
  scan_id: number;
  status: ScanStatus;
}

export interface SiteOut {
  id: number;
  url: string;
  last_scanned_at: string | null;
  latest_scan_status: ScanStatus | null;
}

export interface ScanSummaryOut {
  id: number;
  site_id: number;
  status: ScanStatus;
  started_at: string | null;
  completed_at: string | null;
}

export interface ApprovalOut {
  id: number;
  fix_id: number;
  approver: string | null;
  decision: ApprovalDecision | null;
  decided_at: string | null;
}

export interface GenerateFixedPageResponse {
  page_id: number;
  status: CombinedVerificationStatus;
  detail: string;
  fixes_included_count: number;
  fixes_pending_count: number;
  download_available: boolean;
}

export interface AgentCostBucket {
  call_count: number;
  avg_tokens_per_call: number;
  cache_hit_rate: number;
  models_used: string[];
  latency_ms_median: number | null;
  latency_ms_p95: number | null;
  success_rate: number;
}

export interface AgentCostSummary {
  by_agent: Record<string, AgentCostBucket>;
  fix_verification_status_counts: Record<string, number>;
  fix_retry_rate: number;
  total_fixes: number;
}

export interface ScanPerformanceSummary {
  total_scans: number;
  scan_success_rate: number;
  pipeline_time_median_s: number | null;
  pipeline_time_p95_s: number | null;
}

export interface AccessibilityScoreTrendPoint {
  scan_id: number;
  site_id: number;
  completed_at: string | null;
  open_violations_per_page: number | null;
}

export interface PerformanceSummary {
  agent_cost_summary: AgentCostSummary;
  scan_performance_summary: ScanPerformanceSummary;
  accessibility_score_trend: AccessibilityScoreTrendPoint[];
  // Phase 4 deliberately doesn't open real GitHub PRs — see design.md.
  // Always null for now; an honest placeholder, not a missing field.
  pr_metrics: null;
}
