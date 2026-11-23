import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { api, errorMessage, isNotFound } from "../api/client";
import type { Place, PlacePhotoInfo } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { PlacesMap } from "../components/PlacesMap";
import { openingHoursText } from "../components/PlaceCard";
import { describePrice, formatMinutes } from "../lib/format";
import {
  factualParagraph,
  highlights,
  introTeaser,
  isFoodPlace,
  placeNote,
  placePhone,
  ratingScore,
  ratingWord,
  splitParagraphs,
} from "../lib/placeIntro";
import { CategoryChip, LINK, Ornament, PlaceIllustration, PlacePhoto, SectionHeading, buttonClass, cardClass, isIllustrative } from "../components/ui";

/** Question sent to the chat when the user asks the assistant about a place. */
export function askAssistantText(name: string): string {
  return `${name} có gì hay? Giờ mở cửa và giá vé thế nào?`;
}

/** Credit line for a Commons photo (author, licence, link). Nothing for the source's own photo or no photo. */
function PhotoCredit({ photo }: { photo: PlacePhotoInfo | null | undefined }) {
  if (!photo || photo.kind === "source") return null;
  const credit = (
    <>
      Ảnh: {photo.author ?? "không rõ tác giả"} · {photo.license ?? "không rõ giấy phép"} ·{" "}
      {photo.credit_url ? (
        <a href={photo.credit_url} target="_blank" rel="noopener noreferrer" className={LINK}>
          Wikimedia Commons
        </a>
      ) : (
        "Wikimedia Commons"
      )}
    </>
  );
  return (
    <p className="px-4 pt-2 text-xs text-muc-soft">
      {photo.kind === "commons_illustrative" ? "Ảnh minh hoạ, không phải ảnh của địa điểm này. " : null}
      {credit}
    </p>
  );
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
      <dd className="min-w-0 break-words text-muc [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

/** Summary line of a collapsible section: full width, keyboard focusable, with a visible focus ring. */
const SUMMARY_CLASS =
  "flex cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-4 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-son [&::-webkit-details-marker]:hidden";

function Chevron() {
  return (
    <span aria-hidden="true" className="shrink-0 text-muc-soft transition-transform group-open:rotate-90">
      ▸
    </span>
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
      <Link to="/explore" className={`${LINK} mb-3 inline-block text-sm`}>
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

/** Score block (son background) with a word label, and the number of reviews beside it. */
function RatingCard({ value, count, source }: { value: number; count: number | null; source: string | null }) {
  const reviews = `${count !== null ? `${count} lượt đánh giá` : "Đánh giá"}${source ? ` trên ${source}` : ""}`;
  return (
    <section aria-label="Đánh giá" className={cardClass("flex items-center gap-4 p-4")}>
      <div className="flex shrink-0 flex-col items-center rounded-xl bg-son px-4 py-2 text-on-son">
        <p className="font-serif text-3xl font-semibold leading-none">
          <span>{ratingScore(value)}</span>
          <span className="text-base font-normal">/5</span>
        </p>
        <p className="mt-1 text-xs font-semibold">{ratingWord(value)}</p>
      </div>
      <p className="text-sm text-muc-soft">{reviews}</p>
    </section>
  );
}

function PlaceDetail({ place }: { place: Place }) {
  const note = placeNote(place);
  const phone = placePhone(place);
  const priceKnown = place.price_status === "FREE_CLAIM" || place.price_min_vnd !== null || place.price_max_vnd !== null;
  const guide = place.guide ?? null;
  const summary = place.summary ? splitParagraphs(place.summary) : [];
  const bullets = highlights(place);
  const teaser = introTeaser(place);

  return (
    <article className="space-y-6">
      <div className={cardClass()}>
        <div className="relative">
          <PlacePhoto
            poiId={place.id}
            name={place.name}
            category={place.category}
            size="lg"
            aspect="banner"
            illustrative={isIllustrative(place)}
          />
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-muc/85 via-muc/20 to-transparent" />
          <h1 className="absolute inset-x-4 bottom-3 font-serif text-2xl font-semibold leading-snug text-nga [overflow-wrap:anywhere] md:text-3xl">
            {place.name}
          </h1>
        </div>
        <Ornament />
        <PhotoCredit photo={place.photo} />
        <div className="flex flex-wrap items-center gap-3 p-4">
          <CategoryChip category={place.category} />
          <Link to="/" state={{ prefill: askAssistantText(place.name) }} className={buttonClass("primary", "sm")}>
            Hỏi trợ lý về nơi này
          </Link>
        </div>
      </div>

      <div className="gap-6 md:grid md:grid-cols-[minmax(0,1fr)_minmax(260px,360px)] md:items-start">
        <div className="min-w-0 space-y-3">
          {place.rating_value !== null ? (
            <RatingCard value={place.rating_value} count={place.rating_count} source={place.rating_source} />
          ) : null}

          {bullets.length > 0 ? (
            <section aria-labelledby="highlights-heading" className={cardClass("p-4")}>
              <SectionHeading id="highlights-heading" className="text-base md:text-lg">
                Điểm nổi bật
              </SectionHeading>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-muc">
                {bullets.map((bullet, index) => (
                  <li key={index}>{bullet}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section aria-labelledby="info-heading" className={cardClass()}>
            <details open className="group">
              <summary className={SUMMARY_CLASS}>
                <SectionHeading id="info-heading" className="text-base md:text-lg">
                  Thông tin hữu ích
                </SectionHeading>
                <Chevron />
              </summary>
              <div className="px-4 pb-4">
                <dl className="divide-y divide-vien">
                  {place.address ? <Field label="Địa chỉ">{place.address}</Field> : null}
                  {place.opening_hours_raw ? <Field label="Giờ mở cửa">{openingHoursText(place)}</Field> : null}
                  {priceKnown ? <Field label="Giá">{describePrice(place)}</Field> : null}
                  {place.visit_minutes !== null && !isFoodPlace(place) ? (
                    <Field label="Thời gian tham quan">{formatMinutes(place.visit_minutes)}</Field>
                  ) : null}
                  {phone ? (
                    <Field label="Điện thoại">
                      <a href={`tel:${phone.tel}`} className={LINK}>
                        {phone.display}
                      </a>
                      {phone.note ? <span className="text-muc-soft"> · {phone.note}</span> : null}
                    </Field>
                  ) : null}
                </dl>
                {note ? <p className="pt-2 text-xs leading-relaxed text-muc-soft">{note}</p> : null}
              </div>
            </details>
          </section>
        </div>

        <aside className="mt-6 md:mt-0 md:sticky md:top-4 md:self-start">
          <PlacesMap places={[place]} heightClass="h-64" />
        </aside>
      </div>

      <section aria-labelledby="intro-heading" className={cardClass()}>
        <details className="group">
          <summary className={SUMMARY_CLASS}>
            <div className="min-w-0">
              <SectionHeading id="intro-heading" className="text-base md:text-lg">
                Giới thiệu
              </SectionHeading>
              <span className="mt-1 block text-sm leading-relaxed text-muc-soft group-open:hidden">{teaser}</span>
            </div>
            <Chevron />
          </summary>
          <div
            data-testid="intro-body"
            className="space-y-3 px-4 pb-4 text-sm leading-relaxed text-muc [overflow-wrap:anywhere] sm:px-6 sm:pb-6"
          >
            {guide ? (
              <>
                {splitParagraphs(guide.text).map((paragraph, index) => (
                  <p key={`lead-${index}`}>{paragraph}</p>
                ))}
                {(guide.sections ?? []).map((section, sectionIndex) => (
                  <div key={`section-${sectionIndex}`} className="space-y-3">
                    <h3 className="pt-2 font-serif text-base font-semibold text-son">{section.heading}</h3>
                    {splitParagraphs(section.text).map((paragraph, index) => (
                      <p key={index}>{paragraph}</p>
                    ))}
                  </div>
                ))}
                <p className="pt-1 text-xs text-muc-soft">
                  Theo Wikipedia tiếng Việt ({guide.license}) ·{" "}
                  <a href={guide.url} target="_blank" rel="noopener noreferrer" className={LINK}>
                    bài gốc
                  </a>
                </p>
              </>
            ) : null}

            {!guide && summary.length > 0 ? (
              <>
                {summary.map((paragraph, index) => (
                  <p key={index}>{paragraph}</p>
                ))}
                <p className="pt-1 text-xs text-muc-soft">Theo huetripo.hue.gov.vn</p>
              </>
            ) : null}

            {/* The article already introduces the place; the data paragraph is for places without one. */}
            {guide ? null : <p>{factualParagraph(place)}</p>}
          </div>
        </details>
      </section>

      <footer className="pb-4 text-xs text-muc-soft">
        Dữ liệu: {place.source}
        {place.source_url ? (
          <>
            {" · "}
            <a href={place.source_url} target="_blank" rel="noopener noreferrer" className={LINK}>
              Mở trang nguồn
            </a>
          </>
        ) : null}
      </footer>
    </article>
  );
}
