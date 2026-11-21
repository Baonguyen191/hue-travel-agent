import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getUserId, shortUserId } from "../lib/userId";

const NAV_LINK = "rounded-md px-3 py-2 text-sm font-medium transition-colors";

function navClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_LINK} ${isActive ? "bg-teal-700 text-white" : "text-slate-700 hover:bg-slate-200"}`;
}

export function Layout() {
  const [userId] = useState(() => getUserId());

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-col gap-3 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-col gap-1 md:flex-row md:items-center md:gap-6">
            <span className="text-lg font-semibold text-teal-800">Hue Travel</span>
            <nav aria-label="Chính" className="flex flex-wrap gap-2">
              <NavLink to="/" end className={navClass}>
                Lập kế hoạch
              </NavLink>
              <NavLink to="/explore" className={navClass}>
                Khám phá Huế
              </NavLink>
            </nav>
          </div>
          <span className="text-xs text-slate-500">
            Người dùng thử: {shortUserId(userId)} — chưa phải đăng nhập
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <p className="mx-auto max-w-5xl px-4 py-4 text-xs leading-relaxed text-slate-600">
          Xe, khách sạn và đặt chỗ là <strong>MÔ PHỎNG</strong>. Dữ liệu địa điểm: huetripo.hue.gov.vn (giấy phép
          chưa rõ).
        </p>
      </footer>
    </div>
  );
}
