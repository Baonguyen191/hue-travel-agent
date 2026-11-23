import { test as base, expect, type Page } from "@playwright/test";

/** Problems seen while a test ran: console errors, uncaught exceptions, failed API calls. */
export type Problems = string[];

function watch(page: Page, problems: Problems, allowStatus: (url: string, status: number) => boolean): void {
  page.on("console", (message) => {
    // "Failed to load resource" repeats a failed response without its URL; the listeners below report it.
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      problems.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    const url = decodeURIComponent(response.url());
    const method = response.request().method();
    // A new conversation has no history yet: the chat page expects this 404.
    if (method === "GET" && response.status() === 404 && /\/api\/v1\/chat\/[^/]+$/.test(url)) return;
    if (response.status() >= 400 && !allowStatus(url, response.status())) {
      problems.push(`http ${response.status()}: ${response.request().method()} ${url}`);
    }
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    // Map tiles and image loads aborted by navigation are not app failures.
    if (url.includes("tile.openstreetmap") || request.failure()?.errorText === "net::ERR_ABORTED") return;
    problems.push(`requestfailed: ${url} ${request.failure()?.errorText ?? ""}`);
  });
}

/** Fails if the page scrolls sideways: the layout must fit the viewport. */
export async function expectNoHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "page scrolls horizontally").toBeLessThanOrEqual(1);
}

/** Fails if a visible photo never loaded (broken image). */
export async function expectNoBrokenImages(page: Page): Promise<void> {
  const broken = await page.evaluate(() =>
    Array.from(document.images)
      .filter((img) => img.complete && img.naturalWidth === 0 && img.getBoundingClientRect().width > 0)
      .map((img) => img.currentSrc || img.src),
  );
  expect(broken, "broken images").toEqual([]);
}

type AllowStatus = { allow: (url: string, status: number) => boolean };
type Fixtures = { problems: Problems; allowStatus: AllowStatus };

export const test = base.extend<Fixtures>({
  // Wrapped in an object: Playwright would treat a bare function value as a fixture body.
  allowStatus: [{ allow: () => false }, { option: true }],
  problems: [
    async ({ page, allowStatus }, use) => {
      const problems: Problems = [];
      watch(page, problems, allowStatus.allow);
      await use(problems);
      expect(problems, "console errors or failed API calls").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
