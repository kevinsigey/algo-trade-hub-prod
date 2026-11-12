import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useApi } from "@/hooks/usePaperPortfolio";

// The live cycle (2026-11-12 redesign): with a refresh interval the hook
// refetches while visible, keeps the last good data through a failed
// refresh and marks it stale, and never polls without an interval.
describe("useApi live refresh", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("refetches on the cycle and keeps last data, marked stale, through a failure", async () => {
    vi.useFakeTimers();
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      if (calls === 3) throw new Error("boom");
      return new Response(JSON.stringify({ n: calls }), { status: 200 });
    }));
    const { result } = renderHook(() => useApi<{ n: number }>("/api/portfolio?book=main", 30_000));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.data).toEqual({ n: 1 });
    expect(result.current.lastUpdatedAt).not.toBeNull();

    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(result.current.data).toEqual({ n: 2 });
    expect(result.current.stale).toBe(false);

    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    // The failed refresh changed nothing on screen except the stale flag.
    expect(result.current.data).toEqual({ n: 2 });
    expect(result.current.stale).toBe(true);
    expect(result.current.error).toBeNull();
    expect(calls).toBe(3);
  });

  it("runs the initial read even in a hidden tab -- only polls are suppressed", async () => {
    vi.useFakeTimers();
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      return new Response(JSON.stringify({ n: calls }), { status: 200 });
    }));
    try {
      const { result } = renderHook(() => useApi<{ n: number }>("/api/portfolio/books", 30_000));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(result.current.data).toEqual({ n: 1 });
      // The poll turn is skipped while hidden.
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(calls).toBe(1);
    } finally {
      Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    }
  });

  it("does not poll without an interval", async () => {
    vi.useFakeTimers();
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      return new Response(JSON.stringify({ n: calls }), { status: 200 });
    }));
    const { result } = renderHook(() => useApi<{ n: number }>("/api/portfolio/books"));
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(result.current.data).toEqual({ n: 1 });
    expect(calls).toBe(1);
  });
});
