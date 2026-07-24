/**
 * Layout invariants — every assertion here is a bug that actually shipped:
 * page overflow from the nav/folio, unreachable first nav item, vertically
 * draggable nav row, WebKit painting hover highlights flush-left, dead
 * filter toggles. Computed assertions with tolerances, no golden images.
 */
import { expect, test, type Page } from "@playwright/test";
import { PNG } from "pngjs";

const VIEWPORTS = { mobile: { width: 375, height: 812 }, tablet: { width: 768, height: 1024 }, desktop: { width: 1280, height: 900 } };

let articlePath = "";
let sectionPath = "";

test.beforeAll(async ({ request }) => {
  const xml = await (await request.get("/sitemap-articles.xml")).text();
  const m = xml.match(/https:\/\/[^<]*?(\/[a-z]+\/[a-z0-9-]+\/)/);
  if (!m) throw new Error("sitemap-articles.xml has no article URLs — build dist first");
  articlePath = m[1];
  sectionPath = "/" + articlePath.split("/")[1] + "/";
});

async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

// --------------------------------------------------------------------------
// No horizontal page scroll, any page, any width.
// --------------------------------------------------------------------------
for (const [name, vp] of Object.entries(VIEWPORTS)) {
  test(`no horizontal overflow @ ${name}`, async ({ page }) => {
    await page.setViewportSize(vp);
    for (const path of ["/", sectionPath, articlePath, "/search/", "/privacy/", "/about/", "/404.html"]) {
      await page.goto(path);
      expect(await horizontalOverflow(page), `${path} overflows at ${name}`).toBeLessThanOrEqual(0);
    }
  });
}

// --------------------------------------------------------------------------
// Nav mechanics on mobile.
// --------------------------------------------------------------------------
test("mobile: first nav item is reachable (no centered-overflow clipping)", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  for (const path of ["/", sectionPath]) {
    await page.goto(path);
    const left = await page
      .locator(".nav__list li a")
      .first()
      .evaluate((a) => a.getBoundingClientRect().left);
    expect(left, `first nav link clipped off-screen on ${path}`).toBeGreaterThanOrEqual(0);
  }
});

test("mobile: nav row scrolls horizontally only, never vertically", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  for (const path of ["/", sectionPath]) {
    await page.goto(path);
    const m = await page
      .locator(".nav__list")
      .evaluate((n) => ({ v: n.scrollHeight - n.clientHeight, h: n.scrollWidth - n.clientWidth }));
    expect(m.v, `nav row vertically scrollable on ${path}`).toBeLessThanOrEqual(0);
    expect(m.h, `nav should overflow horizontally at 375px on ${path}`).toBeGreaterThan(0);
  }
});

// Sticky headers: home's navbar and inner pages' compact masthead must pin
// to the viewport top after a deep scroll — at BOTH mobile and desktop
// widths (sticky inside the wrong parent silently stops at the parent edge).
for (const [name, vp] of [["mobile", VIEWPORTS.mobile], ["desktop", VIEWPORTS.desktop]] as const) {
  test(`sticky headers pin to top on scroll @ ${name}`, async ({ page }) => {
    await page.setViewportSize(vp);
    const cases: Array<[string, string]> = [
      ["/", ".home-navbar"],
      [sectionPath, ".masthead--compact"],
      [articlePath, ".masthead--compact"],
    ];
    for (const [path, sel] of cases) {
      await page.goto(path);
      await page.evaluate(() => window.scrollTo(0, 2500));
      const box = await page.locator(sel).evaluate((n) => {
        const r = n.getBoundingClientRect();
        return { top: r.top, height: r.height };
      });
      expect(box.top, `${sel} not pinned at top on ${path} (${name})`).toBe(0);
      expect(box.height, `${sel} collapsed on ${path} (${name})`).toBeGreaterThan(20);
    }
  });
}

test("mobile: folio line fits — date and Lenz chip fully in viewport", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  await page.goto("/");
  const chip = await page.locator(".folio__chip").boundingBox();
  expect(chip!.x + chip!.width, "POWERED BY LENZ chip overflows the folio").toBeLessThanOrEqual(375);
});

test("mobile: wordmark is BS?-only on inner pages, full lockup on home", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  await page.goto(sectionPath);
  await expect(page.locator(".masthead--compact .wordmark__ink")).toBeHidden();
  await expect(page.locator(".masthead--compact .wordmark__mark")).toBeVisible();
  await page.goto("/");
  await expect(page.locator(".wordmark__ink")).toBeVisible();
});

test("light-only: a dark-mode OS still gets newsprint paper", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg, "body background flipped under a dark OS — light-only contract broken").toBe(
    "rgb(250, 247, 240)" // --paper #FAF7F0
  );
});

test("mobile: nav and footer links keep a usable touch-target height", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  await page.goto(sectionPath);
  const navH = await page.locator(".nav__list li a").first().evaluate((a) => a.getBoundingClientRect().height);
  expect(navH, "nav touch target collapsed").toBeGreaterThanOrEqual(40);
  const footH = await page.locator(".footer__col a").first().evaluate((a) => a.getBoundingClientRect().height);
  expect(footH, "footer touch target collapsed").toBeGreaterThanOrEqual(24);
});

test("desktop: home lead/rail grid holds (lead wider than rail)", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await page.goto("/");
  const lead = await page.locator(".home-top .lead__title").boundingBox();
  const rail = await page.locator(".home-top .rail").boundingBox();
  expect(lead!.width).toBeGreaterThan(rail!.width);
});

