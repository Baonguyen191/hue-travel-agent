import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { api, errorMessage, isForbidden, isNotFound } from "../api/client";
import type { PlanRecord } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { Toast } from "../components/Toast";
import { TripRequestForm } from "../components/TripRequestForm";
import { WarningsPanel } from "../components/WarningsPanel";
import { LINK, Ornament, PILL, PlacePhoto, TONE_CLASS, buttonClass, cardClass } from "../components/ui";
import { formatDate } from "../lib/format";
import { toTripRequest, valuesFromTrip, type FormValues } from "../lib/tripForm";
import { effectiveStatus, isWaiting, statusLabel, statusTone, summarizeWarnings } from "../lib/plan";

/** What each plan tab receives from the layout. `reload` refetches the plan after a change. */
export interface PlanContext {
  threadId: string;
  record: PlanRecord;
  reload: () => void;
}

export function usePlan(): PlanContext {
  return useOutletContext<PlanContext>();
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; record: PlanRecord }
  | { status: "not-found" }
  | { status: "forbidden" }
  | { status: "error"; message: string };

export function heroPoi(record: PlanRecord): { poiId: string; name: string; category: string | null } | null {
  for (const day of record.payload.itinerary.days) {
    for (const event of day.events) {
      if (event.kind === "VISIT" && event.poi_id) return { poiId: event.poi_id, name: event.name, category: event.category };
    }
  }
  return null;
}

export function PlanLayout() {
  const { threadId = "" } = useParams();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const dismissToast = useCallback(() => setToast(null), []);
  const reload = useCallback(() => setReloadKey((key) => key + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    api.getPlan(threadId, controller.signal).then(
      (record) => setState({ status: "ready", record }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (isNotFound(error)) setState({ status: "not-found" });
        else if (isForbidden(error)) setState({ status: "forbidden" });
        else setState({ status: "error", message: errorMessage(error) });
      },
    );
    return () => controller.abort();
  }, [threadId, reloadKey]);

  if (state.status === "loading") {
    return <div role="status" aria-label="Đang tải kế hoạch" className="h-64 animate-pulse rounded-2xl bg-nga" />;
  }
  if (state.status === "not-found") {
    return (
      <section className={cardClass("p-6")}>
        <h1 className="font-serif text-xl font-semibold text-son">Không tìm thấy kế hoạch</h1>
        <p className="mt-2 text-sm text-muc-soft">Mã kế hoạch này không tồn tại hoặc đã bị xóa.</p>
      </section>
    );
  }
  if (state.status === "forbidden") {
    return (
      <section className={cardClass("p-6")}>
        <h1 className="font-serif text-xl font-semibold text-son">Kế hoạch thuộc người dùng khác</h1>
        <p className="mt-2 text-sm text-muc-soft">Hãy mở kế hoạch bằng đúng trình duyệt đã tạo ra nó.</p>
      </section>
    );
  }
  if (state.status === "error") return <ErrorBanner message={state.message} />;

  const record = state.record;
  const status = effectiveStatus(record);
  const waiting = isWaiting(record);
  const request = record.payload.request;
  const summary = summarizeWarnings(record);
  const hero = heroPoi(record);

  async function saveEdit(values: FormValues) {
    setSaving(true);
    setEditError(null);
    try {
      const next = await api.createOrEditPlan(threadId, toTripRequest(values, request));
      if (next.status !== "AWAITING_APPROVAL") {
        setEditError(`Kế hoạch không còn chờ duyệt (trạng thái: ${statusLabel(next.status)}).`);
        return;
      }
      setEditing(false);
      setToast(`Đã tạo phiên bản ${next.version}. Hãy duyệt lại phương án.`);
      reload();
    } catch (error) {
      setEditError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  const context: PlanContext = { threadId, record, reload };

  return (
    <div className="space-y-6">
      <header className={cardClass()}>
        <div className="relative">
          <PlacePhoto
            poiId={hero?.poiId ?? null}
            name={hero?.name ?? `${request.origin} → ${request.destination}`}
            category={hero?.category ?? "historic"}
            size="lg"
            aspect="16/9"
            className="max-h-72"
          />
          <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-muc/85 via-muc/25 to-transparent" />
          <div className="absolute inset-x-4 bottom-3 text-nga">
            <h1 className="font-serif text-2xl font-semibold md:text-3xl">
              {request.origin} → {request.destination}
            </h1>
            <p className="text-sm text-nga/90">
              {formatDate(request.start_date)} – {formatDate(request.end_date)} · {request.people} người · {request.rooms} phòng
            </p>
          </div>
        </div>
        <Ornament />
        <div className="flex flex-wrap items-center gap-2 p-3">
          <span className={`${PILL} ${TONE_CLASS[statusTone(status)]}`}>{statusLabel(status)}</span>
          <span className="text-xs text-muc-soft">Phiên bản v{record.version}</span>
          <span className="text-xs text-muc-soft">Mã kế hoạch {record.plan_id.slice(0, 8)}</span>
          {waiting && !editing ? (
            <button
              type="button"
              onClick={() => {
                setEditError(null);
                setEditing(true);
              }}
              className={`${buttonClass("outline", "sm")} ml-auto`}
            >
              Sửa yêu cầu
            </button>
          ) : null}
        </div>
      </header>

      {editing ? (
        <section aria-labelledby="edit-heading" className={cardClass("space-y-4 p-4 sm:p-6")}>
          <div>
            <h2 id="edit-heading" className="font-serif text-base font-semibold text-son">
              Sửa yêu cầu
            </h2>
            <p className="text-sm text-muc-soft">Lưu sẽ tạo phiên bản mới và cần duyệt lại.</p>
          </div>
          {editError ? <ErrorBanner message={editError} /> : null}
          <TripRequestForm
            initial={valuesFromTrip(request)}
            submitLabel="Lưu và tạo phiên bản mới"
            pending={saving}
            onSubmit={saveEdit}
          />
          <button type="button" onClick={() => setEditing(false)} disabled={saving} className={LINK}>
            Hủy sửa
          </button>
        </section>
      ) : null}

      <WarningsPanel summary={summary} />

      <nav aria-label="Các mục kế hoạch" className="flex flex-wrap gap-2">
        <NavLink
          to={`/plan/${threadId}`}
          end
          className={({ isActive }) => `rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${isActive ? "bg-son text-on-son ring-son" : "bg-nga text-son ring-vien hover:ring-kim"}`}
        >
          Lịch trình
        </NavLink>
        <NavLink
          to={`/plan/${threadId}/budget`}
          className={({ isActive }) => `rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${isActive ? "bg-son text-on-son ring-son" : "bg-nga text-son ring-vien hover:ring-kim"}`}
        >
          Ngân sách &amp; duyệt
        </NavLink>
        <NavLink
          to={`/plan/${threadId}/booking`}
          className={({ isActive }) => `rounded-full px-4 py-1.5 text-sm font-semibold ring-1 ${isActive ? "bg-son text-on-son ring-son" : "bg-nga text-son ring-vien hover:ring-kim"}`}
        >
          Đặt chỗ
        </NavLink>
      </nav>

      <Outlet context={context} />

      {toast ? <Toast message={toast} onDismiss={dismissToast} /> : null}
    </div>
  );
}
