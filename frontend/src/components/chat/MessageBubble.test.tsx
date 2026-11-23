import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ChatReply } from "../../api/types";
import type { ChatMessage } from "../../lib/chat";
import { MessageBubble } from "./MessageBubble";

const reply: ChatReply = {
  message_id: "m1",
  text: "Đây là Đại Nội.",
  cards: [
    {
      kind: "place",
      poi_id: "huetripo:531787",
      name: "Đại Nội Huế",
      category: "historic",
      address: null,
      opening_hours_raw: null,
      opening_hours_note: "chưa xác minh",
      price_min_vnd: null,
      price_max_vnd: null,
      phone: null,
      source_url: null,
    },
  ],
  quick_replies: ["Cuối tuần này"],
  pending_confirmation: null,
  understanding: { intent: "place", source: "RULES", notes: [] },
};

const message: ChatMessage = { key: "a1", role: "assistant", text: "Đây là Đại Nội.", reply };

describe("bot message bubble", () => {
  it("keeps the cards outside the son bubble, which holds only the text", () => {
    render(
      <MemoryRouter>
        <MessageBubble message={message} isLast={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const bubble = screen.getByText("Đây là Đại Nội.").closest(".bg-son");
    expect(bubble).not.toBeNull();
    expect(bubble).not.toContainElement(screen.getByRole("heading", { name: "Đại Nội Huế" }));
    expect(bubble).not.toContainElement(screen.getByRole("button", { name: "Cuối tuần này" }));
    expect(screen.getByRole("region", { name: "Địa điểm: Đại Nội Huế" })).not.toHaveClass("bg-son");
  });
});
