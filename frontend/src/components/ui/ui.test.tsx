import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button, CategoryChip, MockBadge, Notice, SectionHeading, buttonClass } from ".";

describe("ui kit", () => {
  it("renders a primary button by default in gold with dark text and type=button", () => {
    render(<Button>Duyệt</Button>);
    const button = screen.getByRole("button", { name: "Duyệt" });
    expect(button).toHaveAttribute("type", "button");
    expect(button.className).toContain("bg-kim");
    expect(button.className).toContain("text-muc");
    expect(button.className).not.toContain("bg-son");
  });

  it("gives outline and secondary variants their own colours", () => {
    expect(buttonClass("outline")).toContain("border-son");
    expect(buttonClass("secondary")).toContain("bg-kim-soft");
  });

  it("labels a category chip in Vietnamese", () => {
    render(<CategoryChip category="historic" />);
    expect(screen.getByText("Di tích")).toBeInTheDocument();
  });

  it("shows the simulated badge text", () => {
    render(<MockBadge />);
    expect(screen.getByText("MÔ PHỎNG")).toBeInTheDocument();
  });

  it("passes role through on a notice", () => {
    render(
      <Notice variant="error" role="alert">
        Lỗi
      </Notice>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Lỗi");
  });

  it("renders the heading level asked for in the serif font", () => {
    render(<SectionHeading as="h2">Ngày 1</SectionHeading>);
    const heading = screen.getByRole("heading", { level: 2, name: "Ngày 1" });
    expect(heading.className).toContain("font-serif");
  });
});
