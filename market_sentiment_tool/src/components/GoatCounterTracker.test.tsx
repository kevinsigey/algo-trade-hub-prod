import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";

import { GoatCounterTracker } from "@/components/GoatCounterTracker";

function Go({ to }: { to: string }) {
  const navigate = useNavigate();
  useEffect(() => {
    navigate(to);
  }, [navigate, to]);
  return null;
}

afterEach(() => {
  delete window.goatcounter;
});

describe("GoatCounterTracker", () => {
  it("skips the landing view and counts later navigations", () => {
    const count = vi.fn();
    window.goatcounter = { count };
    render(
      <MemoryRouter initialEntries={["/macro"]}>
        <GoatCounterTracker />
        <Routes>
          <Route path="/macro" element={<Go to="/oil" />} />
          <Route path="/oil" element={null} />
        </Routes>
      </MemoryRouter>,
    );
    expect(count).toHaveBeenCalledTimes(1);
    expect(count).toHaveBeenCalledWith({ path: "/oil" });
  });

  it("no-ops when count.js never loaded (jsdom, blockers)", () => {
    expect(() =>
      render(
        <MemoryRouter initialEntries={["/macro"]}>
          <GoatCounterTracker />
          <Routes>
            <Route path="/macro" element={<Go to="/oil" />} />
            <Route path="/oil" element={null} />
          </Routes>
        </MemoryRouter>,
      ),
    ).not.toThrow();
  });
});
