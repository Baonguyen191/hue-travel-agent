import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import approveJson from "../test/fixtures/approve.json";
import planApprovedJson from "../test/fixtures/plan-approved.json";
import planJson from "../test/fixtures/plan.json";

const THREAD = "e3d7c6b9-956b-42f7-9916-479fe993c969";

function jsonReply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

function renderBudget(plan: unknown, approveReply: () => Response = () => jsonReply(200, approveJson), afterApprove: unknown = planApprovedJson) {
  let current = plan;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST" && url.endsWith("/approve")) {
      const reply = approveReply();
      if (reply.ok) current = afterApprove;
      return reply;
    }
    return jsonReply(200, current);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter initialEntries={[`/plan/${THREAD}/budget`]}>
      <App />
    </MemoryRouter>,
  );
  return fetchMock;
}

function withOverBudget(plan: typeof planJson, shortfall: number) {
  return {
    ...plan,
    payload: {
      ...plan.payload,
      budget: {
        ...plan.payload.budget,
        shortfall_vnd: shortfall,
        options: plan.payload.budget.options.map((option) => ({
          ...option,
          budget_status: "OVER_BUDGET",
          budget_remaining_vnd: -shortfall,
          warnings: ["Ước tính vượt ngân sách."],
        })),
      },
    },
  };
}

describe("budget tab", () => {
  it("lists every option, approves only the labelled one and keeps the others for comparison", async () => {
    renderBudget(planJson);

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(planJson.payload.budget.options.length);
    expect(screen.getAllByRole("button", { name: /^Duyệt / })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Duyệt Tiết kiệm" })).toBeInTheDocument();
    expect(screen.getAllByText("chưa có nhãn").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Không thể duyệt").length).toBeGreaterThan(0);
  });

  it("tags cost items with their source, and marks mock items as simulated", async () => {
    renderBudget(planJson);
    await screen.findByRole("table");

    expect(screen.getAllByText("MOCK · MÔ PHỎNG").length).toBeGreaterThan(0);
    expect(screen.getAllByText("DATA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ƯỚC TÍNH").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CHƯA RÕ").length).toBeGreaterThan(0);
  });

  it("approves the labelled option with the plan version and then shows the quote", async () => {
    const fetchMock = renderBudget(planJson);
    await userEvent.click(await screen.findByRole("button", { name: "Duyệt Tiết kiệm" }));

    expect(await screen.findByRole("heading", { name: "Đã duyệt phương án Tiết kiệm" })).toBeInTheDocument();
    expect(screen.getByText(/mã báo giá/)).toHaveTextContent(approveJson.quote_hash.slice(0, 16));
    expect(screen.queryByRole("button", { name: /^Duyệt / })).not.toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST") as [string, RequestInit];
    expect(JSON.parse(post[1].body as string)).toEqual({ version: planJson.version, option: "BUDGET" });
  });

  it("asks the user to reload when the plan version has moved on (409)", async () => {
    renderBudget(planJson, () => jsonReply(409, { detail: "Plan version is stale; approve the latest version." }));
    await userEvent.click(await screen.findByRole("button", { name: "Duyệt Tiết kiệm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Kế hoạch đã có phiên bản mới — tải lại để xem.");
    expect(screen.getByRole("button", { name: "Tải lại kế hoạch" })).toBeInTheDocument();
  });

  it("shows the shortfall banner with the amount and every option warning when nothing fits", async () => {
    renderBudget(withOverBudget(planJson, 500000));

    expect(await screen.findByRole("heading", { name: "Không phương án nào nằm trong ngân sách" })).toBeInTheDocument();
    expect(screen.getByText("Thiếu 500.000 ₫ so với ngân sách 8.000.000 ₫.")).toBeInTheDocument();
    expect(screen.getAllByText("Ước tính vượt ngân sách.").length).toBeGreaterThan(0);
  });

  it("shows an approved plan with its selected offers and no approve buttons", async () => {
    renderBudget(planApprovedJson);

    expect(await screen.findByRole("heading", { name: "Đã duyệt phương án Tiết kiệm" })).toBeInTheDocument();
    expect(screen.getAllByText(/Hue Sleeper Bus Demo/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Duyệt / })).not.toBeInTheDocument();
  });
});
