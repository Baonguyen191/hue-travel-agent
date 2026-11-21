import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { saveStoredResult } from "../lib/booking";
import bookJson from "../test/fixtures/book.json";
import planApprovedJson from "../test/fixtures/plan-approved.json";
import planJson from "../test/fixtures/plan.json";
import type { BookingResult } from "../api/types";

function jsonReply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

function renderBooking(plan: unknown, bookBody: unknown = bookJson) {
  const threadId = (plan as { thread_id: string }).thread_id;
  const posts: RequestInit[] = [];
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts.push(init);
      return jsonReply(200, bookBody);
    }
    return jsonReply(200, plan);
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = render(
    <MemoryRouter initialEntries={[`/plan/${threadId}/booking`]}>
      <App />
    </MemoryRouter>,
  );
  return { ...view, posts, threadId };
}

const approvedThread = planApprovedJson.thread_id;

describe("booking tab", () => {
  it("keeps booking disabled until the plan is approved, and says why", async () => {
    renderBooking(planJson);

    const button = await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Chỉ đặt được sau khi phương án đã được duyệt.");
    expect(screen.getByText("Chỉ đặt được sau khi phương án đã được duyệt.")).toBeInTheDocument();
  });

  it("books the approved plan once and shows the simulated references and contacts", async () => {
    const { posts } = renderBooking(planApprovedJson);
    await userEvent.click(await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" }));

    const result = await screen.findByRole("heading", { name: "Kết quả đặt chỗ" });
    const section = result.closest("section")!;
    expect(within(section).getAllByText("Đã đặt (MÔ PHỎNG)").length).toBeGreaterThan(0);
    expect(within(section).getByText("MOCK-b70cf864-mock-transport-outbound-standard")).toBeInTheDocument();
    expect(within(section).getAllByText("MÔ PHỎNG").length).toBeGreaterThan(0);

    expect(screen.getByRole("heading", { name: "Tự liên hệ với các điểm đến" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "0234 3523 237 - Đơn vị quản lý (Trung tâm Bảo tồn Di tích Cố đô Huế)" })).toHaveAttribute(
      "href",
      expect.stringContaining("tel:0234"),
    );
    expect(screen.getAllByText("Đại Nội Huế").length).toBeGreaterThan(0);
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0].body as string).idempotency_key.length).toBeGreaterThanOrEqual(8);
  });

  it("reuses the same idempotency key on a repeat click", async () => {
    const { posts } = renderBooking(planApprovedJson);
    const button = await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" });

    await userEvent.click(button);
    await screen.findByRole("heading", { name: "Kết quả đặt chỗ" });
    await userEvent.click(button);
    await screen.findByRole("heading", { name: "Kết quả đặt chỗ" });

    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[1].body as string)).toEqual(JSON.parse(posts[0].body as string));
  });

  it("restores the last result after a reload without booking again", async () => {
    const first = renderBooking(planApprovedJson);
    await userEvent.click(await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" }));
    await screen.findByRole("heading", { name: "Kết quả đặt chỗ" });
    first.unmount();

    const second = renderBooking(planApprovedJson);

    expect(await screen.findByRole("heading", { name: "Kết quả đặt chỗ" })).toBeInTheDocument();
    expect(second.posts).toHaveLength(0);
  });

  it("re-checks an unknown result with the same key and shows the new status", async () => {
    const unknown = {
      ...bookJson,
      status: "UNKNOWN",
      items: bookJson.items.map((item, index) => (index === 0 ? { ...item, status: "UNKNOWN" } : item)),
    };
    const { posts } = renderBooking(planApprovedJson, unknown);
    await userEvent.click(await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" }));
    await screen.findByRole("heading", { name: "Kết quả đặt chỗ" });

    expect(screen.getAllByText("Chưa rõ, cần kiểm tra lại").length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra lại trạng thái" }));

    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[1].body as string)).toEqual(JSON.parse(posts[0].body as string));
  });

  it("does not show a stored result that belongs to a different quote", async () => {
    const other: BookingResult = { ...(bookJson as unknown as BookingResult), quote_hash: "an-older-quote" };
    saveStoredResult(approvedThread, other);
    renderBooking(planApprovedJson);

    expect(await screen.findByRole("button", { name: "Đặt MÔ PHỎNG" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: "Kết quả đặt chỗ" })).not.toBeInTheDocument();
  });
});
