import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ParsedTrip } from "../api/types";
import parseDod from "../test/fixtures/parse-dod.json";
import parseMissing from "../test/fixtures/parse-missing.json";
import { EMPTY_VALUES, valuesFromParsed, type FormValues } from "../lib/tripForm";
import { TripRequestForm } from "./TripRequestForm";

const dodValues = valuesFromParsed(parseDod as ParsedTrip);

function renderForm(initial: FormValues, options: { missing?: string[]; onSubmit?: (values: FormValues) => void; pending?: boolean } = {}) {
  const onSubmit = options.onSubmit ?? vi.fn();
  render(
    <TripRequestForm
      initial={initial}
      missing={options.missing}
      submitLabel="Tạo lịch trình"
      pending={options.pending}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit, submit: () => screen.getByRole("button", { name: "Tạo lịch trình" }) };
}

describe("TripRequestForm", () => {
  it("prefills the fields and enables submit when the trip is complete", () => {
    const { submit } = renderForm(dodValues);

    expect(screen.getByLabelText("Điểm xuất phát")).toHaveValue("Hà Nội");
    expect(screen.getByLabelText("Điểm đến")).toHaveValue("Huế");
    expect(screen.getByLabelText("Ngày đi")).toHaveValue("2026-12-05");
    expect(screen.getByLabelText("Ngày về")).toHaveValue("2026-12-07");
    expect(screen.getByLabelText("Số người")).toHaveValue(2);
    expect(screen.getByLabelText("Ngân sách (VND)")).toHaveValue(8000000);
    expect(screen.getByText("Tương đương 8.000.000 ₫. Ngân sách là ước tính để so sánh các phương án.")).toBeInTheDocument();
    expect(submit()).toBeEnabled();
  });

  it("highlights missing fields in red with a note and keeps submit disabled", () => {
    const parsed = parseMissing as ParsedTrip;
    renderForm(valuesFromParsed(parsed), { missing: parsed.missing_fields });

    const origin = screen.getByLabelText("Điểm xuất phát");
    expect(origin).toHaveAttribute("aria-invalid", "true");
    expect(origin).toHaveClass("border-red-500");
    expect(screen.getByText("Nhập điểm xuất phát.")).toBeInTheDocument();
    expect(screen.getByText("Chọn ngày đi.")).toBeInTheDocument();
    expect(screen.getByText("Chọn ngày về.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Còn thiếu: điểm xuất phát, ngày đi, ngày về.");
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeDisabled();
  });

  it("does not show a missing field's error as soon as the user fills it", async () => {
    const parsed = parseMissing as ParsedTrip;
    renderForm(valuesFromParsed(parsed), { missing: parsed.missing_fields });

    await userEvent.type(screen.getByLabelText("Điểm xuất phát"), "Hà Nội");

    expect(screen.getByLabelText("Điểm xuất phát")).toHaveAttribute("aria-invalid", "false");
    expect(screen.queryByText("Nhập điểm xuất phát.")).not.toBeInTheDocument();
  });

  it("shows an error for a touched field and blocks submit until it is valid", async () => {
    renderForm({ ...dodValues, people: "" });

    await userEvent.click(screen.getByLabelText("Số người"));
    await userEvent.tab();

    expect(screen.getByText("Số người từ 1 đến 20.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeDisabled();

    await userEvent.clear(screen.getByLabelText("Số người"));
    await userEvent.type(screen.getByLabelText("Số người"), "3");

    expect(screen.queryByText("Số người từ 1 đến 20.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeEnabled();
  });

  it("rejects a return date that is not after the departure date", async () => {
    renderForm({ ...dodValues, endDate: "2026-12-05" });

    await userEvent.click(screen.getByLabelText("Ngày về"));
    await userEvent.tab();

    expect(screen.getByText("Ngày về phải sau ngày đi.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeDisabled();
  });

  it("adds preferences with the button or Enter, removes them, and never submits from Enter", async () => {
    const { onSubmit } = renderForm({ ...dodValues, preferences: [] });
    const draft = screen.getByLabelText("Sở thích");

    await userEvent.type(draft, "chợ đêm{Enter}");
    await userEvent.type(draft, "ẩm thực");
    await userEvent.click(screen.getByRole("button", { name: "Thêm" }));

    const list = screen.getByRole("list", { name: "Sở thích đã chọn" });
    expect(within(list).getByText("chợ đêm")).toBeInTheDocument();
    expect(within(list).getByText("ẩm thực")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Xóa sở thích chợ đêm" }));
    expect(within(list).queryByText("chợ đêm")).not.toBeInTheDocument();
  });

  it("toggles categories as checkboxes, and sends them with the request", async () => {
    const onSubmit = vi.fn();
    renderForm({ ...dodValues, categories: [] }, { onSubmit });

    await userEvent.click(screen.getByRole("checkbox", { name: "Quán ăn" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Chợ" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Chợ" }));
    await userEvent.click(screen.getByRole("button", { name: "Tạo lịch trình" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].categories).toEqual(["restaurant"]);
  });

  it("disables every control while a request is pending", () => {
    renderForm(dodValues, { pending: true });

    expect(screen.getByLabelText("Điểm xuất phát")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeDisabled();
  });

  it("keeps the budget empty and valid when the user has not given one", () => {
    renderForm({ ...EMPTY_VALUES, origin: "Hà Nội", startDate: "2026-12-05", endDate: "2026-12-07", people: "2" });

    expect(screen.getByLabelText("Ngân sách (VND)")).toHaveValue(null);
    expect(screen.getByText("Có thể để trống nếu chưa có ngân sách.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tạo lịch trình" })).toBeEnabled();
  });

  it("submits the values as typed when the form is valid", () => {
    const onSubmit = vi.fn();
    renderForm(dodValues, { onSubmit });

    fireEvent.submit(screen.getByRole("button", { name: "Tạo lịch trình" }).closest("form")!);

    expect(onSubmit).toHaveBeenCalledWith(dodValues);
  });
});
