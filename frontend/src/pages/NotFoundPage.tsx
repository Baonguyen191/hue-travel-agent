import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6">
      <h1 className="text-xl font-semibold">Không tìm thấy trang</h1>
      <p className="mt-2 text-sm text-slate-600">Đường dẫn này không tồn tại.</p>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-teal-700 underline">
        Về trang chủ
      </Link>
    </section>
  );
}
