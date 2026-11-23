import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Layout } from "./Layout";

describe("layout header", () => {
  it("is cream with dark text, not a son bar", () => {
    render(
      <MemoryRouter>
        <Layout />
      </MemoryRouter>,
    );
    const header = screen.getByRole("banner");
    expect(header.className).not.toContain("bg-son");
    expect(header.className).toContain("bg-nga");
    expect(header.className).toContain("text-muc");
  });
});
