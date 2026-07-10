import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts by design (Phase 4.5, Decision 2) — mirrors
// this project's existing dev/test separation (.env vs .env.test, distinct
// Postgres services) rather than merging a `test` block into the prod
// build config.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setupTests.ts"],
    globals: false,
  },
});
