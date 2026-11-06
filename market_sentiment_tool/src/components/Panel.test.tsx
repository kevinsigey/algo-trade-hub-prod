import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { Panel } from "@/components/Panel";

describe("Panel", () => {
  it("shows the summary, opens the full view on demand and closes on Escape", () => {
    render(<Panel title="Positions" full={<p>every row</p>}><p>top rows</p></Panel>);
    expect(screen.getByText("top rows")).toBeInTheDocument();
    expect(screen.queryByText("every row")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Positions in full" }));
    const dialog = screen.getByRole("dialog", { name: "Positions" });
    expect(dialog).toHaveTextContent("every row");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("has no open control when there is nothing more to show", () => {
    render(<Panel title="Movers"><p>all of it</p></Panel>);
    expect(screen.queryByRole("button", { name: /in full/ })).toBeNull();
  });
});

describe("Panel full view and the keyboard", () => {
  it("keeps Tab inside the open view, wrapping from the last control to the first", () => {
    render(<Panel title="Picks" full={<a href="#x">last link</a>}><p>summary</p></Panel>);
    fireEvent.click(screen.getByRole("button", { name: "Open Picks in full" }));
    const dialog = screen.getByRole("dialog", { name: "Picks" });
    const close = screen.getByRole("button", { name: "Close" });
    const last = screen.getByText("last link");
    last.focus();
    fireEvent.keyDown(dialog, { key: "Tab" });
    expect(document.activeElement).toBe(close);
    close.focus();
    fireEvent.keyDown(dialog, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
