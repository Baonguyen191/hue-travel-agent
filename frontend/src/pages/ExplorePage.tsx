import { useEffect, useState } from "react";
import { api, errorMessage } from "../api/client";
import type { Place, PlaceCategory } from "../api/types";
import { CategoryChips } from "../components/CategoryChips";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlaceCard } from "../components/PlaceCard";
import { PlacesMap } from "../components/PlacesMap";
import { CardSkeletons } from "../components/Skeletons";
import { useDebouncedValue } from "../hooks/useDebouncedValue";

export const PAGE_SIZE = 24;
const SEARCH_DEBOUNCE_MS = 300;

/** The filters that define one request. A change to any of them starts a new load. */
interface Filters {
  q: string;
  category: PlaceCategory | null;
  offset: number;
}

interface LoadState {
  status: "loading" | "ready" | "error";
  items: Place[];
  total: number;
  message: string;
}

export function ExplorePage() {
  const [input, setInput] = useState("");
  const debouncedQuery = useDebouncedValue(input.trim(), SEARCH_DEBOUNCE_MS);
  const [filters, setFilters] = useState<Filters>({ q: "", category: null, offset: 0 });
  const [load, setLoad] = useState<LoadState>({ status: "loading", items: [], total: 0, message: "" });

  // A new debounced query starts again from the first page.
  useEffect(() => {
    setFilters((current) => (current.q === debouncedQuery ? current : { ...current, q: debouncedQuery, offset: 0 }));
  }, [debouncedQuery]);

  useEffect(() => {
    const controller = new AbortController();
    setLoad((previous) => ({ ...previous, status: "loading", message: "" }));
    const paging = { category: filters.category ?? undefined, limit: PAGE_SIZE, offset: filters.offset };
    const request = filters.q
      ? api
          .searchPlaces({ q: filters.q, ...paging }, controller.signal)
          .then((page) => ({ items: page.items.map((result) => result.place), total: page.total }))
      : api.listPlaces(paging, controller.signal).then((page) => ({ items: page.items, total: page.total }));

    request.then(
      (result) => setLoad({ status: "ready", items: result.items, total: result.total, message: "" }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setLoad({ status: "error", items: [], total: 0, message: errorMessage(error) });
      },
    );
    return () => controller.abort();
  }, [filters]);

  const pageCount = Math.max(1, Math.ceil(load.total / PAGE_SIZE));
  const currentPage = Math.floor(filters.offset / PAGE_SIZE) + 1;

  const summary =
    load.status === "loading"
      ? "Đang tải…"
      : filters.q
        ? `Tìm thấy ${load.total} địa điểm cho “${filters.q}”`
        : `${load.total} địa điểm`;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Khám phá Huế</h1>
        <p className="text-sm text-slate-600">
          Dữ liệu từ huetripo.hue.gov.vn. Giá là giá tham khảo, giờ mở cửa chưa được xác minh.
        </p>
      </header>

      <div className="space-y-3">
        <div>
          <label htmlFor="explore-search" className="block text-sm font-medium text-slate-800">
            Tìm theo tên hoặc địa chỉ
          </label>
          <input
            id="explore-search"
            type="search"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="ví dụ: đại nội, chợ đông ba"
            autoComplete="off"
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-base shadow-sm focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-200"
          />
        </div>
        <CategoryChips
          value={filters.category}
          onChange={(category) => setFilters((current) => ({ ...current, category, offset: 0 }))}
        />
      </div>

      {load.status === "error" ? <ErrorBanner message={load.message} /> : null}

      <div className="gap-6 md:grid md:grid-cols-[minmax(0,1fr)_minmax(260px,380px)]">
        <section aria-label="Kết quả" className="min-w-0 space-y-4">
          <p aria-live="polite" className="text-sm text-slate-600">
            {summary}
          </p>

          {load.status === "loading" && load.items.length === 0 ? (
            <CardSkeletons count={6} label="Đang tải địa điểm" />
          ) : load.items.length === 0 && load.status === "ready" ? (
            <p className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-600">
              Không có địa điểm nào khớp bộ lọc.
            </p>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {load.items.map((place) => (
                <li key={place.id}>
                  <PlaceCard place={place} />
                </li>
              ))}
            </ul>
          )}

          {load.total > PAGE_SIZE ? (
            <nav aria-label="Phân trang" className="flex items-center justify-between gap-3 text-sm">
              <button
                type="button"
                disabled={filters.offset === 0 || load.status === "loading"}
                onClick={() => setFilters((current) => ({ ...current, offset: Math.max(0, current.offset - PAGE_SIZE) }))}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Trang trước
              </button>
              <span>
                Trang {currentPage} / {pageCount}
              </span>
              <button
                type="button"
                disabled={currentPage >= pageCount || load.status === "loading"}
                onClick={() => setFilters((current) => ({ ...current, offset: current.offset + PAGE_SIZE }))}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Trang sau
              </button>
            </nav>
          ) : null}
        </section>

        <aside className="mt-6 md:sticky md:top-4 md:mt-0 md:self-start">
          <PlacesMap places={load.items} />
        </aside>
      </div>
    </div>
  );
}
