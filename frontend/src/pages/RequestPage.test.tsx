import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import createPlanJson from "../test/fixtures/create-plan.json";
import parseDodJson from "../test/fixtures/parse-dod.json";
import parseMissingJson from "../test/fixtures/parse-missing.json";
import { calledUrls, routeFetch, type RouteReply } from "../test/fetchMock";
import { DOD_SENTENCE, RequestPage } from "./RequestPage";

const UUID_PLAN = /\/api\/v1\/plans\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** Stands in for the plan page: only proves the navigation and the thread id. */
function PlanRouteProbe() {
  const { threadId } = useParams();
  return <p>Mã kế hoạch: {threadId}</p>;
}

function renderApp() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<RequestPage />} />
        <Route path="/plan/:threadId" element={<PlanRouteProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Parse replies come from the parse fixture; any other URL is the plan creation. */
function replies(parse: unknown, create: RouteReply) {
  return (url: string): RouteReply => (url.endsWith("/plans/parse") ? { body: parse } : create);
}

async function parseText(text: string) {
  await userEvent.type(screen.getByLabelText("Yêu cầu của bạn"), text);
  await userEvent.click(screen.getByRole("button", { name: "Phân tích yêu cầu" }));
}

describe("RequestPage", () => {
  beforeEach(() => {
    window.localStorage.setItem("hue.userId", "tester-0002");
  });

  it("offers the DoD sentence as the placeholder and keeps parse disabled until there is text", async () => {
    renderApp();

    expect(screen.getByLabelText("Yêu cầu của bạn")).toHaveAttribute("placeholder", DOD_SENTENCE);
    expect(screen.getByRole("button", { name: "Phân tích yêu cầu" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Yêu cầu của bạn"), "Đi Huế");
    expect(screen.getByRole("button", { name: "Phân tích yêu cầu" })).toBeEnabled();
  });

  it("parses the sentence and prefills the form from the parsed request", async () => {
    const fetchMock = routeFetch(replies(parseDodJson, { body: createPlanJson }));
    renderApp();

    await parseText(DOD_SENTENCE);

    expect(await screen.findByLabelText("Điểm xuất phát")).toHaveValue("Hà Nội");
    expect(screen.getByLabelText("Ngân sách (VND)")).toHaveValue(8000000);
    expect(screen.getByText("Phân tích bằng quy tắc tiếng Việt")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sở thích đã chọn" })).toHaveTextContent("di tích");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ text: DOD_SENTENCE });
  });

  it("highlights what the parser could not find and keeps submit disabled", async () => {
    routeFetch(replies(parseMissingJson, { body: createPlanJson }));
    renderApp();

    await parseText("Tôi muốn đi Huế vào tháng sau, 2 người");

    expect(await screen.findByText("Nhập điểm xuất phát.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeDisabled();
    expect(screen.getByLabelText("Số người")).toHaveValue(2);
  });

  it("creates the plan under a new thread id and opens the plan page", async () => {
    const fetchMock = routeFetch(replies(parseDodJson, { body: createPlanJson }));
    renderApp();
    await parseText(DOD_SENTENCE);
    await screen.findByLabelText("Điểm xuất phát");

    await userEvent.click(screen.getByRole("button", { name: "Tạo lịch trình" }));

    expect(await screen.findByText(/Mã kế hoạch:/)).toBeInTheDocument();
    const planCall = calledUrls(fetchMock).find((url) => UUID_PLAN.test(url));
    expect(planCall).toBeDefined();
    const threadId = planCall!.split("/").pop()!;
    expect(screen.getByText(new RegExp(threadId))).toBeInTheDocument();

    const [, init] = fetchMock.mock.calls.find(([url]) => UUID_PLAN.test(String(url))) as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toMatchObject({
      origin: "Hà Nội",
      destination: "Huế",
      start_date: "2026-12-05",
      end_date: "2026-12-07",
      people: 2,
      budget_vnd: 8000000,
    });
  });

  it("shows the progress steps while the plan is being built", async () => {
    let release: ((reply: Response) => void) | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith("/plans/parse")) {
          return new Response(JSON.stringify(parseDodJson), { status: 200 });
        }
        return new Promise<Response>((resolve) => {
          release = resolve;
        });
      }),
    );
    renderApp();
    await parseText(DOD_SENTENCE);
    await screen.findByLabelText("Điểm xuất phát");

    await userEvent.click(screen.getByRole("button", { name: "Tạo lịch trình" }));

    const progress = await screen.findByRole("status");
    expect(within(progress).getByText("Đang tạo lịch trình…")).toBeInTheDocument();
    for (const label of [
      "Tìm địa điểm và phương tiện",
      "Xếp lịch trình theo ngày",
      "Tính ngân sách các phương án",
      "Kiểm tra lịch trình",
      "Lưu phiên bản chờ duyệt",
    ]) {
      expect(within(progress).getByText(label)).toBeInTheDocument();
    }
    release?.(new Response(JSON.stringify(createPlanJson), { status: 200 }));
    expect(await screen.findByText(/Mã kế hoạch:/)).toBeInTheDocument();
  });

  it("stays on the form and lists the reasons when validation fails", async () => {
    const failed = {
      ...createPlanJson,
      status: "FAILED_VALIDATION",
      plan_id: null,
      version: null,
      options: [],
      warnings: [],
      trace: ["search", "itinerary", "budget", "validate", "itinerary", "budget", "validate", "failed"],
      retries: 3,
      attempts: ["no budget option", "no budget option"],
      approval: null,
      waiting: false,
    };
    routeFetch(replies(parseDodJson, { body: failed }));
    renderApp();
    await parseText(DOD_SENTENCE);
    await screen.findByLabelText("Điểm xuất phát");

    await userEvent.click(screen.getByRole("button", { name: "Tạo lịch trình" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Chưa tạo được lịch trình hợp lệ")).toBeInTheDocument();
    expect(within(alert).getAllByText("no budget option")).toHaveLength(2);
    expect(within(alert).getByRole("list", { name: "Các bước đã chạy" })).toHaveTextContent("Dừng vì chưa đạt yêu cầu");
    expect(screen.getByLabelText("Điểm xuất phát")).toBeInTheDocument();
    expect(screen.queryByText(/Mã kế hoạch:/)).not.toBeInTheDocument();
  });

  it("shows the API detail when creating the plan fails", async () => {
    routeFetch(
      replies(parseDodJson, {
        status: 422,
        body: { detail: [{ type: "value_error", loc: ["body"], msg: "Value error, end_date must be after start_date" }] },
      }),
    );
    renderApp();
    await parseText(DOD_SENTENCE);
    await screen.findByLabelText("Điểm xuất phát");

    await userEvent.click(screen.getByRole("button", { name: "Tạo lịch trình" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Value error, end_date must be after start_date"),
    );
    expect(screen.getByLabelText("Điểm xuất phát")).toBeInTheDocument();
  });

  it("shows a parse failure without losing the typed text", async () => {
    routeFetch(() => ({ status: 500, body: { detail: "Parser đang bảo trì." } }));
    renderApp();

    await parseText("Đi Huế");

    expect(await screen.findByRole("alert")).toHaveTextContent("Parser đang bảo trì.");
    expect(screen.getByLabelText("Yêu cầu của bạn")).toHaveValue("Đi Huế");
  });
});
