// The plain "@testing-library/jest-dom" entry point assumes a global
// `expect` (vitest's `globals: true` mode). This project keeps
// `globals: false` (explicit `import { expect } from "vitest"` in every
// test file, consistent with `verbatimModuleSyntax`), so the
// Vitest-specific entry point is required instead — it extends Vitest's
// own `expect` module rather than reaching for a global.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Same `globals: false` consequence as above: React Testing Library's own
// auto-cleanup only self-registers when it detects a *global* `afterEach`
// (jest, or vitest's `globals: true`). With explicit imports instead,
// nothing unmounts the previous test's render, so every test after the
// first sees leftover DOM from prior tests unless this runs explicitly.
afterEach(cleanup);

// Async-assertion convention (Phase 4.5, Resolution R2): every
// loading -> error -> success assertion in this suite uses RTL's
// `findBy*` (preferred) or `waitFor` — never a manual `act()` wrapper.
// Established once here so every test file downstream follows the same
// pattern instead of improvising its own.

// jsdom doesn't implement matchMedia. ViolationDiff.tsx reads
// `window.matchMedia("(prefers-color-scheme: dark)")` at module load
// time (a top-level const, not inside the component body), so this must
// exist before any test file imports that component — setupFiles run
// before test files are loaded, so defining it here is early enough.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}
