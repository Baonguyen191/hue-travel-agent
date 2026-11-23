import { expect, expectNoBrokenImages, expectNoHorizontalScroll, test } from "./fixtures";

const SHOTS = "e2e/.results/shots";

test.describe("pages @mobile", () => {
  test("chat welcome", async ({ page }, info) => {
    await page.goto("/");
    await expect(page.getByPlaceholder(/Tôi đi Huế 3 ngày 2 đêm/)).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoBrokenImages(page);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-chat.png`, fullPage: true });
  });

  test("explore: list, category filter, search without accents", async ({ page }, info) => {
    await page.goto("/explore");
    const results = page.getByLabel("Kết quả");
    await expect(results.getByRole("link").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoBrokenImages(page);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-explore.png`, fullPage: true });

    await page.getByRole("group", { name: "Loại địa điểm" }).getByRole("button", { name: /Cà phê/ }).click();
    await page.waitForLoadState("networkidle");
    await expect(results.getByRole("link").first()).toBeVisible();
    await expectNoBrokenImages(page);

    await page.getByPlaceholder("ví dụ: đại nội, chợ đông ba").fill("dai noi");
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-explore-search.png`, fullPage: true });
  });

  test("place detail with source photo", async ({ page }, info) => {
    await page.goto("/explore/huetripo:192068");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Thiên An");
    await page.waitForLoadState("networkidle");
    await expectNoBrokenImages(page);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-detail.png`, fullPage: true });
  });

  test("place detail shows the Wikipedia introduction with its source", async ({ page }, info) => {
    await page.goto("/explore/huetripo:512284"); // Sông Hương
    const intro = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Giới thiệu", exact: true }) })
      .first();
    await expect(intro).toContainText("Wikipedia tiếng Việt");
    // "Giới thiệu" is a closed <details>: open it so its link is visible to role queries.
    await intro.locator("summary").click();
    await expect(intro.getByRole("link", { name: "bài gốc" })).toHaveAttribute("href", /vi\.wikipedia\.org/);
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-guide.png`, fullPage: true });
  });

  test("request form", async ({ page }, info) => {
    await page.goto("/form");
    await expect(page.getByLabel("Điểm xuất phát")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: `${SHOTS}/${info.project.name}-form.png`, fullPage: true });
  });

  test("unknown route shows 404 page", async ({ page }) => {
    await page.goto("/khong-co-trang-nay");
    await expect(page.getByRole("heading", { name: "Không tìm thấy trang" })).toBeVisible();
  });
});

test.describe("missing resources", () => {
  test.use({ allowStatus: { allow: (url, status) => status === 404 && /huetripo:0000000|plans\/no-such/.test(url) } });

  test("unknown place shows a not-found message", async ({ page }) => {
    await page.goto("/explore/huetripo:0000000");
    await expect(page.getByText(/Không tìm thấy/).first()).toBeVisible();
  });

  test("unknown plan shows a not-found message", async ({ page }) => {
    await page.goto("/plan/no-such-thread");
    await expect(page.getByRole("heading", { name: "Không tìm thấy kế hoạch" })).toBeVisible();
  });
});
