import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import createPlanJson from "../test/fixtures/create-plan.json";
import planApprovedJson from "../test/fixtures/plan-approved.json";
import planJson from "../test/fixtures/plan.json";
import { routeFetch } from "../test/fetchMock";

const THREAD = "e3d7c6b9-956b-42f7-9916-479fe993c969";
const PLAN_URL = `/api/v1/plans/${THREAD}`;

function renderPlan(path = `/plan/${THREAD}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

function jsonReply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8" } });
}

describe("plan page", () => {
  beforeEach(() => {
    window.localStorage.setItem("hue.userId", "tester-0003");
  });

  it("shows the waiting status, the warnings panel and the itinerary timeline", async () => {
    routeFetch(() => ({ body: planJson }));
    renderPlan();

    expect(await screen.findByRole("heading", { level: 1, name: "Hà Nội → Huế" })).toBeInTheDocument();
    expect(screen.getByText("Chờ duyệt")).toBeInTheDocument();
    expect(screen.getByText("Phiên bản v1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sửa yêu cầu" })).toBeInTheDocument();

    const warnings = screen.getByRole("region", { name: "Cảnh báo và kiểm tra" });
    expect(within(warnings).getByText("Kiểm tra lịch trình: đạt")).toBeInTheDocument();
    expect(within(warnings).getByText(/Loại trừ: 3 địa điểm/)).toBeInTheDocument();

    expect(screen.getAllByRole("tab")).toHaveLength(planJson.payload.itinerary.days.length);
    expect(screen.getByRole("link", { name: "Đại Nội Huế" })).toHaveAttribute("href", "/explore/huetripo%3A531787");
    expect(screen.getByText("Bữa trưa")).toBeInTheDocument();
    expect(screen.queryByText("Travel buffer")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Bản đồ ngày đã chọn" })).toBeInTheDocument();
  });

  it("switches days from the day tabs", async () => {
    routeFetch(() => ({ body: planJson }));
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    const tabs = screen.getAllByRole("tab");
    await userEvent.click(tabs[1]);

    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(tabs[0]).toHaveAttribute("aria-selected", "false");
  });

  it("edits the request while waiting, creates a new version and reloads the plan", async () => {
    const newVersion = { ...createPlanJson, version: 2 };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "POST" ? jsonReply(200, newVersion) : jsonReply(200, planJson),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPlan();
    await screen.findByRole("heading", { level: 1 });

    await userEvent.click(screen.getByRole("button", { name: "Sửa yêu cầu" }));
    const people = screen.getByLabelText("Số người");
    expect(people).toHaveValue(2);
    await userEvent.clear(people);
    await userEvent.type(people, "3");
    await userEvent.click(screen.getByRole("button", { name: "Lưu và tạo phiên bản mới" }));

    expect(await screen.findByText("Đã tạo phiên bản 2. Hãy duyệt lại phương án.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST") as [string, RequestInit];
    expect(post[0]).toBe(PLAN_URL);
    expect(JSON.parse(post[1].body as string)).toMatchObject({ people: 3, origin: "Hà Nội", destination: "Huế" });
    // Initial load plus the reload after the edit.
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "GET")).toHaveLength(2));
  });

  it("shows an approved plan with no edit action", async () => {
    routeFetch(() => ({ body: planApprovedJson }));
    renderPlan();

    expect(await screen.findByText("Đã duyệt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sửa yêu cầu" })).not.toBeInTheDocument();
  });

  it("says the plan belongs to another user on 403", async () => {
    routeFetch(() => ({ status: 403, body: { detail: "Plan belongs to another user." } }));
    renderPlan();

    expect(await screen.findByRole("heading", { name: "Kế hoạch thuộc người dùng khác" })).toBeInTheDocument();
  });

  it("says the plan was not found on 404", async () => {
    routeFetch(() => ({ status: 404, body: { detail: "Plan thread was not found." } }));
    renderPlan("/plan/00000000-0000-4000-8000-000000000000");

    expect(await screen.findByRole("heading", { name: "Không tìm thấy kế hoạch" })).toBeInTheDocument();
  });
});
