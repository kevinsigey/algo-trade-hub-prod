import { useCallback, useEffect, useState } from "react";
import { KeyRound } from "lucide-react";

import { adminJson } from "@/lib/workshop";

// Machine API keys (phase-2 spec §1, step 1): the issue/revoke UI. The key is shown exactly
// once, in the banner after creation -- only its hash is stored, so there is nothing to
// "view" later. No /api/v1 order routes exist yet; this page is the lifecycle and the audit
// trail, shipped ahead of them on purpose.

type ApiKey = {
  id: number;
  label: string;
  scopes: string[];
  max_qty: number;
  max_notional: number;
  daily_cap: number;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

type KeyEvent = {
  id: number;
  at: string;
  route: string;
  client_order_id: string | null;
  outcome: string;
  detail: string | null;
};

const ALL_SCOPES = ["orders:place", "orders:read", "portfolio:read"] as const;

function fmt(ts: string | null): string {
  if (!ts) return "never";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

export default function MachineKeys() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [scopes, setScopes] = useState<string[]>(["orders:place"]);
  const [maxQty, setMaxQty] = useState(100);
  const [maxNotional, setMaxNotional] = useState(25000);
  const [dailyCap, setDailyCap] = useState(50);
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState<number | null>(null);
  const [eventsFor, setEventsFor] = useState<number | null>(null);
  const [events, setEvents] = useState<KeyEvent[] | null>(null);

  const load = useCallback(async () => {
    try {
      const body = await adminJson<{ keys: ApiKey[] }>("/api/admin/keys");
      setKeys(body.keys);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load keys");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setError(null);
    try {
      const body = await adminJson<ApiKey & { key: string }>("/api/admin/keys", {
        method: "POST",
        body: JSON.stringify({ label, scopes, max_qty: maxQty, max_notional: maxNotional, daily_cap: dailyCap }),
      });
      setFreshKey(body.key);
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the key");
    }
  };

  const revoke = async (id: number) => {
    try {
      await adminJson(`/api/admin/keys/${id}/revoke`, { method: "POST" });
      setConfirmRevoke(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not revoke the key");
    }
  };

  const toggleEvents = async (id: number) => {
    if (eventsFor === id) {
      setEventsFor(null);
      setEvents(null);
      return;
    }
    setEventsFor(id);
    setEvents(null);
    try {
      const body = await adminJson<{ events: KeyEvent[] }>(`/api/admin/keys/${id}/events`);
      setEvents(body.events);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load events");
    }
  };

  const toggleScope = (scope: string) =>
    setScopes((cur) => (cur.includes(scope) ? cur.filter((s) => s !== scope) : [...cur, scope]));

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4">
      <div className="flex items-center gap-2">
        <KeyRound className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Machine keys</h1>
      </div>
      <p className="text-sm text-muted-foreground">
        Keys let your own scripts place paper orders through the machine API. A key is shown
        once, at creation — only its hash is stored — and revoking is instant and final.
        Rotation is revoke + create. The order routes themselves ship in the next step; for
        now this page is the lifecycle and the audit trail.
      </p>

      {error && <div className="rounded border border-destructive/50 bg-destructive/10 p-3 text-sm">{error}</div>}

      {freshKey && (
        <div className="space-y-2 rounded border border-amber-500/50 bg-amber-500/10 p-3">
          <p className="text-sm font-medium">Copy this key now — it is shown once and cannot be recovered.</p>
          <code className="block break-all rounded bg-background p-2 text-sm">{freshKey}</code>
          <button type="button" className="rounded bg-secondary px-3 py-1 text-sm" onClick={() => setFreshKey(null)}>
            I saved it
          </button>
        </div>
      )}

      <div className="space-y-3 rounded border p-4">
        <h2 className="font-medium">New key</h2>
        <label className="block text-sm">
          Label
          <input
            className="mt-1 w-full rounded border bg-background p-2"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="mac scripts"
          />
        </label>
        <div className="flex flex-wrap gap-4 text-sm">
          {ALL_SCOPES.map((scope) => (
            <label key={scope} className="flex items-center gap-2">
              <input type="checkbox" checked={scopes.includes(scope)} onChange={() => toggleScope(scope)} />
              {scope}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <label>
            Max qty / order
            <input type="number" className="mt-1 block w-28 rounded border bg-background p-2" value={maxQty}
              onChange={(e) => setMaxQty(Number(e.target.value))} />
          </label>
          <label>
            Max notional / order ($)
            <input type="number" className="mt-1 block w-32 rounded border bg-background p-2" value={maxNotional}
              onChange={(e) => setMaxNotional(Number(e.target.value))} />
          </label>
          <label>
            Daily cap (orders)
            <input type="number" className="mt-1 block w-28 rounded border bg-background p-2" value={dailyCap}
              onChange={(e) => setDailyCap(Number(e.target.value))} />
          </label>
        </div>
        <button
          type="button"
          className="rounded bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
          disabled={!label.trim() || scopes.length === 0}
          onClick={() => void create()}
        >
          Create key
        </button>
      </div>

      <div className="space-y-3">
        {keys === null && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
        {keys?.length === 0 && <p className="text-sm text-muted-foreground">No keys yet.</p>}
        {keys?.map((k) => (
          <div key={k.id} className="space-y-2 rounded border p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{k.label}</span>
              <span className={k.revoked_at ? "text-sm text-destructive" : "text-sm text-emerald-500"}>
                {k.revoked_at ? `Revoked ${fmt(k.revoked_at)}` : "Active"}
              </span>
            </div>
            <p className="text-sm text-muted-foreground">
              {k.scopes.join(", ")} · max {k.max_qty} shares / ${Number(k.max_notional).toLocaleString()} per
              order · {k.daily_cap}/day · created {fmt(k.created_at)} · last used {fmt(k.last_used_at)}
            </p>
            <div className="flex gap-2">
              <button type="button" className="rounded bg-secondary px-3 py-1 text-sm" onClick={() => void toggleEvents(k.id)}>
                {eventsFor === k.id ? "Hide events" : "Events"}
              </button>
              {!k.revoked_at &&
                (confirmRevoke === k.id ? (
                  <>
                    <button type="button" className="rounded bg-destructive px-3 py-1 text-sm text-destructive-foreground"
                      onClick={() => void revoke(k.id)}>
                      Confirm revoke
                    </button>
                    <button type="button" className="rounded bg-secondary px-3 py-1 text-sm" onClick={() => setConfirmRevoke(null)}>
                      Keep it
                    </button>
                  </>
                ) : (
                  <button type="button" className="rounded bg-secondary px-3 py-1 text-sm" onClick={() => setConfirmRevoke(k.id)}>
                    Revoke
                  </button>
                ))}
            </div>
            {eventsFor === k.id && (
              <div className="pt-2 text-sm">
                {events === null ? (
                  <p className="text-muted-foreground">Loading events…</p>
                ) : events.length === 0 ? (
                  <p className="text-muted-foreground">No events yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {events.map((e) => (
                      <li key={e.id} className="flex flex-wrap gap-x-3 text-muted-foreground">
                        <span>{fmt(e.at)}</span>
                        <span className="text-foreground">{e.outcome}</span>
                        <span>{e.route}</span>
                        {e.client_order_id && <span>{e.client_order_id}</span>}
                        {e.detail && <span>{e.detail}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
