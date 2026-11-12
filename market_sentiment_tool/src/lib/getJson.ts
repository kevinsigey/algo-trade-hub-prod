import { buildApiUrl } from "@/lib/api";

/** A hung endpoint must become the caller's error state, never an infinite
 * "Loading…": pages render an "unavailable" tile from a rejected read, but
 * only if the read actually settles (Nov 12: several pages spun forever
 * while a restarting server left requests hanging). */
export const GET_JSON_TIMEOUT_MS = 25_000;

/** GET one API path as JSON; a non-2xx answer becomes an Error carrying the server's `detail`. */
export async function getJson<T>(path: string, timeoutMs: number = GET_JSON_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(buildApiUrl(path), { signal: controller.signal });
  } catch (err) {
    if (controller.signal.aborted) {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
  const payload = await response.json();
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  return payload as T;
}
