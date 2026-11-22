import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CHAT_ID_KEY } from "../lib/chat";
import chatHistoryFixture from "../test/fixtures/chat/chat-history.json";
import chatBookAsk from "../test/fixtures/chat/chat-05-book-ask.json";
import chatBookDone from "../test/fixtures/chat/chat-06-book-done.json";
import chatApproveAsk from "../test/fixtures/chat/chat-03-approve-ask.json";
import chatApproveDone from "../test/fixtures/chat/chat-04-approve-done.json";
import chatClarify1 from "../test/fixtures/chat/chat-clarify-1.json";
import chatClarify2 from "../test/fixtures/chat/chat-clarify-2.json";
import chatPlaceFixture from "../test/fixtures/chat/chat-02-place.json";
import chatPlanFixture from "../test/fixtures/chat/chat-01-plan.json";
import { SAMPLE_QUESTIONS } from "../components/chat/ChatWelcome";
import { ChatPage } from "./ChatPage";

/** A captured API response: the status and body the real backend returned. */
interface Capture {
  input?: string | null;
  status: number;
  body: unknown;
}

const asCapture = (json: unknown): Capture => json as Capture;
const chatHistory = asCapture(chatHistoryFixture);
const planReply = asCapture(chatPlanFixture);
const placeReply = asCapture(chatPlaceFixture);
const approveAsk = asCapture(chatApproveAsk);
const approveDone = asCapture(chatApproveDone);
const bookAsk = asCapture(chatBookAsk);
const bookDone = asCapture(chatBookDone);
const clarify1 = asCapture(chatClarify1);
const clarify2 = asCapture(chatClarify2);

const CONVERSATION = "f".repeat(32);
const NOT_FOUND = { status: 404, body: { detail: "Không tìm thấy cuộc trò chuyện" } };

interface ApiStub {
  /** Texts of the POST bodies, in the order they were sent. */
  sent: string[];
  /** Every URL requested, with its method. */
  calls: { method: string; url: string }[];
}

/**
 * Replaces fetch for the chat API. GET returns `history` (or 404 when null). Each POST returns the
 * next reply from `replies`; a function reply can wait on a promise.
 */
function stubChatApi(
  history: Capture | null,
  replies: Array<Capture | (() => Promise<Capture>)>,
): ApiStub {
  const stub: ApiStub = { sent: [], calls: [] };
  const queue = [...replies];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const method = init?.method ?? "GET";
      stub.calls.push({ method, url });
      if (method === "POST") {
        const body = JSON.parse(String(init?.body)) as { text: string };
        stub.sent.push(body.text);
        const next = queue.shift();
        if (next === undefined) throw new Error(`No reply queued for: ${body.text}`);
        const capture = typeof next === "function" ? await next() : next;
        return json(capture.status, capture.body);
      }
      const requested = url.split("/").pop();
      if (history === null || requested !== CONVERSATION) return json(NOT_FOUND.status, NOT_FOUND.body);
      return json(200, history.body);
    }),
  );
  return stub;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

/** A history payload built from captured turns, the same shape GET /api/v1/chat/{id} returns. */
function historyOf(turns: Capture[]): Capture {
  const messages = turns.flatMap((turn, index) => {
    const reply = turn.body as { text: string };
    return [
      { id: `u-${index}`, role: "user", text: turn.input ?? "", created_at: "2026-11-22T10:00:00", payload: null },
      { id: `a-${index}`, role: "assistant", text: reply.text, created_at: "2026-11-22T10:00:01", payload: turn.body },
    ];
  });
  return { status: 200, body: { conversation_id: CONVERSATION, messages } };
}

function renderChat(state?: { prefill: string }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: "/", state }]}>
      <ChatPage />
    </MemoryRouter>,
  );
}

/** Captures keep their input text so historyOf can rebuild the transcript. */
function turn(input: string, capture: Capture): Capture {
  return { ...capture, input };
}

