import { Link, useParams } from "react-router-dom";

/** Stub until the plan page is built: shows the thread id so the route can be checked. */
export function PlanStubPage() {
  const { threadId } = useParams();

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6">
      <h1 className="text-xl font-semibold">Kế hoạch</h1>
      <p className="mt-2 break-all text-sm text-slate-700">
        Mã kế hoạch: <code>{threadId}</code>
      </p>
      <p className="mt-2 text-sm text-slate-600">Trang lịch trình sẽ được hoàn thiện ở bước sau.</p>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-teal-700 underline">
        Quay lại nhập yêu cầu
      </Link>
    </section>
  );
}
