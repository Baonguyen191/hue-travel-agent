import { Link } from "react-router-dom";
import { PlaceIllustration, buttonClass, cardClass } from "../components/ui";

export function NotFoundPage() {
  return (
    <section className={cardClass("p-8 text-center")}>
      <PlaceIllustration category="historic" className="mx-auto mb-4 h-32 w-48 rounded-xl" />
      <h1 className="font-serif text-xl font-semibold text-son">Không tìm thấy trang</h1>
      <p className="mt-2 text-sm text-muc-soft">Đường dẫn này không tồn tại.</p>
      <Link to="/" className={`${buttonClass("outline")} mt-4`}>
        Về trang chủ
      </Link>
    </section>
  );
}
