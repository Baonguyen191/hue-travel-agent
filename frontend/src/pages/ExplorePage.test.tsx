import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import listJson from "../test/fixtures/places-historic.json";
import searchJson from "../test/fixtures/places-search-dai-noi.json";
import { calledUrls, routeFetch } from "../test/fetchMock";
import { ExplorePage } from "./ExplorePage";

// The map needs a real layout engine; its own behaviour is covered in PlacesMap.test.tsx.
vi.mock("../components/PlacesMap", async () => {
  const { createElement } = await import("react");
  return {
    PlacesMap: ({ places }: { places: unknown[] }) => createElement("div", { "data-testid": "map" }, `${places.length} điểm trên bản đồ`),
  };
});

function renderExplore() {
  return render(
    <MemoryRouter>
      <ExplorePage />
    </MemoryRouter>,
  );
}

function listRoutes() {
  return (url: string) => {
    if (url.includes("/places/search")) return { body: searchJson };
    return { body: listJson };
  };
}

describe("ExplorePage", () => {
  beforeEach(() => {
    window.localStorage.setItem("hue.userId", "tester-0001");
  });

  it("loads the first page of places with the total and reference prices", async () => {
    const fetchMock = routeFetch(listRoutes());
    renderExplore();

    expect(await screen.findByRole("heading", { name: "Quốc Tử Giám" })).toBeInTheDocument();
    expect(screen.getByText("251 địa điểm")).toBeInTheDocument();
    expect(screen.getAllByText("miễn phí theo nguồn")).not.toHaveLength(0);
    expect(screen.getAllByText(/tham khảo, đơn vị chưa rõ\)$/)).not.toHaveLength(0);
    expect(calledUrls(fetchMock)[0]).toBe("/api/v1/places?limit=24&offset=0");
  });

  it("sends the X-User-Id header on every request", async () => {
    const fetchMock = routeFetch(listRoutes());
    renderExplore();
    await screen.findByRole("heading", { name: "Quốc Tử Giám" });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-User-Id"]).toBe("tester-0001");
  });

  it("searches after a 300 ms debounce and shows the matching count", async () => {
    const fetchMock = routeFetch(listRoutes());
    renderExplore();
    await screen.findByRole("heading", { name: "Quốc Tử Giám" });

    await userEvent.type(screen.getByLabelText("Tìm theo tên hoặc địa chỉ"), "dai noi");

    expect(await screen.findByText("Tìm thấy 2 địa điểm cho “dai noi”")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Đại Nội Huế" })).toBeInTheDocument();
    const searchCalls = calledUrls(fetchMock).filter((url) => url.includes("/places/search"));
    expect(searchCalls).toEqual(["/api/v1/places/search?q=dai+noi&limit=24&offset=0"]);
  });

  it("filters by category and resets to the first page", async () => {
    const fetchMock = routeFetch(listRoutes());
    renderExplore();
    await screen.findByRole("heading", { name: "Quốc Tử Giám" });

    await userEvent.click(screen.getByRole("button", { name: "Di tích" }));

    await waitFor(() => expect(calledUrls(fetchMock)).toContain("/api/v1/places?category=historic&limit=24&offset=0"));
    expect(screen.getByRole("button", { name: "Di tích" })).toHaveAttribute("aria-pressed", "true");
  });

  it("moves between pages with a page counter", async () => {
    const fetchMock = routeFetch(listRoutes());
    renderExplore();
    await screen.findByRole("heading", { name: "Quốc Tử Giám" });

    const pager = screen.getByRole("navigation", { name: "Phân trang" });
    expect(within(pager).getByRole("button", { name: "Trang trước" })).toBeDisabled();
    await userEvent.click(within(pager).getByRole("button", { name: "Trang sau" }));

    expect(await screen.findByText("Trang 2 / 11")).toBeInTheDocument();
    expect(calledUrls(fetchMock)).toContain("/api/v1/places?limit=24&offset=24");
  });

  it("shows the API detail when the source is unavailable", async () => {
    routeFetch(() => ({ status: 503, body: { detail: "Hue SQLite source file is unavailable." } }));
    renderExplore();

    expect(await screen.findByRole("alert")).toHaveTextContent("Hue SQLite source file is unavailable.");
  });

  it("says so when nothing matches", async () => {
    routeFetch(() => ({ body: { items: [], total: 0, limit: 24, offset: 0 } }));
    renderExplore();

    expect(await screen.findByText("Không có địa điểm nào khớp bộ lọc.")).toBeInTheDocument();
  });

  it("passes the current page of places to the map", async () => {
    routeFetch(listRoutes());
    renderExplore();

    expect(await screen.findByTestId("map")).toHaveTextContent("5 điểm trên bản đồ");
  });
});
