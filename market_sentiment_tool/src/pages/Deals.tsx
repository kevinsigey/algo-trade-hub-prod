import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import type { DealRun, DealRunRow } from "@/lib/deals";

const num = (v: string): number | null => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};
const f2 = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${f2(v, 1)}%`);

function Field({ label, value, onChange, hint }: { label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium text-slate-300">{label}</span>
      <input value={value} onChange={(e) => onChange(e.target.value)} inputMode="decimal"
        className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-[15px] text-white focus:border-emerald-400 focus:outline-none" />
      {hint && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

function Verdict({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`rounded-full border px-2.5 py-1 text-[13px] font-semibold ${
      ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-rose-500/40 bg-rose-500/10 text-rose-300"}`}>
      {ok ? "✓ " : "✗ "}{label}
    </span>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-semibold ${tone ?? "text-white"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[13px] text-slate-400">{sub}</div>}
    </div>
  );
}

/** One football-field row: a range bar against the shared scale, with an
 * optional marker line. */
function Bar({ label, low, high, scale, marker, tone = "bg-slate-500" }:
  { label: string; low: number; high: number; scale: number; marker?: number; tone?: string }) {
  const l = Math.max(0, (low / scale) * 100);
  const w = Math.max(1.5, ((high - low) / scale) * 100);
  return (
    <div className="flex items-center gap-3 text-[13px]">
      <span className="w-44 shrink-0 truncate text-slate-300">{label}</span>
      <div className="relative h-5 flex-1 rounded bg-slate-800/70">
        <div className={`absolute top-1 h-3 rounded ${tone}`} style={{ left: `${l}%`, width: `${w}%` }} />
        {marker != null && (
          <div className="absolute -top-0.5 h-6 w-0.5 bg-amber-300" style={{ left: `${(marker / scale) * 100}%` }} />
        )}
      </div>
      <span className="w-32 shrink-0 tabular-nums text-slate-200">
        {low === high ? `$${f2(low)}` : `$${f2(low)} – $${f2(high)}`}
      </span>
    </div>
  );
}

/* ------------------------------- IPO detail ------------------------------ */

