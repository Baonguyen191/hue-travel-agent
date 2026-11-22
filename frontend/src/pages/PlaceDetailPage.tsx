import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessage, isNotFound } from "../api/client";
import type { Place } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlacesMap } from "../components/PlacesMap";
import { openingHoursText } from "../components/PlaceCard";
import { describePrice, describeRating, formatDate, formatMinutes, formatTime } from "../lib/format";
import { CategoryChip, LINK, Notice, Ornament, PlaceIllustration, PlacePhoto, SectionHeading, buttonClass, cardClass } from "../components/ui";

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

/** Question sent to the chat when the user asks the assistant about a place. */
export function askAssistantText(name: string): string {
  return `${name} có gì hay? Giờ mở cửa và giá vé thế nào?`;
}

type DetailState =
  | { status: "loading" }
  | { status: "ready"; place: Place }
  | { status: "not-found" }
  | { status: "error"; message: string };

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-2 py-2 text-sm sm:grid-cols-[10rem_1fr]">
      <dt className="text-muc-soft">{label}</dt>
      <dd className="min-w-0 break-words text-muc">{children}</dd>
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
      <Link to="/explore" className={`${LINK} text-sm`}>
        ← Khám phá Huế
      </Link>

      {state.status === "loading" ? (
        <div role="status" aria-label="Đang tải chi tiết" className="h-64 animate-pulse rounded-2xl bg-kim-soft" />
      ) : null}

      {state.status === "not-found" ? (
        <section className={cardClass("p-6")}>
          <PlaceIllustration category={null} className="mb-4 h-32 rounded-xl" />
          <SectionHeading as="h1">Không tìm thấy địa điểm</SectionHeading>
          <p className="mt-2 text-sm text-muc-soft">Mã {poiId} không có trong nguồn dữ liệu Huế.</p>
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
      <div className={cardClass()}>
        <div className="relative">
          <PlacePhoto
            poiId={place.id}
            name={place.name}
            category={place.category}
            size="lg"
            aspect="16/9"
            className="max-h-80"
          />
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-muc/85 via-muc/20 to-transparent" />
          <h1 className="absolute inset-x-4 bottom-3 font-serif text-2xl font-semibold leading-snug text-nga md:text-3xl">
            {place.name}
          </h1>
        </div>
        <Ornament />
        <div className="flex flex-wrap items-center gap-3 p-4">
          <CategoryChip category={place.category} />
          <Link to="/" state={{ prefill: askAssistantText(place.name) }} className={buttonClass("primary", "sm")}>
            Hỏi trợ lý về nơi này
          </Link>
          {place.address ? <p className="w-full text-sm text-muc-soft">{place.address}</p> : null}
        </div>
      </div>

      <Notice variant="warning" aria-labelledby="warnings-heading" role="region">
        <h2 id="warnings-heading" className="font-serif text-sm font-semibold text-son">
          Cảnh báo về dữ liệu
        </h2>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      </Notice>

      <div className="gap-6 md:grid md:grid-cols-[minmax(0,1fr)_minmax(260px,360px)]">
        <div className="min-w-0 space-y-6">
          <section aria-labelledby="info-heading" className={cardClass("p-4")}>
            <SectionHeading id="info-heading">Thông tin đã chuẩn hóa</SectionHeading>
            <dl className="mt-2 divide-y divide-vien">
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
                    <a href={place.source_url} target="_blank" rel="noopener noreferrer" className={LINK}>
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
            <section aria-labelledby="summary-heading" className={cardClass("p-4")}>
              <SectionHeading id="summary-heading">Giới thiệu từ nguồn</SectionHeading>
              <p className="mt-2 text-sm leading-relaxed text-muc-soft">{place.summary}</p>
            </section>
          ) : null}

          <section aria-labelledby="raw-heading" className={cardClass("p-4")}>
            <SectionHeading id="raw-heading">Thuộc tính gốc từ nguồn</SectionHeading>
            {Object.keys(place.raw_attributes).length === 0 ? (
              <p className="mt-2 text-sm text-muc-soft">Nguồn không có thuộc tính bổ sung.</p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="sr-only">
                    <tr>
                      <th scope="col">Thuộc tính</th>
                      <th scope="col">Giá trị</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-vien">
                    {Object.entries(place.raw_attributes).map(([key, value]) => (
                      <tr key={key} className="align-top">
                        <th scope="row" className="w-1/3 py-2 pr-3 font-medium text-muc-soft">
                          {key}
                        </th>
                        <td className="break-words py-2 text-muc">{String(value)}</td>
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
