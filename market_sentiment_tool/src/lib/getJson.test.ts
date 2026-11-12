import { afterEach, describe, expect, it, vi } from "vitest";

import { getJson } from "@/lib/getJson";

/** getJson settles every read: a hung endpoint rejects as a timeout so the
 * page can show its unavailable state instead of spinning on "Loading…"
 * forever. */

describe("getJson", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("returns the parsed payload on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: 1 }),
      { status: 200, headers: { "Content-Type": "application/json" } })));
    await expect(getJson("/api/anything")).resolves.toEqual({ ok: 1 });
  });

  it("rejects with the server detail on a non-2xx answer", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }),
      { status: 503, headers: { "Content-Type": "application/json" } })));
    await expect(getJson("/api/anything")).rejects.toThrow("nope");
  });

  it("rejects as a timeout when the request hangs past the limit", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const pending = getJson("/api/hangs", 5_000);
    const assertion = expect(pending).rejects.toThrow("Request timed out after 5s");
    await vi.advanceTimersByTimeAsync(5_000);
    await assertion;
  });

  it("rejects as a timeout when the body stalls after the headers arrive", async () => {
    vi.useFakeTimers();
    // fetch resolves as soon as the headers land; the body read is what
    // stalls, and it rejects only when the abort signal fires.
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: () => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    }) as unknown as Response));
    const pending = getJson("/api/stalls", 5_000);
    const assertion = expect(pending).rejects.toThrow("Request timed out after 5s");
    await vi.advanceTimersByTimeAsync(5_000);
    await assertion;
  });
});
