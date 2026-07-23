import { defineConfig, devices } from "@playwright/test";

// Layout invariants run against the ALREADY-BUILT dist/ (run `python build.py`
// first). Static files only — no app server, fully deterministic.
export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8123" },
  webServer: {
    command: "python3 -m http.server 8123 --bind 127.0.0.1 --directory ../dist",
    url: "http://127.0.0.1:8123/",
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    // Desktop Blink — what most dev-time checking already sees.
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Mobile WebKit — the iOS Safari engine. Not optional: it renders
    // inline-box backgrounds differently (see the 2026-07-24 flush-left
    // highlight bug that Chromium could not reproduce).
    { name: "webkit-iphone", use: { ...devices["iPhone 13"] } },
  ],
});