describe("ChatPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem(CHAT_ID_KEY, CONVERSATION);
  });

  it("loads the stored conversation id and renders the transcript from history on mount", async () => {
    const stub = stubChatApi(chatHistory, []);

    renderChat();

    expect(await screen.findByText(/Mình đã lên lịch 3 ngày ở Huế/)).toBeInTheDocument();
    expect(screen.getByText(/Tôi đi Huế 3 ngày 2 đêm/)).toBeInTheDocument();
    expect(stub.calls[0]).toEqual({ method: "GET", url: `/api/v1/chat/${CONVERSATION}` });
  });

  it("sends the typed message on Enter and clears the box", async () => {
    const stub = stubChatApi(null, [clarify1]);
    renderChat();
    const box = screen.getByRole("textbox", { name: "Tin nhắn" });

    await userEvent.type(box, "Đi Huế 2 ngày{Enter}");

    expect(await screen.findByText("Bạn muốn đi Huế từ ngày nào?")).toBeInTheDocument();
    expect(stub.sent).toEqual(["Đi Huế 2 ngày"]);
    expect(box).toHaveValue("");
  });

  it("keeps Shift+Enter as a line break and does not send", async () => {
    const stub = stubChatApi(null, []);
    renderChat();
    const box = screen.getByRole("textbox", { name: "Tin nhắn" });

    await userEvent.type(box, "dòng một{Shift>}{Enter}{/Shift}dòng hai");

    expect(box).toHaveValue("dòng một\ndòng hai");
    expect(stub.sent).toEqual([]);
  });

  it("disables the send button while the box is empty", () => {
    stubChatApi(null, []);
    renderChat();

    expect(screen.getByRole("button", { name: "Gửi" })).toBeDisabled();
  });

  it("shows a thinking bubble while the reply is pending", async () => {
    let finish: (capture: Capture) => void = () => undefined;
    const pending = new Promise<Capture>((resolve) => {
      finish = resolve;
    });
    stubChatApi(null, [() => pending]);
    renderChat();

    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Đi Huế 2 ngày{Enter}");

    expect(await screen.findByRole("status")).toHaveTextContent("đang suy nghĩ…");
    finish(clarify1);
    expect(await screen.findByText("Bạn muốn đi Huế từ ngày nào?")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("chips send their text", async () => {
    const stub = stubChatApi(null, [clarify1, clarify2]);
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Đi Huế 2 ngày{Enter}");

    await userEvent.click(await screen.findByRole("button", { name: "Cuối tuần này" }));

    expect(await screen.findByText("Bạn xuất phát từ đâu và đi mấy người? (mặc định: Huế, 1 người)")).toBeInTheDocument();
    expect(stub.sent).toEqual(["Đi Huế 2 ngày", "Cuối tuần này"]);
  });

  it("pending approval shows Xác nhận and Huỷ, which send đồng ý and huỷ", async () => {
    const stub = stubChatApi(null, [approveAsk, approveDone]);
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Duyệt BUDGET{Enter}");

    await userEvent.click(await screen.findByRole("button", { name: "Xác nhận" }));

    expect(await screen.findByText(/Đã duyệt phương án Tiết kiệm/)).toBeInTheDocument();
    expect(stub.sent).toEqual(["Duyệt BUDGET", "đồng ý"]);
  });

  it("the Huỷ button sends huỷ", async () => {
    const stub = stubChatApi(null, [approveAsk, clarify1]);
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Duyệt BUDGET{Enter}");

    await userEvent.click(await screen.findByRole("button", { name: "Huỷ" }));

    await waitFor(() => expect(stub.sent).toEqual(["Duyệt BUDGET", "huỷ"]));
  });

  it("the plan card shows days, a detail link and budget buttons with Vietnamese names", async () => {
    const stub = stubChatApi(null, [planReply, approveAsk]);
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Tôi đi Huế 3 ngày{Enter}");

    const card = await screen.findByRole("region", { name: "Lịch trình" });
    expect(within(card).getByText("Ngày 1 · 05/12/2026")).toBeInTheDocument();
    // The fixture predates poi_id, so the item falls back to an illustration that also names the place.
    expect(within(card).getAllByText("Đại Nội Huế").length).toBeGreaterThan(0);
    expect(within(card).getByText("08:01")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Xem chi tiết" })).toHaveAttribute(
      "href",
      `/plan/${(planReply.body as { cards: { thread_id: string }[] }).cards[0].thread_id}`,
    );
    expect(within(card).queryByText(/BUDGET/)).not.toBeInTheDocument();

    await userEvent.click(within(card).getByRole("button", { name: "Duyệt Tiết kiệm" }));

    await waitFor(() => expect(stub.sent).toEqual(["Tôi đi Huế 3 ngày", "Duyệt BUDGET"]));
  });

  it("the place card shows the hours with the unverified note and links to the detail page", async () => {
    stubChatApi(null, [placeReply]);
    renderChat();
    await userEvent.type(screen.getByRole("textbox", { name: "Tin nhắn" }), "Đại Nội mở cửa mấy giờ?{Enter}");

    const card = await screen.findByRole("region", { name: "Địa điểm: Đại Nội Huế" });
    expect(within(card).getByText("07:30-17:30")).toBeInTheDocument();
    expect(within(card).getByText("(chưa xác minh)")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Xem trên trang khám phá" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/explore\/huetripo/),
    );
  });

  it("the booking card shows MÔ PHỎNG badges and the contacts for places", async () => {
    stubChatApi(null, [bookAsk, bookDone]);
    renderChat();
    const box = screen.getByRole("textbox", { name: "Tin nhắn" });
    await userEvent.type(box, "Đặt vé và khách sạn{Enter}");
    await screen.findByRole("button", { name: "Xác nhận" });
    await userEvent.type(box, "đồng ý{Enter}");

    const card = await screen.findByRole("region", { name: "Kết quả đặt chỗ" });
    expect(within(card).getAllByText("MÔ PHỎNG").length).toBeGreaterThan(0);
    expect(within(card).getByRole("heading", { name: "Tự liên hệ" })).toBeInTheDocument();
    expect(within(card).getByText(/0915088175/)).toBeInTheDocument();
  });

  it("tags each bot reply with the source that understood it", async () => {
    const llmReply = { ...approveDone, body: { ...(approveDone.body as object), understanding: { intent: "approve", source: "OLLAMA", notes: [] } } };
    stubChatApi(historyOf([turn("Đi Huế 2 ngày", clarify1), turn("Đồng ý", llmReply)]), []);

    renderChat();

    expect(await screen.findByText("Hiểu bằng: luật (Ollama không chạy)")).toBeInTheDocument();
    expect(screen.getByText("Hiểu bằng: LLM (qwen3.5:4b)")).toBeInTheDocument();
  });

  it("Cuộc trò chuyện mới clears the transcript and stores a new id", async () => {
    stubChatApi(chatHistory, []);
    renderChat();
    expect(await screen.findByText(/Mình đã lên lịch 3 ngày ở Huế/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cuộc trò chuyện mới" }));

    await waitFor(() => expect(screen.queryByText(/Mình đã lên lịch 3 ngày ở Huế/)).not.toBeInTheDocument());
    expect(window.localStorage.getItem(CHAT_ID_KEY)).not.toBe(CONVERSATION);
  });

  it("links to the form page", () => {
    stubChatApi(null, []);
    renderChat();

    expect(screen.getByRole("link", { name: "Nhập bằng form" })).toHaveAttribute("href", "/form");
  });

  it("fills the composer from a sample question without sending", async () => {
    const stub = stubChatApi(null, []);
    renderChat();

    await userEvent.click(await screen.findByRole("button", { name: SAMPLE_QUESTIONS[1] }));

    expect(screen.getByRole("textbox", { name: "Tin nhắn" })).toHaveValue(SAMPLE_QUESTIONS[1]);
    expect(stub.sent).toEqual([]);
  });

  it("fills the composer from router state", async () => {
    stubChatApi(null, []);
    renderChat({ prefill: "Đại Nội Huế có gì hay?" });

    expect(await screen.findByRole("textbox", { name: "Tin nhắn" })).toHaveValue("Đại Nội Huế có gì hay?");
  });
});
