import type { Page } from "@playwright/test";
import { expect, expectNoBrokenImages, expectNoHorizontalScroll, test } from "./fixtures";

const SENTENCE =
  "Tôi đi Huế 3 ngày 2 đêm từ 05/12/2026, xuất phát Hà Nội, 2 người, ngân sách 8 triệu, thích di tích và đặc sản";

async function createPlan(page: Page): Promise<string> {
  await page.goto("/form");
  await page.getByLabel("Yêu cầu của bạn").fill(SENTENCE);
  await page.getByRole("button", { name: "Phân tích yêu cầu" }).click();
  await expect(page.getByText("Nguồn phân tích")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel("Điểm xuất phát")).toHaveValue("Hà Nội");
  await expect(page.getByLabel("Số người")).toHaveValue("2");
  await page.getByRole("button", { name: "Tạo lịch trình" }).click();
  await page.waitForURL(/\/plan\/[^/]+$/, { timeout: 120_000 });
  return page.url().split("/plan/")[1];
}

const tabs = (page: Page) => page.getByRole("navigation", { name: "Các mục kế hoạch" });

test.describe("transport and stay choices", () => {
  test("'đi tàu, ở resort' prices the train and the resort", async ({ page }) => {
    await page.goto("/form");
    await page
      .getByLabel("Yêu cầu của bạn")
      .fill("Tôi đi Huế 3 ngày 2 đêm từ 05/12/2026, xuất phát Hà Nội, 2 người, ngân sách 15 triệu, đi tàu, ở resort");
    await page.getByRole("button", { name: "Phân tích yêu cầu" }).click();
    await expect(page.getByText("Nguồn phân tích")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "Tạo lịch trình" }).click();
    await page.waitForURL(/\/plan\/[^/]+$/, { timeout: 120_000 });

    await tabs(page).getByRole("link", { name: /Ngân sách/ }).click();
    const table = page.getByRole("table", { name: "Các phương án ngân sách" });
    await expect(table).toContainText("Reunification Train Demo");
    await expect(table).toContainText("Perfume River Demo Resort");
    await expect(table).not.toContainText("Hue Sleeper Bus Demo");
    await expect(table).not.toContainText("Old Quarter Homestay Demo");
  });
});

test.describe("trip from the form @mobile", () => {
  test("parse, plan, approve, book once even when pressed twice", async ({ page }) => {
    const threadId = await createPlan(page);
    await expect(page.getByRole("heading", { level: 1, name: "Hà Nội → Huế" })).toBeVisible();
    await expect(page.getByText("Chờ duyệt")).toBeVisible();

    // Itinerary: three days, each with a map.
    const days = page.getByRole("tablist", { name: "Chọn ngày" }).getByRole("tab");
    await expect(days).toHaveCount(3);
    for (let day = 0; day < 3; day += 1) {
      await days.nth(day).click();
      await expect(days.nth(day)).toHaveAttribute("aria-selected", "true");
      await expect(page.getByRole("region", { name: "Bản đồ ngày đã chọn" })).toBeVisible();
    }
    await expectNoHorizontalScroll(page);

    // Booking is refused before approval.
    await tabs(page).getByRole("link", { name: "Đặt chỗ" }).click();
    await expect(page.getByRole("button", { name: "Đặt MÔ PHỎNG" })).toBeDisabled();
    await expect(page.getByText("Chỉ đặt được sau khi phương án đã được duyệt.")).toBeVisible();

    // Approve the budget option.
    await tabs(page).getByRole("link", { name: /Ngân sách/ }).click();
    await expectNoHorizontalScroll(page);
    await page.getByRole("button", { name: "Duyệt Tiết kiệm" }).filter({ visible: true }).click();
    await expect(page.getByText(/Đã duyệt phương án Tiết kiệm/)).toBeVisible();

    // Book: a second press sends the same idempotency key.
    await tabs(page).getByRole("link", { name: "Đặt chỗ" }).click();
    const bookCalls: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith(`/plans/${threadId}/book`)) {
        bookCalls.push(request.postData() ?? "");
      }
    });
    const book = page.getByRole("button", { name: "Đặt MÔ PHỎNG" });
    await expect(book).toBeEnabled();
    await book.click();
    await expect(page.getByRole("heading", { name: "Kết quả đặt chỗ" })).toBeVisible();
    await expect(page.getByText(/MOCK-/).filter({ visible: true }).first()).toBeVisible();
    await book.click();
    await expect(book).toBeEnabled();
    expect(bookCalls).toHaveLength(2);
    expect(bookCalls[0]).toEqual(bookCalls[1]);
    await expectNoBrokenImages(page);
    await expectNoHorizontalScroll(page);
  });
});
