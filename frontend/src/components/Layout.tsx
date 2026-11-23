import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getUserId, shortUserId } from "../lib/userId";
import { Ornament } from "./ui";

const NAV_LINK = "border-b-2 px-1 py-1 text-sm font-medium transition-colors";

function navClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_LINK} ${isActive ? "border-kim text-son" : "border-transparent text-muc-soft hover:text-son"}`;
}

export function Layout() {
  const [userId] = useState(() => getUserId());

  return (
    <div className="flex min-h-screen flex-col bg-giay">
      <header className="bg-nga text-muc">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-col gap-1 md:flex-row md:items-center md:gap-8">
            <span className="font-serif text-xl font-bold tracking-wide text-son">Hue Travel</span>
            <nav aria-label="Chính" className="flex flex-wrap gap-5">
              <NavLink to="/" end className={navClass}>
                Trò chuyện
              </NavLink>
              <NavLink to="/explore" className={navClass}>
                Khám phá Huế
              </NavLink>
            </nav>
          </div>
          <span className="text-xs text-muc-soft">Người dùng thử: {shortUserId(userId)} — chưa phải đăng nhập</span>
        </div>
      </header>
      <Ornament />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-vien bg-nga">
        <p className="mx-auto max-w-5xl px-4 py-4 text-xs leading-relaxed text-muc-soft">
          Xe, khách sạn và đặt chỗ là <strong>MÔ PHỎNG</strong>. Dữ liệu địa điểm: huetripo.hue.gov.vn (giấy phép
          chưa rõ).
        </p>
      </footer>
    </div>
  );
}
