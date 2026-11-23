import type { Page } from "@playwright/test";
import { expect, expectNoHorizontalScroll, test } from "./fixtures";

// Needs the backend with a local Ollama (qwen3.5:4b), as the app does. Each turn takes a few seconds.

const bot = (page: Page) => page.getByRole("article", { name: "Trợ lý" });

/** Sends one message and returns the text of the bot reply it produced. */
async function say(page: Page, text: string): Promise<string> {
  const before = await bot(page).count();
  const box = page.getByPlaceholder(/Tôi đi Huế 3 ngày 2 đêm/);
  await box.fill(text);
  await box.press("Enter");
  await expect(bot(page)).toHaveCount(before + 1, { timeout: 90_000 });
  return (await bot(page).last().innerText()).replace(/\s+/g, " ");
}

async function press(page: Page, name: string): Promise<string> {
  const before = await bot(page).count();
  await page.getByRole("button", { name, exact: true }).last().click();
  await expect(bot(page)).toHaveCount(before + 1, { timeout: 90_000 });
  return (await bot(page).last().innerText()).replace(/\s+/g, " ");
}

test.describe("chat @mobile", () => {
  test("asks until the trip is fully specified, two questions at a time, no buttons", async ({ page }) => {
    await page.goto("/");
    let reply = await say(page, "cho tôi plan đi Huế 3 ngày 2 đêm");
    expect(reply).toContain("từ ngày nào");
    expect(reply).toContain("xuất phát từ đâu");
    expect(reply).not.toContain("mấy ngày");
    await expect(bot(page).last().getByRole("button")).toHaveCount(0);

    reply = await say(page, "Thứ 7 tới, từ Hà Nội");
    expect(reply).toContain("Mình ghi nhận");
    expect(reply).toContain("Hà Nội → Huế");
    expect(reply).toContain("mấy người");
    expect(reply).toContain("Ngân sách");
    expect(reply).not.toContain("Lịch trình 3 ngày");
    await expect(bot(page).last().getByRole("button")).toHaveCount(0);

    reply = await say(page, "2 người, 6 triệu");
    expect(reply).toContain("thích gì");
    // Optional questions wait until every required one is answered, so they are never lost.
    expect(reply).not.toContain("đi Huế bằng gì");

    reply = await say(page, "thích ẩm thực và thiên nhiên, đi xe giường nằm");
    expect(reply).toContain("ở đâu");
    expect(reply).toContain("thong thả");
    expect(reply).not.toContain("bằng gì"); // transport was answered

    reply = await say(page, "homestay, thong thả");
    expect(reply).toContain("muốn đến hoặc muốn tránh");

    reply = await say(page, "không");
    expect(reply).toContain("Mình tóm tắt lại chuyến đi");
    expect(reply).toContain("Nhịp độ: thong thả");
    expect(reply).not.toContain("Lịch trình 3 ngày");
    await expect(bot(page).last().getByRole("button")).toHaveCount(0); // text only, no buttons

    reply = await say(page, "thêm số lượng điểm đến, 3 điểm hơi ít");
    expect(reply).toContain("Nhịp độ: vừa phải");
    expect(reply).toContain("← đã đổi");
    expect(reply).not.toContain("Lịch trình 3 ngày");

    reply = await say(page, "ok");
    expect(reply).toContain("Lịch trình 3 ngày");
    await expect(bot(page).last().getByRole("region", { name: "Lịch trình" })).toBeVisible();
    await expectNoHorizontalScroll(page);
  });

  test("a bare answer like 'ngày mai' continues the plan, not a greeting", async ({ page }) => {
    await page.goto("/");
    let reply = await say(page, "xin chào");
    expect(reply).toContain("trợ lý lập lịch du lịch Huế");

    reply = await say(page, "tôi muốn đi Huế 3 ngày 2 đêm với người yêu");
    expect(reply).toContain("từ ngày nào");
    expect(reply).not.toContain("mấy người"); // "với người yêu" already means two people

    reply = await say(page, "ngày mai");
    expect(reply).not.toContain("Chào bạn");
    expect(reply).toContain("xuất phát từ đâu");
    expect(reply).not.toContain("mấy người");

    reply = await say(page, "từ Đà Nẵng, khoảng 6 triệu");
    expect(reply).toContain("thích gì");

    reply = await say(page, "ẩm thực, tùy");
    reply = await say(page, "tùy");
    // The cheapest option is over 6 triệu, so the budget check is asked alone before the rest.
    if (reply.includes("vượt ngân sách")) reply = await say(page, "giữ");
    expect(reply).toContain("muốn đến hoặc muốn tránh");
    reply = await say(page, "không");
    expect(reply).toContain("Mình tóm tắt lại chuyến đi");
    reply = await say(page, "ok");
    expect(reply).toContain("Lịch trình 3 ngày");
  });

  test("warns before planning when the cheapest option is over budget", async ({ page }) => {
    await page.goto("/");
    let reply = await say(
      page,
      "Tôi đi Huế 3 ngày 2 đêm từ 05/12/2026, xuất phát Hà Nội, 2 người, ngân sách 3 triệu, thích ẩm thực, đi xe giường nằm, ở homestay, lịch vừa phải",
    );
    expect(reply).toContain("vượt ngân sách");
    expect(reply).toContain("tăng ngân sách");
    expect(reply).not.toContain("Lịch trình 3 ngày");
    await expect(bot(page).last().getByRole("button")).toHaveCount(0);

    expect(reply).not.toContain("muốn đến hoặc muốn tránh"); // the budget question is asked alone

    reply = await say(page, "giữ");
    expect(reply).toContain("muốn đến hoặc muốn tránh");
    reply = await say(page, "không");
    expect(reply).toContain("chọn phương án tiết kiệm nhất");
    reply = await say(page, "ok");
    expect(reply).toContain("Lịch trình 3 ngày");
  });

  test("the guide describes a place from Wikipedia, with its source", async ({ page }) => {
    await page.goto("/");
    const reply = await say(page, "Sông Hương có gì hay?");
    expect(reply).toContain("Sông Hương");
    expect(reply).toContain("Nguồn: Wikipedia tiếng Việt");
    expect(reply).not.toMatch(/[㐀-鿿]/); // no Han characters in the answer
  });

  test("small talk gets a friendly answer, not a refusal", async ({ page }) => {
    await page.goto("/");
    let reply = await say(page, "xin chào");
    expect(reply).toContain("trợ lý lập lịch du lịch Huế");
    expect(reply).not.toContain("Xin lỗi");
    await expect(bot(page).last().getByRole("button")).toHaveCount(0);

    reply = await say(page, "bạn là ai?");
    expect(reply).toContain("MÔ PHỎNG");

    reply = await say(page, "cảm ơn bạn");
    expect(reply).toContain("Không có gì");

    reply = await say(page, "Huế mai có mưa không?");
    expect(reply).toContain("chưa có dữ liệu thời tiết");
  });

  test("edits a plan, approves and books in chat", async ({ page }) => {
    await page.goto("/");
    let reply = await say(
      page,
      "Tôi đi Huế 3 ngày 2 đêm từ 05/12/2026, xuất phát Hà Nội, 2 người, ngân sách 8 triệu, thích di tích và chùa, đi xe giường nằm, ở homestay, lịch vừa phải",
    );
    expect(reply).toContain("muốn đến hoặc muốn tránh"); // the only unsettled question
    reply = await say(page, "không");
    expect(reply).toContain("Mình tóm tắt lại chuyến đi");
    reply = await say(page, "ok");
    expect(reply).toContain("version 1");

    reply = await say(page, "Đổi thành 4 người");
    expect(reply).toContain("đổi số người thành 4");
    expect(reply).toContain("version 2");

    reply = await say(page, "Bỏ chùa ra khỏi lịch");
    expect(reply).toContain("version 3");
    const itinerary = bot(page).last().getByRole("region", { name: "Lịch trình" });
    await expect(itinerary).not.toContainText("Chùa");

    reply = await press(page, "Duyệt Tiết kiệm");
    expect(reply).toContain("version 3");
    reply = await press(page, "Xác nhận");
    expect(reply).toMatch(/đã duyệt/i);

    reply = await press(page, "Đặt vé và khách sạn");
    reply = await press(page, "Xác nhận");
    await expect(bot(page).last().getByRole("region", { name: "Kết quả đặt chỗ" })).toBeVisible();
    await expect(bot(page).last()).toContainText("MÔ PHỎNG");
  });
});
