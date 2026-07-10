const TONE_BY_VALUE: Record<string, "ok" | "warn" | "error" | "neutral"> = {
  done: "ok",
  verified: "ok",
  clean: "ok",
  approved: "ok",
  loaded: "ok",
  confirmed: "ok",
  running: "warn",
  queued: "neutral",
  needs_review: "warn",
  pending: "neutral",
  violations_remain: "warn",
  manual_review: "warn",
  failed: "error",
  rejected: "error",
  error: "error",
};

export default function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) {
    return <span className="badge badge-neutral">unknown</span>;
  }
  const tone = TONE_BY_VALUE[value] ?? "neutral";
  return <span className={`badge badge-${tone}`}>{value}</span>;
}