export function IpoDetail({ o, talkLow, talkHigh }: { o: any; talkLow?: number | null; talkHigh?: number | null }) {
  const scale = Math.max(o.pw_ps, ...o.ladder.map((r: any) => r.ps), talkHigh ?? 0) * 1.05;
  const maxShock = Math.max(...o.sensitivity.map((s: any) => Math.abs(s.d_pw_ps)), 0.01);
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <Tile label="Our fair value (probability-weighted)" value={`$${f2(o.pw_ps)}`}
          sub={`$${f2(o.pw_ev_b, 0)}B enterprise value`} tone="text-emerald-300" />
        <Tile label="Bear case" value={`$${f2(o.bear_ps)}`} sub="the downside the entry test bounds" />
        <Tile label="Chance below the talk mid" value={o.prob_below_talk_mid != null ? `${f2(o.prob_below_talk_mid * 100, 0)}%` : "—"}
          sub="scenario weight under the mid" />
        <Tile label="Implied P/S at our value" value={o.implied_ps_at_pw != null ? `${f2(o.implied_ps_at_pw, 1)}×` : "—"}
          sub="on the revenue / run rate entered" />
        <Tile label="Forks, jointly" value={o.conditions.joint_odds != null ? `${f2(o.conditions.joint_odds * 100, 1)}%` : "—"}
          sub="all conditions at once" />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">
          The ladder — bar length is value, the segment is the scenario's weight; amber line is our fair value
        </h3>
        <div className="mt-3 space-y-2.5">
          {o.ladder.map((r: any) => (
            <div key={r.name}>
              <Bar label={`${r.name} · ${Math.round(r.weight * 100)}%`} low={r.ps} high={r.ps} scale={scale} marker={o.pw_ps} tone="bg-sky-500" />
              <div className="ml-44 mr-32 mt-1 h-1.5 rounded bg-slate-800">
                <div className="h-1.5 rounded bg-sky-300/70" style={{ width: `${r.weight * 100}%` }} />
              </div>
            </div>
          ))}
          {talkLow != null && talkHigh != null && (
            <Bar label="Talk range" low={talkLow} high={talkHigh} scale={scale} tone="bg-amber-500/70" />
          )}
        </div>
      </div>

      {o.entry.at_mid ? (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">Entry test — the paper's three rules</h3>
          {(["at_mid", "at_high"] as const).map((k) => {
            const t = o.entry[k];
            return (
              <div key={k} className="mt-3">
                <p className="text-[15px] text-slate-200">
                  At {k === "at_mid" ? "the talk mid" : "the talk high"} (${f2(t.talk_ps)}): expected return vs our value {pct(t.exp_return_vs_pw_pct)},
                  margin of safety {pct(t.mos_vs_pw_pct)}, bear downside {pct(t.bear_downside_pct)}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Verdict ok={t.rules.beats_pw} label="Price at or below PW value" />
                  <Verdict ok={t.rules.mos_25} label="Margin of safety ≥ 25%" />
                  <Verdict ok={t.rules.bear_bound_40} label="Bear downside ≤ 40%" />
                  <Verdict ok={t.enter} label={t.enter ? "ENTER" : "Not a clean entry"} />
                </div>
              </div>
            );
          })}
        </div>
      ) : <p className="text-[15px] text-amber-300">{o.entry.missing}</p>}

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">What moves the answer most (Δ $/share)</h3>
        <ul className="mt-3 space-y-2">
          {o.sensitivity.slice(0, 6).map((s: any) => (
            <li key={s.lever} className="flex items-center gap-3 text-sm">
              <span className="w-64 shrink-0 truncate text-slate-200">{s.lever}</span>
              <div className="h-3.5 flex-1 rounded bg-slate-800/70">
                <div className={`h-3.5 rounded ${s.d_pw_ps >= 0 ? "bg-emerald-500/80" : "bg-rose-500/80"}`}
                  style={{ width: `${(Math.abs(s.d_pw_ps) / maxShock) * 100}%` }} />
              </div>
              <span className={`w-24 shrink-0 text-right tabular-nums ${s.d_pw_ps >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                {s.d_pw_ps >= 0 ? "+" : ""}${f2(s.d_pw_ps)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ------------------------------- M&A detail ------------------------------ */

export function MaDetail({ o }: { o: any }) {
  const scale = Math.max(o.acquirer.ps_high, o.target.ps_high, o.offer.value_ps, o.fair_value?.ps_high ?? 0) * 1.05;
  const maxPv = Math.max(...(["bear", "base", "bull"] as const).map((k) => Math.abs(o.cases[k].synergy_pv_b ?? 0)), 0.01);
  return (
    <div className="space-y-5">
      {o.fair_value && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-300/80">Our fair value for the target</div>
              <div className="mt-1 text-4xl font-semibold text-emerald-200">${f2(o.fair_value.ps)} <span className="text-lg text-emerald-300/70">/ share</span></div>
            </div>
            <p className="max-w-xl text-[15px] text-slate-200">
              Range ${f2(o.fair_value.ps_low)} – ${f2(o.fair_value.ps_high)} (blend:{" "}
              {Object.entries(o.fair_value.weights as Record<string, number>)
                .map(([k, w]) => `${k} ${Math.round(w * 100)}%`).join(" · ")}).
              The offer at ${f2(o.offer.value_ps)} is {pct(o.fair_value.vs_offer_pct)} vs our estimate — {o.fair_value.verdict}.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile label="Premium to undisturbed" value={pct(o.offer.premium_pct)}
          sub={`offer $${f2(o.offer.value_ps)} vs $${f2(o.offer.undisturbed_ps)}`} />
        <Tile label="Combined revenue" value={`$${f2(o.pro_forma.combined_revenue_b, 1)}B`}
          sub={`$${f2(o.pro_forma.combined_ebitda_b, 1)}B EBITDA`} />
        <Tile label="Combined value at the offer" value={`$${f2(o.pro_forma.ev_at_offer_b, 0)}B`}
          sub={o.pro_forma.ev_to_revenue != null ? `${f2(o.pro_forma.ev_to_revenue, 1)}× revenue · ${f2(o.pro_forma.ev_to_ebitda, 1)}× EBITDA` : undefined} />
        <Tile label="New shares issued" value={`${f2(o.pro_forma.new_shares_b, 2)}B`}
          sub={`${f2(o.pro_forma.combined_shares_b, 2)}B combined`} />
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">Football fields ($/share)</h3>
        <div className="mt-3 space-y-2">
          {(["acquirer", "target"] as const).map((k) => {
            const s = o[k];
            return (
              <div key={k} className="space-y-2">
                <Bar label={`${s.name} — all bases`} low={s.ps_low} high={s.ps_high} scale={scale} tone="bg-sky-500" />
                {s.fields.revenue && <Bar label="· on revenue" low={s.fields.revenue.ps_low} high={s.fields.revenue.ps_high} scale={scale} tone="bg-slate-500" />}
                {s.fields.ebitda && <Bar label="· on EBITDA" low={s.fields.ebitda.ps_low} high={s.fields.ebitda.ps_high} scale={scale} tone="bg-slate-500" />}
                {s.dcf_ps != null && <Bar label="· DCF" low={s.dcf_ps} high={s.dcf_ps} scale={scale} tone="bg-violet-500" />}
              </div>
            );
          })}
          {o.fair_value && <Bar label="Our fair value (target)" low={o.fair_value.ps_low} high={o.fair_value.ps_high} scale={scale} tone="bg-emerald-500" />}
          <Bar label="Offer value" low={o.offer.value_ps} high={o.offer.value_ps} scale={scale} tone="bg-amber-500" />
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">Ownership of the combined company</h3>
          <div className="mt-3 flex h-9 w-full overflow-hidden rounded-lg text-[13px] font-medium">
            <div className="flex items-center justify-center bg-sky-600/80 text-white" style={{ width: `${o.pro_forma.ownership.acquirer_pct}%` }}>
              {o.acquirer.name} holders {f2(o.pro_forma.ownership.acquirer_pct, 1)}%
            </div>
            <div className="flex items-center justify-center bg-amber-500/80 text-slate-950" style={{ width: `${o.pro_forma.ownership.target_pct}%` }}>
              {o.target.name} {f2(o.pro_forma.ownership.target_pct, 1)}%
            </div>
          </div>
          {o.ratio_range && (
            <div className="mt-5">
              <h4 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">Where the offered ratio sits</h4>
              <div className="relative mt-4 h-3 rounded bg-slate-800">
                <div className="absolute top-0 h-3 rounded bg-slate-600" style={{ left: "0%", width: "100%" }} />
                <div className="absolute -top-1.5 h-6 w-1 rounded bg-amber-300"
                  style={{ left: `${(o.ratio_range.position ?? 0) * 100}%` }} />
              </div>
              <div className="mt-1.5 flex justify-between text-xs text-slate-400">
                <span>implied low {o.ratio_range.low}</span>
                <span className="text-amber-200">offered {o.ratio_range.offered}</span>
                <span>implied high {o.ratio_range.high}</span>
              </div>
              <p className="mt-1 text-[13px] text-slate-300">
                {o.ratio_range.inside ? "Inside the range the standalone values support." : "Outside that range."}
              </p>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h3 className="text-[13px] font-semibold uppercase tracking-wide text-slate-400">Synergy cases — who captures the value</h3>
          <div className="mt-3 space-y-3">
            {(["bear", "base", "bull"] as const).map((k) => {
              const c = o.cases[k];
              return (
                <div key={k} className="text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-medium capitalize text-slate-100">{k}</span>
                    <span className="tabular-nums text-slate-300">
                      PV {c.synergy_pv_b != null ? `$${f2(c.synergy_pv_b, 1)}B` : "—"} · EPS {c.accretion_pct != null ? pct(c.accretion_pct) : "needs both EPS"}
                    </span>
                  </div>
                  <div className="mt-1 h-3 rounded bg-slate-800/70">
                    <div className="h-3 rounded bg-violet-500/80" style={{ width: `${(Math.abs(c.synergy_pv_b ?? 0) / maxPv) * 100}%` }} />
                  </div>
                  <p className="mt-1 text-[13px] text-slate-400">
                    target captures {c.target_captures_b != null ? `$${f2(c.target_captures_b, 1)}B` : "—"} ·
                    acquirer captures {c.acquirer_captures_b != null ? `$${f2(c.acquirer_captures_b, 1)}B` : "—"}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------- IPO builder ----------------------------- */

interface ScenRow { name: string; ev: string; revenue: string; multiple: string; weight: string }

const ANTHROPIC_SCEN: ScenRow[] = [
  { name: "Bear — token utility (DCF)", ev: "446", revenue: "", multiple: "", weight: "20" },
  { name: "Software multiple on today's mix", ev: "1130", revenue: "", multiple: "", weight: "30" },
  { name: "Base — partial climb (DCF)", ev: "1525", revenue: "", multiple: "", weight: "35" },
  { name: "Bull — all three go right (DCF)", ev: "4628", revenue: "", multiple: "", weight: "15" },
];

function IpoBuilder({ onSaved }: { onSaved: () => void }) {
  const [company, setCompany] = useState("Anthropic");
  const [shares, setShares] = useState("16.9368");
  const [revenue, setRevenue] = useState("65");
  const [netCash, setNetCash] = useState("");
  const [talkLow, setTalkLow] = useState("85");
  const [talkHigh, setTalkHigh] = useState("110");
  const [perp, setPerp] = useState("");
  const [scen, setScen] = useState<ScenRow[]>(ANTHROPIC_SCEN);
  const [conds, setConds] = useState([{ name: "Hold enterprise lead (share)", odds: "60" },
                                      { name: "Shift mix up (layer)", odds: "45" },
                                      { name: "Keep compute margin (constraint)", odds: "55" }]);
  const [run, setRun] = useState<DealRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async () => {
    setBusy(true); setError(null);
    try {
      const inputs = {
        company, shares_b: num(shares), revenue_b: num(revenue), net_cash_b: num(netCash),
        talk_low_ps: num(talkLow), talk_high_ps: num(talkHigh),
        scenarios: scen.map((s) => ({ name: s.name, ev_b: num(s.ev), revenue_b: num(s.revenue),
                                      multiple: num(s.multiple), weight: (num(s.weight) ?? 0) / 100 })),
        conditions: conds.filter((c) => c.name).map((c) => ({ name: c.name, odds: (num(c.odds) ?? 0) / 100 })),
      };
      const d = await adminJson<DealRun>("/api/deals/ipo/run", { method: "POST", body: JSON.stringify({ inputs }) });
      setRun(d);
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "The run failed"); }
    setBusy(false);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[400px_1fr]">
      <section className="space-y-3">
        <p className="text-[13px] leading-relaxed text-slate-400">Prefilled with the Anthropic paper's own form (S-1 fully-diluted shares, its four outcome values and weights). Every field is editable; private inputs are the form — nothing is pulled or invented.</p>
        <Field label="Company" value={company} onChange={setCompany} />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Fully-diluted shares (B)" value={shares} onChange={setShares} hint="From the S-1/F-1" />
          <Field label="Revenue / run rate ($B)" value={revenue} onChange={setRevenue} />
          <Field label="Net cash ($B, blank = 0)" value={netCash} onChange={setNetCash} />
          <Field label="Pre-IPO perp mark ($/sh, optional)" value={perp} onChange={setPerp} hint="A reported mark, never the stock" />
          <Field label="Talk range low ($/sh)" value={talkLow} onChange={setTalkLow} />
          <Field label="Talk range high ($/sh)" value={talkHigh} onChange={setTalkHigh} />
        </div>
        <h3 className="pt-2 text-[15px] font-semibold text-white">Scenarios — value ($B) or revenue × multiple, and weight %</h3>
        {scen.map((s, i) => (
          <div key={i} className="grid grid-cols-[1fr_64px_64px_56px] items-end gap-2">
            <Field label={i === 0 ? "Name" : ""} value={s.name}
              onChange={(v) => setScen(scen.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
            <Field label={i === 0 ? "Value $B" : ""} value={s.ev}
              onChange={(v) => setScen(scen.map((x, j) => (j === i ? { ...x, ev: v } : x)))} />
            <Field label={i === 0 ? "or Rev ×" : ""} value={s.revenue}
              onChange={(v) => setScen(scen.map((x, j) => (j === i ? { ...x, revenue: v } : x)))} />
            <Field label={i === 0 ? "Wt %" : ""} value={s.weight}
              onChange={(v) => setScen(scen.map((x, j) => (j === i ? { ...x, weight: v } : x)))} />
          </div>
        ))}
        <h3 className="pt-2 text-[15px] font-semibold text-white">Conditions (the filing's own forks) — odds %</h3>
        {conds.map((c, i) => (
          <div key={i} className="grid grid-cols-[1fr_72px] items-end gap-2">
            <Field label={i === 0 ? "Condition" : ""} value={c.name}
              onChange={(v) => setConds(conds.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
            <Field label={i === 0 ? "Odds %" : ""} value={c.odds}
              onChange={(v) => setConds(conds.map((x, j) => (j === i ? { ...x, odds: v } : x)))} />
          </div>
        ))}
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        <button type="button" onClick={go} disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2.5 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Run the IPO builder
        </button>
        {num(perp) != null && run && (
          <p className="text-[13px] text-slate-500">
            Cross-check: the pre-IPO perp mark of ${f2(num(perp))}/share is a reported mark on a derivative — it is not the stock and implies nothing by itself.
          </p>
        )}
      </section>
      <section>
        {!run && <p className="text-[15px] text-slate-500">Run it to see our fair value, the ladder, and the entry test.</p>}
        {run && <IpoDetail o={run.outputs} talkLow={num(talkLow)} talkHigh={num(talkHigh)} />}
      </section>
    </div>
  );
}

/* ------------------------------- M&A builder ----------------------------- */

interface SideState { mode: "public" | "private"; source: "yahoo" | "edgar"; ticker: string; name: string; price: string; shares: string;
  revenue: string; ebitda: string; eps: string; netCash: string; revLo: string; revHi: string;
  ebLo: string; ebHi: string; fcfM: string; growth: string; wacc: string; exitM: string; stamp: string }

const blankSide = (name: string): SideState => ({ mode: "private", source: "yahoo", ticker: "", name, price: "", shares: "",
  revenue: "", ebitda: "", eps: "", netCash: "", revLo: "", revHi: "", ebLo: "", ebHi: "",
  fcfM: "10", growth: "5", wacc: "10", exitM: "10", stamp: "" });

function sideInputs(s: SideState) {
  return { name: s.name, price: num(s.price), shares_b: num(s.shares), revenue_b: num(s.revenue),
           ebitda_b: num(s.ebitda), eps: num(s.eps), net_cash_b: num(s.netCash),
           rev_multiples: { low: num(s.revLo), high: num(s.revHi) },
           ebitda_multiples: { low: num(s.ebLo), high: num(s.ebHi) },
           dcf: { fcf_margin: (num(s.fcfM) ?? 0) / 100, growth: (num(s.growth) ?? 0) / 100,
                  wacc: (num(s.wacc) ?? 0) / 100, exit_multiple: num(s.exitM) } };
}

function SideForm({ side, setSide, label }: { side: SideState; setSide: (s: SideState) => void; label: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const prefill = async () => {
    setBusy(true); setErr(null);
    try {
      const d = await adminJson<any>(`/api/deals/public/${side.ticker}?source=${side.source}`);
      setSide({ ...side, name: d.name, price: String(d.price ?? ""), shares: String(d.shares_b ?? ""),
        revenue: String(d.revenue_b ?? ""), ebitda: String(d.ebitda_b ?? ""), eps: String(d.eps ?? ""),
        netCash: String(d.net_cash_b ?? ""), revLo: String(d.rev_multiples?.low ?? ""), revHi: String(d.rev_multiples?.high ?? ""),
        ebLo: String(d.ebitda_multiples?.low ?? ""), ebHi: String(d.ebitda_multiples?.high ?? ""),
        stamp: `${d.source} · as of ${String(d.as_of).slice(0, 10)}${d.filing_as_of ? ` · filed ${String(d.filing_as_of).slice(0, 10)}` : ""}${d.ebitda_basis ? ` · EBITDA = ${d.ebitda_basis}` : ""} · multiples are the company's own, ±15%` });
    } catch (e) { setErr(e instanceof Error ? e.message : "Prefill failed"); }
    setBusy(false);
  };
  const set = (k: keyof SideState) => (v: string) => setSide({ ...side, [k]: v });
  return (
    <fieldset className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <legend className="px-1 text-base font-semibold text-white">{label}</legend>
      <div className="flex flex-wrap gap-2 text-[13px]">
        {(["public", "private"] as const).map((m) => (
          <button key={m} type="button" onClick={() => setSide({ ...side, mode: m })}
            className={`rounded-full border px-2.5 py-1 ${side.mode === m ? "border-emerald-500/50 text-emerald-300" : "border-slate-700 text-slate-400"}`}>
            {m === "public" ? "Public ticker" : "Private — I'll supply the financials"}
          </button>
        ))}
      </div>
      {side.mode === "public" && (
        <div className="flex flex-wrap items-center gap-2">
          <input aria-label={`${label} ticker`} value={side.ticker} onChange={(e) => setSide({ ...side, ticker: e.target.value.toUpperCase() })}
            placeholder="TSLA" className="w-28 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 font-mono text-[15px] text-white" />
          <div className="flex overflow-hidden rounded-lg border border-slate-700 text-[13px]" role="group" aria-label={`${label} prefill source`}>
            {(["yahoo", "edgar"] as const).map((src) => (
              <button key={src} type="button" onClick={() => setSide({ ...side, source: src })} aria-pressed={side.source === src}
                className={`px-2.5 py-2 ${side.source === src ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"}`}>
                {src === "yahoo" ? "Market (Yahoo)" : "Filed (EDGAR)"}
              </button>
            ))}
          </div>
          <button type="button" onClick={prefill} disabled={busy || !side.ticker}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 disabled:opacity-50">
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Prefill
          </button>
        </div>
      )}
      {err && <p role="alert" className="text-sm text-rose-300">{err}</p>}
      {side.stamp && <p className="text-[13px] text-slate-500">{side.stamp}</p>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Name" value={side.name} onChange={set("name")} />
        <Field label="Price ($/sh)" value={side.price} onChange={set("price")} />
        <Field label="Shares (B)" value={side.shares} onChange={set("shares")} />
        <Field label="Net cash ($B)" value={side.netCash} onChange={set("netCash")} />
        <Field label="Revenue ($B)" value={side.revenue} onChange={set("revenue")} />
        <Field label="EBITDA ($B)" value={side.ebitda} onChange={set("ebitda")} />
        <Field label="EPS ($)" value={side.eps} onChange={set("eps")} />
      </div>
      <div className="grid grid-cols-4 gap-3">
        <Field label="EV/Rev low ×" value={side.revLo} onChange={set("revLo")} />
        <Field label="EV/Rev high ×" value={side.revHi} onChange={set("revHi")} />
        <Field label="EV/EBITDA low ×" value={side.ebLo} onChange={set("ebLo")} />
        <Field label="EV/EBITDA high ×" value={side.ebHi} onChange={set("ebHi")} />
        <Field label="DCF: FCF margin %" value={side.fcfM} onChange={set("fcfM")} />
        <Field label="DCF: growth %" value={side.growth} onChange={set("growth")} />
        <Field label="DCF: WACC %" value={side.wacc} onChange={set("wacc")} />
        <Field label="DCF: exit × FCF" value={side.exitM} onChange={set("exitM")} />
      </div>
    </fieldset>
  );
}

function MaBuilder({ onSaved }: { onSaved: () => void }) {
  const [acq, setAcq] = useState<SideState>(blankSide("Acquirer"));
  const [tgt, setTgt] = useState<SideState>(blankSide("Target"));
  const [cashPs, setCashPs] = useState("");
  const [ratio, setRatio] = useState("");
  const [undisturbed, setUndisturbed] = useState("");
  const [syn, setSyn] = useState({ bear: "", base: "", bull: "" });
  const [run, setRun] = useState<DealRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async () => {
    setBusy(true); setError(null);
    try {
      const inputs = { acquirer: sideInputs(acq), target: sideInputs(tgt),
        offer: { cash_ps: num(cashPs) ?? 0, exchange_ratio: num(ratio) ?? 0, undisturbed_ps: num(undisturbed) },
        synergies: { bear: num(syn.bear), base: num(syn.base), bull: num(syn.bull) },
        tax_rate: 0.21, synergy_multiple: 10, debt_rate: 0 };
      const d = await adminJson<DealRun>("/api/deals/ma/run", { method: "POST", body: JSON.stringify({ inputs }) });
      setRun(d);
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "The run failed"); }
    setBusy(false);
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <SideForm side={acq} setSide={setAcq} label="Acquirer" />
        <SideForm side={tgt} setSide={setTgt} label="Target" />
      </div>
      <fieldset className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <legend className="px-1 text-base font-semibold text-white">Offer and synergies</legend>
        <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
          <Field label="Cash ($/target sh)" value={cashPs} onChange={setCashPs} />
          <Field label="Exchange ratio" value={ratio} onChange={setRatio} hint="acquirer shares per target share" />
          <Field label="Undisturbed target price ($)" value={undisturbed} onChange={setUndisturbed} hint="blank = current price" />
          <Field label="Synergies bear ($B/yr)" value={syn.bear} onChange={(v) => setSyn({ ...syn, bear: v })} />
          <Field label="Synergies base ($B/yr)" value={syn.base} onChange={(v) => setSyn({ ...syn, base: v })} />
          <Field label="Synergies bull ($B/yr)" value={syn.bull} onChange={(v) => setSyn({ ...syn, bull: v })} />
        </div>
        <p className="text-[13px] text-slate-500">House defaults, stated on the run: 21% tax on synergies, synergy value capitalized at 10× after tax, cash portion carries no interest cost (0% debt rate). Standalone basis for the bridge is the target's football-field mid.</p>
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        <button type="button" onClick={go} disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2.5 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
          {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Run the M&A builder
        </button>
      </fieldset>
      {run && <MaDetail o={run.outputs} />}
    </div>
  );
}

/* ------------------------------ Saved + modal ---------------------------- */

function RunModal({ run, onClose, onSummarize, summBusy }:
  { run: DealRun; onClose: () => void; onSummarize: () => void; summBusy: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/80 p-4 md:p-8" role="dialog" aria-modal="true" aria-label={run.name}>
      <div className="w-full max-w-4xl rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <span className="mr-2 rounded-full border border-slate-600 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-300">{run.kind}</span>
            <h2 className="mt-1 inline text-xl font-semibold text-white">{run.name}</h2>
            <p className="mt-1 text-[13px] text-slate-400">Run and saved on {run.created_at.slice(0, 10)} — inputs and outputs exactly as entered and computed.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="rounded-lg border border-slate-600 p-1.5 text-slate-300 hover:border-slate-400">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
        <div className="mt-5">
          {run.kind === "ipo"
            ? <IpoDetail o={run.outputs} talkLow={run.inputs.talk_low_ps} talkHigh={run.inputs.talk_high_ps} />
            : <MaDetail o={run.outputs} />}
        </div>
        <div className="mt-6 border-t border-slate-800 pt-4">
          {run.summary ? (
            <div>
              <p className="text-[13px] font-semibold uppercase tracking-wide text-violet-300">
                AI summary — DRAFT{run.summary_model ? ` · ${run.summary_model}` : ""}
              </p>
              <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-slate-950/70 p-4 text-[15px] leading-relaxed text-slate-100">{run.summary}</pre>
            </div>
          ) : (
            <button type="button" onClick={onSummarize} disabled={summBusy}
              className="inline-flex items-center gap-2 rounded-lg border border-violet-500/50 px-3.5 py-2 text-[15px] text-violet-200 hover:border-violet-300 disabled:opacity-50">
              {summBusy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Draft the AI summary
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Deals and IPOs: one page, M&A first (the stronger product today), the IPO
 * entry test second, saved drafts on their own tab -- opening one brings the
 * full record up centrally. Every run saves with inputs and outputs. */
export default function Deals() {
  const [tab, setTab] = useState<"ma" | "ipo" | "saved">("ma");
  const [runs, setRuns] = useState<DealRunRow[] | null>(null);
  const [open, setOpen] = useState<DealRun | null>(null);
  const [summBusy, setSummBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => adminJson<DealRunRow[]>("/api/deals/runs").then(setRuns).catch(() => setRuns([]));
  useEffect(() => { load(); }, []);

  const openRun = (id: number) =>
    adminJson<DealRun>(`/api/deals/runs/${id}`).then(setOpen).catch((e: Error) => setError(e.message));

  const summarize = async () => {
    if (!open) return;
    setSummBusy(true); setError(null);
    try {
      setOpen(await adminJson<DealRun>(`/api/deals/runs/${open.id}/summary`, { method: "POST", body: "{}" }));
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "The summary failed"); }
    setSummBusy(false);
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">
      <h1 className="text-3xl font-bold tracking-tight text-white">Deals and IPOs</h1>
      <p className="mt-1.5 max-w-3xl text-[15px] leading-relaxed text-slate-300">
        Draft a deal through the paper apparatus — the Tesla–SpaceX merger bridge on one side, the Anthropic IPO entry
        test on the other. Our own fair-value estimate sits next to every offer; every run saves as a draft.
      </p>

      <div className="mt-6 flex gap-1 border-b border-slate-800" role="tablist" aria-label="Deals sections">
        {([["ma", "M&A builder"], ["ipo", "IPO builder"], ["saved", "Saved drafts"]] as const).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-t-lg px-4 py-2.5 text-[15px] font-medium ${tab === k ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"}`}>
            {label}{k === "saved" && runs ? ` (${runs.length})` : ""}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "ma" && <MaBuilder onSaved={load} />}
        {tab === "ipo" && <IpoBuilder onSaved={load} />}
        {tab === "saved" && (
          <section>
            {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
            {runs?.length === 0 && <p className="text-[15px] text-slate-500">No runs saved yet — run either builder and the draft lands here.</p>}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {(runs ?? []).map((r) => (
                <button key={r.id} type="button" onClick={() => openRun(r.id)}
                  className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3.5 text-left hover:border-slate-500">
                  <span className="flex items-center justify-between gap-2">
                    <span className="rounded-full border border-slate-600 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-300">{r.kind}</span>
                    <span className="text-xs text-slate-500">{r.created_at.slice(0, 10)}</span>
                  </span>
                  <span className="mt-2 block text-[15px] font-medium leading-snug text-slate-100">{r.name}</span>
                  <span className="mt-1 block text-[13px] text-slate-400">
                    {r.kind === "ipo"
                      ? <>our fair value <span className="text-emerald-300">${f2(r.headline.pw_ps)}</span> · bear ${f2(r.headline.bear_ps)}</>
                      : <>offer <span className="text-amber-200">${f2(r.headline.offer_ps)}</span> ({pct(r.headline.premium_pct)}) · our value ${f2(r.headline.fair_ps)}</>}
                  </span>
                  <span className="mt-1 block text-xs text-slate-500">{r.has_summary ? "AI summary drafted" : "no summary yet"} · click to open</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>

      {open && <RunModal run={open} onClose={() => setOpen(null)} onSummarize={summarize} summBusy={summBusy} />}
    </div>
  );
}
