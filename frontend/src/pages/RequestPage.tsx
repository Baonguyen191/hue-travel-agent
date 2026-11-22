import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { CheckpointState, ParsedTrip, TripRequest } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { SectionHeading, buttonClass, cardClass, Notice } from "../components/ui";
import { PlanProgress, TraceList } from "../components/PlanProgress";
import { TripRequestForm } from "../components/TripRequestForm";
import { newUuid } from "../lib/ids";
import { EMPTY_VALUES, toTripRequest, valuesFromParsed, type FormValues } from "../lib/tripForm";
import { translateWarnings } from "../lib/warnings";

export const DOD_SENTENCE =
  "Tôi đi Huế 3 ngày 2 đêm từ 05/12, xuất phát Hà Nội, 2 người, ngân sách 8 triệu, thích di tích và đặc sản";

const SOURCE_LABEL: Record<string, string> = {
  RULES: "Phân tích bằng quy tắc tiếng Việt",
  "RULES+OPENAI": "Quy tắc tiếng Việt, bổ sung bằng OpenAI",
  FORM_FALLBACK: "Không đọc được yêu cầu, hãy nhập tay",
};

interface FormSeed {
  key: number;
  values: FormValues;
}

/** Request screen: describe the trip, review the parsed form, then create the plan. */
export function RequestPage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsed, setParsed] = useState<ParsedTrip | null>(null);
  const [base, setBase] = useState<TripRequest | null>(null);
  const [seed, setSeed] = useState<FormSeed>({ key: 0, values: EMPTY_VALUES });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [failure, setFailure] = useState<CheckpointState | null>(null);

  async function parse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.parseTrip(text.trim());
      setParsed(result);
      setBase(result.request);
      setSeed((current) => ({ key: current.key + 1, values: valuesFromParsed(result) }));
      setFailure(null);
      setSubmitError(null);
    } catch (error) {
      setParseError(errorMessage(error));
    } finally {
      setParsing(false);
    }
  }

  async function createPlan(values: FormValues) {
    const threadId = newUuid();
    setSubmitting(true);
    setSubmitError(null);
    setFailure(null);
    try {
      const state = await api.createOrEditPlan(threadId, toTripRequest(values, base));
      if (state.status === "AWAITING_APPROVAL") {
        navigate(`/plan/${threadId}`);
        return;
      }
      setFailure(state);
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <SectionHeading as="h1">Lập kế hoạch chuyến đi</SectionHeading>
        <p className="text-sm text-muc-soft">
          Mô tả chuyến đi bằng tiếng Việt. Hệ thống sẽ điền sẵn biểu mẫu để bạn kiểm tra trước khi tạo lịch trình.
        </p>
      </header>

      <section aria-labelledby="describe-heading" className={cardClass("space-y-3 p-4 sm:p-6")}>
        <SectionHeading id="describe-heading">1. Mô tả chuyến đi</SectionHeading>
        <form onSubmit={parse} className="space-y-3">
          <div>
            <label htmlFor="request-text" className="block text-sm font-medium text-muc">
              Yêu cầu của bạn
            </label>
            <textarea
              id="request-text"
              rows={4}
              value={text}
              placeholder={DOD_SENTENCE}
              onChange={(event) => setText(event.target.value)}
              disabled={parsing || submitting}
              className="mt-1 w-full rounded-xl border border-vien bg-nga px-3 py-2 text-base text-muc focus:border-son focus:outline-none focus:ring-2 focus:ring-son/30 disabled:bg-giay"
            />
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muc-soft">Bạn cũng có thể bỏ qua bước này và điền trực tiếp biểu mẫu bên dưới.</p>
            <button
              type="submit"
              disabled={text.trim() === "" || parsing || submitting}
              className={buttonClass("outline")}
            >
              {parsing ? "Đang phân tích…" : "Phân tích yêu cầu"}
            </button>
          </div>
        </form>
        {parseError ? <ErrorBanner message={parseError} /> : null}
        {parsed ? (
          <div className="space-y-2 text-sm text-muc-soft">
            <p>
              Nguồn phân tích: <span className="font-medium text-muc">{SOURCE_LABEL[parsed.source] ?? parsed.source}</span>
            </p>
            {parsed.notes.length > 0 ? (
              <ul className="list-disc space-y-1 pl-5 text-muc">
                {parsed.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="form-heading" className={cardClass("space-y-4 p-4 sm:p-6")}>
        <SectionHeading id="form-heading">2. Kiểm tra và chỉnh sửa</SectionHeading>
        <TripRequestForm
          key={seed.key}
          initial={seed.values}
          missing={parsed?.missing_fields ?? []}
          submitLabel={submitting ? "Đang tạo…" : "Tạo lịch trình"}
          pending={submitting}
          onSubmit={createPlan}
        />
        <PlanProgress active={submitting} />
        {submitError ? <ErrorBanner message={submitError} /> : null}
        {failure ? <PlanFailure state={failure} /> : null}
      </section>
    </div>
  );
}

function PlanFailure({ state }: { state: CheckpointState }) {
  const reasons = translateWarnings(state.attempts.length > 0 ? state.attempts : state.warnings);
  return (
    <Notice variant="error" role="alert" aria-labelledby="failure-heading" className="space-y-3">
      <h3 id="failure-heading" className="font-serif text-base font-semibold text-son">
        Chưa tạo được lịch trình hợp lệ
      </h3>
      {state.status === "FAILED_VALIDATION" ? (
        <p className="text-sm text-muc">
          Hệ thống đã thử lại {state.retries} lần nhưng lịch trình vẫn chưa đạt. Hãy điều chỉnh yêu cầu (ngân sách, số ngày,
          sở thích) rồi thử lại.
        </p>
      ) : (
        <p className="text-sm text-muc">Trạng thái không mong đợi: {state.status}.</p>
      )}
      {reasons.length > 0 ? (
        <div>
          <p className="text-sm font-medium text-muc">Lý do từ hệ thống:</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muc">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div>
        <p className="mb-1 text-sm font-medium text-muc">Các bước đã chạy:</p>
        <TraceList trace={state.trace} />
      </div>
    </Notice>
  );
}
