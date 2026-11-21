import { beforeEach, describe, expect, it } from "vitest";
import type { ChatHistory, ChatReply } from "../api/types";
import chatHistory from "../test/fixtures/chat/chat-history.json";
import chatPlan from "../test/fixtures/chat/chat-01-plan.json";
import chatApproveAsk from "../test/fixtures/chat/chat-03-approve-ask.json";
import chatClarifyDefaults from "../test/fixtures/chat/chat-clarify-2.json";
import {
  CHAT_ID_KEY,
  loadConversationId,
  messagesFromHistory,
  quickReplyLabel,
  showsConfirmation,
  sourceTagText,
  startNewConversation,
  visibleQuickReplies,
} from "./chat";

function replyOf(capture: { body: unknown }): ChatReply {
  return capture.body as ChatReply;
}

describe("sourceTagText", () => {
  it("names the LLM and its model when Ollama read the message", () => {
    expect(sourceTagText("OLLAMA")).toBe("Hiểu bằng: LLM (qwen3.5:4b)");
  });

  it("says the rules answered when Ollama did not", () => {
    expect(sourceTagText("RULES")).toBe("Hiểu bằng: luật (Ollama không chạy)");
  });
});

describe("quickReplyLabel", () => {
  it("shows the Vietnamese budget name for an approve chip but keeps the sent text", () => {
    expect(quickReplyLabel("Duyệt BUDGET")).toBe("Duyệt Tiết kiệm");
    expect(quickReplyLabel("Duyệt COMFORT")).toBe("Duyệt Thoải mái");
  });

  it("leaves every other chip unchanged", () => {
    expect(quickReplyLabel("Cuối tuần này")).toBe("Cuối tuần này");
    expect(quickReplyLabel("Duyệt XYZ")).toBe("Duyệt XYZ");
  });
});

describe("confirmation and quick replies", () => {
  it("shows confirmation buttons for the last approve step and hides its yes/no chips", () => {
    const reply = replyOf(chatApproveAsk);

    expect(showsConfirmation(reply, true)).toBe(true);
    expect(visibleQuickReplies(reply)).toEqual([]);
  });

  it("does not show stale confirmation buttons on an older message", () => {
    expect(showsConfirmation(replyOf(chatApproveAsk), false)).toBe(false);
  });

  it("keeps the defaults answers as chips, without confirmation buttons", () => {
    const reply = replyOf(chatClarifyDefaults);

    expect(showsConfirmation(reply, true)).toBe(false);
    expect(visibleQuickReplies(reply)).toEqual(["Từ Hà Nội, 2 người", "Dùng mặc định"]);
  });

  it("drops the approve chip when the plan card already offers the budget option", () => {
    const reply = replyOf(chatPlan);

    expect(reply.quick_replies).toEqual(["Duyệt BUDGET"]);
    expect(visibleQuickReplies(reply)).toEqual([]);
  });
});

describe("messagesFromHistory", () => {
  it("keeps the order and attaches the stored reply to assistant messages only", () => {
    const messages = messagesFromHistory((chatHistory as unknown as { body: ChatHistory }).body);

    expect(messages).toHaveLength(12);
    expect(messages[0]).toMatchObject({ role: "user", reply: null });
    expect(messages[1].role).toBe("assistant");
    expect(messages[1].reply?.understanding.intent).toBe("plan_new");
  });
});

describe("loadConversationId", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("creates a 32-character id once and reuses it", () => {
    const first = loadConversationId();
    const second = loadConversationId();

    expect(first).toMatch(/^[0-9a-f]{32}$/);
    expect(second).toBe(first);
    expect(window.localStorage.getItem(CHAT_ID_KEY)).toBe(first);
  });

  it("replaces a stored value that is not a conversation id", () => {
    window.localStorage.setItem(CHAT_ID_KEY, "not-an-id");

    const id = loadConversationId();

    expect(id).toMatch(/^[0-9a-f]{32}$/);
  });

  it("startNewConversation saves a different id", () => {
    const before = loadConversationId();

    const after = startNewConversation();

    expect(after).not.toBe(before);
    expect(window.localStorage.getItem(CHAT_ID_KEY)).toBe(after);
  });
});
