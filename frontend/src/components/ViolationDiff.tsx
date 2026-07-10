import ReactDiffViewer from "react-diff-viewer-continued";

// Wraps ReactDiffViewer with the two fields every violation actually has:
// the detected html_snippet ("before") and the Developer agent's
// proposed_code_diff ("after"). No dark-theme detection library added just
// for this — prefers-color-scheme is read once at mount, matching how the
// rest of the app's CSS already themes via the same media query.
const prefersDark =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export default function ViolationDiff({
  before,
  after,
}: {
  before: string | null;
  after: string | null;
}) {
  if (!before && !after) {
    return <p className="muted">No HTML captured for this violation.</p>;
  }
  return (
    <div style={{ overflowX: "auto", maxWidth: "100%" }}>
      <ReactDiffViewer
        oldValue={before ?? ""}
        newValue={after ?? "(no fix proposed yet)"}
        splitView
        useDarkTheme={prefersDark}
        leftTitle="Detected (before)"
        rightTitle="Proposed fix (after)"
      />
    </div>
  );
}