test("footer columns: one row on desktop, 2+1 on mobile", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.desktop);
  await page.goto("/");
  const desktopTops = await page
    .locator(".footer__col")
    .evaluateAll((cols) => cols.map((c) => Math.round(c.getBoundingClientRect().top)));
  expect(new Set(desktopTops).size, "footer columns not on one row at 1280").toBe(1);
  await page.setViewportSize(VIEWPORTS.mobile);
  await page.goto("/");
  // Sections + Site share a row (narrow lists fit side by side); the wide
  // disclosure column takes its own full-width row below.
  const mobileTops = await page
    .locator(".footer__col")
    .evaluateAll((cols) => cols.map((c) => Math.round(c.getBoundingClientRect().top)));
  expect(mobileTops[0], "Sections and Site should share a row at 375").toBe(mobileTops[1]);
  expect(mobileTops[2], "wide column should sit below the link lists").toBeGreaterThan(mobileTops[0]);
});

// --------------------------------------------------------------------------
// Hover-highlight symmetry — PIXEL-level, because box metrics lie: WebKit
// painted inline-box highlights flush-left while getBoundingClientRect
// reported perfect 6px padding on both sides.
// --------------------------------------------------------------------------
test("nav hover highlight has symmetric breathing room (pixel check)", async ({ page }) => {
  await page.setViewportSize(VIEWPORTS.mobile);
  await page.goto(sectionPath);
  const link = page.locator(".nav__list li:nth-child(2) a");
  await link.hover();
  const box = (await link.boundingBox())!;
  const shot = PNG.sync.read(
    await page.screenshot({ clip: { x: box.x, y: box.y, width: box.width, height: box.height } })
  );
  const scale = shot.width / box.width; // device pixel ratio of the shot
  const inkCols: number[] = [];
  const bgCols: number[] = [];
  for (let x = 0; x < shot.width; x++) {
    let ink = false;
    let bg = false;
    for (let y = 0; y < shot.height; y++) {
      const i = (shot.width * y + x) << 2;
      const [r, g, b] = [shot.data[i], shot.data[i + 1], shot.data[i + 2]];
      if (r + g + b < 300) ink = true; // dark glyph pixel
      if (r > 220 && g > 170 && b < 120) bg = true; // accent yellow
    }
    if (ink) inkCols.push(x);
    if (bg) bgCols.push(x);
  }
  expect(inkCols.length, "no text ink found in highlight box").toBeGreaterThan(0);
  expect(bgCols.length, "hover background did not paint").toBeGreaterThan(0);
  const leftGap = inkCols[0] - bgCols[0];
  const rightGap = bgCols[bgCols.length - 1] - inkCols[inkCols.length - 1];
  // ≤2 CSS px of asymmetry (glyph side-bearings + trailing letter-spacing).
  expect(
    Math.abs(leftGap - rightGap),
    `highlight asymmetric: left ${leftGap}px vs right ${rightGap}px (physical, scale ${scale})`
  ).toBeLessThanOrEqual(2 * scale);
  // And there IS breathing room at all (≥3 CSS px each side).
  expect(leftGap).toBeGreaterThanOrEqual(3 * scale);
  expect(rightGap).toBeGreaterThanOrEqual(3 * scale);
});

// --------------------------------------------------------------------------
// Behavioral: verdict filter actually hides cards ([hidden] must win).
// --------------------------------------------------------------------------
test("section verdict filter hides non-matching cards", async ({ page }) => {
  await page.goto(sectionPath);
  const chips = page.locator("[data-verdict-filter]:not([data-verdict-filter='all'])");
  const count = await chips.count();
  test.skip(count === 0, "no verdict chips on this section");
  // Click the first specific-verdict chip; every visible card must match it.
  const chip = chips.first();
  const verdict = await chip.getAttribute("data-verdict-filter");
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  const wrong = await page
    .locator(`[data-verdict]:not([data-verdict='${verdict}'])`)
    .evaluateAll((cards) => cards.filter((c) => c.offsetParent !== null && !c.hidden).length);
  expect(wrong, "cards with other verdicts still visible after filtering").toBe(0);
});

// --------------------------------------------------------------------------
// Search: Pagefind loads and returns results (skips on --skip-search builds).
// --------------------------------------------------------------------------
test("search returns results", async ({ page, request }) => {
  const probe = await request.get("/pagefind/pagefind-ui.js");
  test.skip(!probe.ok(), "dist built with --skip-search");
  await page.goto("/search/");
  await page.locator(".pagefind-ui__search-input").fill("the");
  await expect(page.locator(".pagefind-ui__result").first()).toBeVisible({ timeout: 10_000 });
});

// --------------------------------------------------------------------------
// Attribution CTAs: same voice (font/size), so the ↗ arrows match.
// --------------------------------------------------------------------------
test("attribution CTAs share the readlink font metrics", async ({ page }) => {
  await page.goto(articlePath);
  const metrics = await page.evaluate(() => {
    const style = (sel: string) => {
      const el = document.querySelector(sel)!;
      const s = getComputedStyle(el);
      return `${s.fontFamily}|${s.fontSize}|${s.textTransform}`;
    };
    return {
      readlink: style(".attribution .readlink"),
      verify: style(".attribution__cta--verify"),
      flag: style(".attribution__cta--flag"),
      discuss: style(".attribution__cta--discuss"),
    };
  });
  expect(metrics.verify).toBe(metrics.readlink);
  expect(metrics.flag).toBe(metrics.readlink);
  expect(metrics.discuss).toBe(metrics.readlink);
});
