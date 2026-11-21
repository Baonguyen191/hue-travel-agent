import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessage, isNotFound } from "../api/client";
import type { Place } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlacesMap } from "../components/PlacesMap";
import { openingHoursText } from "../components/PlaceCard";
import { describePrice, describeRating, formatDate, formatMinutes, formatTime } from "../lib/format";
import { CATEGORY_LABEL } from "../lib/labels";

/** Warnings about this POI's data. Always shown, even when the list is short. */
export function placeWarnings(place: Place): string[] {
  const warnings: string[] = [];
  if (place.opening_hours_raw === null) {
    warnings.push("Nguồn không có giờ mở cửa.");
  } else if (place.opening_hours_confidence === "UNVERIFIED") {
    warnings.push("Giờ mở cửa lấy từ nguồn và chưa được xác minh.");
  } else if (place.opening_hours_confidence === "PARTIAL") {
    warnings.push("Giờ mở cửa mới xác minh một phần.");
  } else {
    warnings.push("Chưa rõ giờ mở cửa.");
  }
  if (place.price_status === "REFERENCE_RANGE") {
    warnings.push("Giá là giá tham khảo từ nguồn; đơn vị chưa rõ, nên kiểm tra trước khi đi.");
  } else if (place.price_status === "FREE_CLAIM") {
    warnings.push("Nguồn ghi là miễn phí; chưa kiểm chứng.");
  } else {
    warnings.push("Chưa có thông tin giá.");
  }
  if (place.rating_value === null) warnings.push("Chưa có đánh giá.");
  return warnings;
}

type DetailState =
  | { status: "loading" }
  | { status: "ready"; place: Place }
  | { status: "not-found" }
  | { status: "error"; message: string };

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-2 text-sm sm:grid-cols-[10rem_1fr]">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function PlaceDetailPage() {
  const { poiId = "" } = useParams();
  const [state, setState] = useState<DetailState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    api.getPlace(poiId, controller.signal).then(
      (place) => setState({ status: "ready", place }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState(isNotFound(error) ? { status: "not-found" } : { status: "error", message: errorMessage(error) });
      },
    );
    return () => controller.abort();
  }, [poiId]);

  return (
    <div className="space-y-6">
      <Link to="/explore" className="text-sm font-medium text-teal-700 underline">
        ← Khám phá Huế
      </Link>

      {state.status === "loading" ? (
        <div role="status" aria-label="Đang tải chi tiết" className="h-64 animate-pulse rounded-lg bg-slate-100" />
      ) : null}

      {state.status === "not-found" ? (
        <section className="rounded-lg border border-slate-200 bg-white p-6">
          <h1 className="text-xl font-semibold">Không tìm thấy địa điểm</h1>
          <p className="mt-2 text-sm text-slate-600">Mã {poiId} không có trong nguồn dữ liệu Huế.</p>
        </section>
      ) : null}

      {state.status === "error" ? <ErrorBanner message={state.message} /> : null}

      {state.status === "ready" ? <PlaceDetail place={state.place} /> : null}
    </div>
  );
}

function PlaceDetail({ place }: { place: Place }) {
  const warnings = placeWarnings(place);

  return (
    <article className="space-y-6">
      <header className="space-y-2">
        <span className="inline-block rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700">
          {CATEGORY_LABEL[place.category]}
        </span>
        <h1 className="text-2xl font-semibold leading-snug">{place.name}</h1>
        {place.address ? <p className="text-sm text-slate-600">{place.address}</p> : null}
      </header>

      <section aria-labelledby="warnings-heading" className="rounded-lg border border-amber-300 bg-amber-50 p-4">
        <h2 id="warnings-heading" className="text-sm font-semibold text-amber-900">
          Cảnh báo về dữ liệu
        </h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </section>

      <div className="gap-6 md:grid md:grid-cols-[minmax(0,1fr)_minmax(260px,360px)]">
        <div className="min-w-0 space-y-6">
          <section aria-labelledby="info-heading" className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 id="info-heading" className="text-base font-semibold">
              Thông tin đã chuẩn hóa
            </h2>
            <dl className="mt-2 divide-y divide-slate-100">
              <Field label="Đánh giá">
                {describeRating(place.rating_value, place.rating_count)}
                {place.rating_source ? ` (${place.rating_source})` : ""}
              </Field>
              <Field label="Giá">{describePrice(place)}</Field>
              <Field label="Giờ mở cửa">{openingHoursText(place)}</Field>
              <Field label="Thời gian tham quan">{formatMinutes(place.visit_minutes)}</Field>
              <Field label="Tọa độ">
                {place.lat.toFixed(5)}, {place.lon.toFixed(5)}
              </Field>
              <Field label="Nguồn">
                {place.source}
                {place.source_url ? (
                  <>
                    {" · "}
                    <a
                      href={place.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-teal-700 underline"
                    >
                      Mở trang nguồn
                    </a>
                  </>
                ) : null}
              </Field>
              <Field label="Mã trong nguồn">{place.source_place_id}</Field>
              <Field label="Thu thập lúc">
                {formatDate(place.collected_at)} {formatTime(place.collected_at)}
              </Field>
            </dl>
          </section>

          {place.summary ? (
            <section aria-labelledby="summary-heading" className="rounded-lg border border-slate-200 bg-white p-4">
              <h2 id="summary-heading" className="text-base font-semibold">
                Giới thiệu từ nguồn
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">{place.summary}</p>
            </section>
          ) : null}

          <section aria-labelledby="raw-heading" className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 id="raw-heading" className="text-base font-semibold">
              Thuộc tính gốc từ nguồn
            </h2>
            {Object.keys(place.raw_attributes).length === 0 ? (
              <p className="mt-2 text-sm text-slate-600">Nguồn không có thuộc tính bổ sung.</p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="sr-only">
                    <tr>
                      <th scope="col">Thuộc tính</th>
                      <th scope="col">Giá trị</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {Object.entries(place.raw_attributes).map(([key, value]) => (
                      <tr key={key} className="align-top">
                        <th scope="row" className="w-1/3 py-2 pr-3 font-medium text-slate-600">
                          {key}
                        </th>
                        <td className="break-words py-2">{String(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <aside className="mt-6 md:mt-0 md:sticky md:top-4 md:self-start">
          <PlacesMap places={[place]} heightClass="h-64" />
        </aside>
      </div>
    </article>
  );
}
