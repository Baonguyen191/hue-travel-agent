import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CategoryChips } from "./CategoryChips";

describe("CategoryChips", () => {
  it("renders 'Tất cả' plus the eight categories, all as toggle buttons", () => {
    render(<CategoryChips value={null} onChange={() => {}} />);

    const group = screen.getByRole("group", { name: "Loại địa điểm" });
    const chips = group.querySelectorAll("button");
    expect(chips).toHaveLength(9);
    for (const label of ["Tất cả", "Quán ăn", "Cà phê", "Di tích", "Điểm tham quan", "Chợ", "Tôn giáo", "Công viên", "Bảo tàng"]) {
      expect(screen.getByRole("button", { name: label })).toHaveAttribute("aria-pressed");
    }
  });

  it("marks the selected chip as pressed", () => {
    render(<CategoryChips value="historic" onChange={() => {}} />);

    expect(screen.getByRole("button", { name: "Di tích" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Tất cả" })).toHaveAttribute("aria-pressed", "false");
  });

  it("reports the chosen category, and null for 'Tất cả'", async () => {
    const onChange = vi.fn();
    render(<CategoryChips value="historic" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: "Cà phê" }));
    await userEvent.click(screen.getByRole("button", { name: "Tất cả" }));

    expect(onChange).toHaveBeenNthCalledWith(1, "cafe");
    expect(onChange).toHaveBeenNthCalledWith(2, null);
  });
});
