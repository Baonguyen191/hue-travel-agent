import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ChatPlanCard } from "../../api/types";
import { ChatCardView } from "./ChatCards";

const card: ChatPlanCard = {
  kind: "plan_summary",
  thread_id: "t1",
  status: "AWAITING_APPROVAL",
  version: 1,
  days: [
    {
      date: "2026-12-20",
      items: [
        { time: "08:00", name: "Đại Nội Huế", kind: "VISIT", meal: null, poi_id: "huetripo:531787" },
        { time: "11:30", name: "Nghỉ ăn trưa", kind: "MEAL_BREAK", meal: null, poi_id: null },
      ],
    },
  ],
  budget_options: [],
};

describe("plan card photos", () => {
  it("shows a photo for each item with a poi id and an illustration otherwise", () => {
    render(
      <MemoryRouter>
        <ChatCardView card={card} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const section = screen.getByRole("region", { name: "Lịch trình" });
    expect(within(section).getByRole("img", { name: "Đại Nội Huế" })).toHaveAttribute(
      "src",
      "/api/v1/places/huetripo%3A531787/photo?w=160",
    );
    expect(within(section).getAllByTestId("place-illustration")).toHaveLength(1);
    expect(within(section).getByText("08:00")).toBeInTheDocument();
  });
});
