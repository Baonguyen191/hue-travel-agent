import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useOutletContext, useParams } from "react-router-dom";
import { api, errorMessage, isForbidden, isNotFound } from "../api/client";
import type { PlanRecord } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { Toast } from "../components/Toast";
import { TripRequestForm } from "../components/TripRequestForm";
import { WarningsPanel } from "../components/WarningsPanel";
import { formatDate } from "../lib/format";
import { toTripRequest, valuesFromTrip, type FormValues } from "../lib/tripForm";
import { effectiveStatus, isWaiting, statusLabel, statusTone, summarizeWarnings, type StatusTone } from "../lib/plan";

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

const TONE_CLASS: Record<StatusTone, string> = {
  approved: "bg-emerald-100 text-emerald-900 ring-emerald-300",
  waiting: "bg-amber-100 text-amber-900 ring-amber-300",
  failed: "bg-red-100 text-red-900 ring-red-300",
  neutral: "bg-slate-100 text-slate-800 ring-slate-300",
};

const TAB_CLASS = "border-b-2 px-1 pb-2 text-sm font-medium";

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
    return <div role="status" aria-label="Đang tải kế hoạch" className="h-64 animate-pulse rounded-lg bg-slate-100" />;
  }
  if (state.status === "not-found") {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="text-xl font-semibold">Không tìm thấy kế hoạch</h1>
        <p className="mt-2 text-sm text-slate-600">Mã kế hoạch này không tồn tại hoặc đã bị xóa.</p>
      </section>
    );
  }
  if (state.status === "forbidden") {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="text-xl font-semibold">Kế hoạch thuộc người dùng khác</h1>
        <p className="mt-2 text-sm text-slate-600">Hãy mở kế hoạch bằng đúng trình duyệt đã tạo ra nó.</p>
      </section>
    );
  }
  if (state.status === "error") return <ErrorBanner message={state.message} />;

  const record = state.record;
  const status = effectiveStatus(record);
  const waiting = isWaiting(record);
  const request = record.payload.request;
  const summary = summarizeWarnings(record);

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
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${TONE_CLASS[statusTone(status)]}`}>
            {statusLabel(status)}
          </span>
          <span className="text-xs text-slate-600">Phiên bản v{record.version}</span>
          <span className="text-xs text-slate-500">Mã kế hoạch {record.plan_id.slice(0, 8)}</span>
        </div>
        <h1 className="text-2xl font-semibold">
          {request.origin} → {request.destination}
        </h1>
        <p className="text-sm text-slate-600">
          {formatDate(request.start_date)} – {formatDate(request.end_date)} · {request.people} người · {request.rooms} phòng
        </p>
        {waiting && !editing ? (
          <button
            type="button"
            onClick={() => {
              setEditError(null);
              setEditing(true);
            }}
            className="rounded-md border border-teal-700 px-3 py-1.5 text-sm font-medium text-teal-800 hover:bg-teal-50"
          >
            Sửa yêu cầu
          </button>
        ) : null}
      </header>

      {editing ? (
        <section aria-labelledby="edit-heading" className="space-y-4 rounded-lg border border-slate-200 bg-white p-4 sm:p-6">
          <div>
            <h2 id="edit-heading" className="text-base font-semibold">
              Sửa yêu cầu
            </h2>
            <p className="text-sm text-slate-600">Lưu sẽ tạo phiên bản mới và cần duyệt lại.</p>
          </div>
          {editError ? <ErrorBanner message={editError} /> : null}
          <TripRequestForm
            initial={valuesFromTrip(request)}
            submitLabel="Lưu và tạo phiên bản mới"
            pending={saving}
            onSubmit={saveEdit}
          />
          <button type="button" onClick={() => setEditing(false)} disabled={saving} className="text-sm font-medium text-slate-700 underline">
            Hủy sửa
          </button>
        </section>
      ) : null}

      <WarningsPanel summary={summary} />

      <nav aria-label="Các mục kế hoạch" className="flex gap-5 border-b border-slate-200">
        <NavLink
          to={`/plan/${threadId}`}
          end
          className={({ isActive }) => `${TAB_CLASS} ${isActive ? "border-teal-700 text-teal-900" : "border-transparent text-slate-600"}`}
        >
          Lịch trình
        </NavLink>
        <NavLink
          to={`/plan/${threadId}/budget`}
          className={({ isActive }) => `${TAB_CLASS} ${isActive ? "border-teal-700 text-teal-900" : "border-transparent text-slate-600"}`}
        >
          Ngân sách &amp; duyệt
        </NavLink>
        <NavLink
          to={`/plan/${threadId}/booking`}
          className={({ isActive }) => `${TAB_CLASS} ${isActive ? "border-teal-700 text-teal-900" : "border-transparent text-slate-600"}`}
        >
          Đặt chỗ
        </NavLink>
      </nav>

      <Outlet context={context} />

      {toast ? <Toast message={toast} onDismiss={dismissToast} /> : null}
    </div>
  );
}
