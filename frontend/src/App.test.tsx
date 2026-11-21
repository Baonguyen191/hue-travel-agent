import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { routeFetch } from "./test/fetchMock";
import { USER_ID_KEY } from "./lib/userId";
import planJson from "./test/fixtures/plan.json";


function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("app shell", () => {
  beforeEach(() => {
    routeFetch(() => ({ body: { items: [], total: 0, limit: 24, offset: 0 } }));
  });

  it("shows the Vietnamese navigation and the persistent MOCK disclaimer", () => {
    window.localStorage.setItem(USER_ID_KEY, "1a2b3c4d-0000-0000-0000-000000000000");
    renderAt("/");

    const nav = screen.getByRole("navigation", { name: "Chính" });
    expect(nav).toHaveTextContent("Trò chuyện");
    expect(nav).toHaveTextContent("Khám phá Huế");
    expect(screen.getByText(/Người dùng thử: 1a2b3c4d — chưa phải đăng nhập/)).toBeInTheDocument();
    expect(screen.getByText(/Xe, khách sạn và đặt chỗ là/)).toHaveTextContent("MÔ PHỎNG");
    expect(screen.getByText(/huetripo\.hue\.gov\.vn/)).toBeInTheDocument();
  });

  it("navigates between screens from the top nav", async () => {
    renderAt("/");

    await userEvent.click(screen.getByRole("link", { name: "Khám phá Huế" }));

    expect(screen.getByRole("heading", { name: "Khám phá Huế" })).toBeInTheDocument();
  });

  it("opens the plan route and shows the trip header", async () => {
    routeFetch(() => ({ body: planJson }));
    renderAt("/plan/e3d7c6b9-956b-42f7-9916-479fe993c969");

    expect(await screen.findByRole("heading", { level: 1, name: "Hà Nội → Huế" })).toBeInTheDocument();
  });

  it("keeps the request form at /form", () => {
    renderAt("/form");

    expect(screen.getByRole("heading", { level: 1, name: "Lập kế hoạch chuyến đi" })).toBeInTheDocument();
  });

  it("shows a 404 page for unknown paths", () => {
    renderAt("/khong-co-trang");

    expect(screen.getByRole("heading", { name: "Không tìm thấy trang" })).toBeInTheDocument();
  });
});
