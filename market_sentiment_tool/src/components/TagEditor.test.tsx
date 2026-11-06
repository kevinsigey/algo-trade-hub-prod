import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TagEditor } from "@/components/TagEditor";

vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: { access_token: "jwt" } } }) } } }));

afterEach(() => vi.unstubAllGlobals());

describe("TagEditor", () => {
  it("adds a tag on Enter and removes one, saving the server's cleaned list each time", async () => {
    const f = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const tags = JSON.parse(String(init?.body)).tags as string[];
      return new Response(JSON.stringify({ id: 7, tags: tags.map((t) => t.trim()) }), { status: 200 });
    });
    vi.stubGlobal("fetch", f);
    render(<TagEditor ideaId={7} initial={["Defensive"]} />);
    fireEvent.change(screen.getByLabelText("Add a tag"), { target: { value: " Rates " } });
    fireEvent.keyDown(screen.getByLabelText("Add a tag"), { key: "Enter" });
    expect(await screen.findByText("Rates")).toBeInTheDocument();
    expect(String(f.mock.calls[0][0])).toContain("/api/workshop/ideas/7/tags");
    expect(f.mock.calls[0][1]?.method).toBe("PUT");
    fireEvent.click(screen.getByRole("button", { name: "Remove tag Defensive" }));
    await waitFor(() => expect(screen.queryByText("Defensive")).toBeNull());
  });

  it("says so when a save fails and keeps the last saved tags", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "no" }), { status: 500 })));
    render(<TagEditor ideaId={7} initial={["Defensive"]} />);
    fireEvent.change(screen.getByLabelText("Add a tag"), { target: { value: "Rates" } });
    fireEvent.keyDown(screen.getByLabelText("Add a tag"), { key: "Enter" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't save/i);
    expect(screen.queryByText("Rates")).toBeNull();
    expect(screen.getByText("Defensive")).toBeInTheDocument();
  });
});
