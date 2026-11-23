import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ChatPlaceCard, ChatPlanCard } from "../../api/types";
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

describe("place card photo label", () => {
  const placeCard: ChatPlaceCard = {
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
  };

  it("shows the illustrative badge when the card photo is a generic picture", () => {
    render(
      <MemoryRouter>
        <ChatCardView card={{ ...placeCard, photo_illustrative: true }} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("region", { name: "Địa điểm: Đại Nội Huế" })).toHaveTextContent("Ảnh minh hoạ");
  });

  it("has no badge for the place's own photo", () => {
    render(
      <MemoryRouter>
        <ChatCardView card={placeCard} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Ảnh minh hoạ")).not.toBeInTheDocument();
  });
});

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

  it("shows the sunset slot label before the time and the reason only as a tooltip", () => {
    const sunsetCard: ChatPlanCard = {
      ...card,
      days: [
        {
          date: "2026-12-05",
          items: [
            {
              time: "16:30",
              name: "Cầu Trường Tiền",
              kind: "VISIT",
              meal: null,
              poi_id: "huetripo:664215",
              slot: "sunset",
              reason: "điểm ngắm hoàng hôn",
            },
          ],
        },
      ],
    };
    render(
      <MemoryRouter>
        <ChatCardView card={sunsetCard} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const section = screen.getByRole("region", { name: "Lịch trình" });
    expect(within(section).getByText("Hoàng hôn")).toBeInTheDocument();
    expect(within(section).getByText("16:30")).toBeInTheDocument();
    expect(within(section).getByTitle("điểm ngắm hoàng hôn")).toBeInTheDocument();
    expect(within(section).queryByText("Lý do: điểm ngắm hoàng hôn")).not.toBeInTheDocument();
  });

  it("adds the guide intro to the item tooltip after the reason", () => {
    const introCard: ChatPlanCard = {
      ...card,
      days: [
        {
          date: "2026-12-05",
          items: [
            {
              time: "08:00",
              name: "Đại Nội Huế",
              kind: "VISIT",
              meal: null,
              poi_id: "huetripo:531787",
              slot: "morning",
              reason: "hợp sở thích di tích",
              intro: "Từng là nơi ở của các vua triều Nguyễn.",
            },
          ],
        },
      ],
    };
    render(
      <MemoryRouter>
        <ChatCardView card={introCard} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const section = screen.getByRole("region", { name: "Lịch trình" });
    expect(within(section).getByTitle("hợp sở thích di tích Từng là nơi ở của các vua triều Nguyễn.")).toBeInTheDocument();
    expect(within(section).queryByText("Từng là nơi ở của các vua triều Nguyễn.")).not.toBeInTheDocument();
  });

  it("shows no slot label for items without a slot", () => {
    render(
      <MemoryRouter>
        <ChatCardView card={card} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const section = screen.getByRole("region", { name: "Lịch trình" });
    expect(within(section).queryByText("Sáng")).not.toBeInTheDocument();
    expect(within(section).queryByText("Hoàng hôn")).not.toBeInTheDocument();
  });
});
