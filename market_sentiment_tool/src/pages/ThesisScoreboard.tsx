import { AlertTriangle, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useThesisScoreboard } from "@/hooks/useThesisScoreboard";
import type { ClaimBlock, Scoreboard } from "@/lib/thesisTracker";

const dash = (value: string | number | null | undefined) =>
  value === null || value === undefined || value === "" ? "—" : String(value);

const pct = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;

const interval = (value: [number, number] | null | undefined) =>
  !value ? "" : ` (${pct(value[0])}–${pct(value[1])})`;

const usd = (value: number | null | undefined) =>
  value === null || value === undefined
    ? "—"
    : `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;

const fmtDay = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

function StateChip({ state }: { state: string }) {
  const hot = state === "fired" || state === "killed";
  const done = state === "passed";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider ${
        hot
          ? "bg-red-500/15 text-red-300"
          : done
            ? "bg-emerald-500/15 text-emerald-300"
            : "bg-slate-800 text-slate-300"
      }`}
    >
      {state}
    </span>
  );
}

function ClaimCard({ claim }: { claim: ClaimBlock }) {
  const countdown =
    claim.claim === "A"
      ? `${claim.prints_remaining} of ${claim.prints_target} prints remaining`
      : claim.claim === "B"
        ? `${claim.clusters_remaining} of ${claim.clusters_target} clusters remaining`
        : `${claim.fires_remaining} of ${claim.fires_target} fires remaining`;
  return (
    <Card className="border-slate-800 bg-slate-900/40">
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-lg text-white">
          <span>Claim {claim.claim} — {claim.metric}</span>
          <StateChip state={claim.state} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm text-slate-300">
        <p>
          Graded <span className="font-mono text-white">{claim.graded}</span>
          {claim.rate !== null && (
            <>
              {" "}· hit rate <span className="font-mono text-white">{pct(claim.rate)}</span>
              <span className="text-slate-500">{interval(claim.interval)}</span>
            </>
          )}
          {claim.claim === "C" && (
            <> · net so far <span className="font-mono text-white">{usd(claim.net)}</span></>
          )}
        </p>
        <p className="text-slate-400">{countdown}</p>
        <p className="text-slate-400">
          Deadline {fmtDay(claim.deadline)}
          {claim.days_to_deadline !== null && claim.days_to_deadline !== undefined && (
            <> · {claim.days_to_deadline} days</>
          )}
          {claim.progress_verdict && (
            <> · progress verdict <span className="text-white">{claim.progress_verdict}</span></>
          )}
        </p>
        {claim.note && <p className="text-slate-500">{claim.note}</p>}
      </CardContent>
    </Card>
  );
}

function RegimePanel({ board }: { board: Scoreboard }) {
  const { regime, cash_gauge } = board;
  return (
    <Card className="border-slate-800 bg-slate-900/40">
      <CardHeader>
        <CardTitle className="text-lg text-white">Regime — Gray Area governor</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm text-slate-300">
        <p>
          Ratified odds: stalemate{" "}
          <span className="font-mono text-white">{pct(regime.odds.stalemate)}</span> · boom{" "}
          <span className="font-mono text-white">{pct(regime.odds.boom)}</span> · crash{" "}
          <span className="font-mono text-white">{pct(regime.odds.crash)}</span>
        </p>
        <p>
          Big-four 2027 capex:{" "}
          {regime.capex.figure_usd_bn === null ? (
            <span className="text-slate-400">
              no figure recorded yet — crash grade below ${regime.capex.crash_below_usd_bn}B, boom
              grade at or above ${regime.capex.boom_at_or_above_usd_bn}B
            </span>
          ) : (
            <>
              <span className="font-mono text-white">${regime.capex.figure_usd_bn}B</span> — grading{" "}
              <span className="text-white">{dash(regime.capex.grading)}</span> against the $
              {regime.capex.crash_below_usd_bn}B / ${regime.capex.boom_at_or_above_usd_bn}B lines
            </>
          )}
        </p>
        <p>
          Crash triggers fired:{" "}
          <span className="font-mono text-white">{regime.crash_triggers.fired_count}</span>
          {regime.crash_triggers.fired.length > 0 && (
            <span className="text-slate-400"> ({regime.crash_triggers.fired.join(", ")})</span>
          )}
        </p>
        <div>
          <p className="mb-1 text-slate-400">Credit lights</p>
          <ul className="space-y-1">
            {regime.credit_lights.map((light) => (
              <li key={light.key} className="flex flex-wrap items-center gap-2">
                <span className="text-slate-300">{light.label}</span>
                <StateChip state={light.state} />
                <span className="text-slate-500">
                  as of {fmtDay(light.as_of)}
                  {light.age_days !== null && <> · {light.age_days}d old</>}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-1 text-slate-400">Cash floor — {cash_gauge.floor_pct}% of equity</p>
          <ul className="space-y-1">
            {cash_gauge.books.map((book) => (
              <li key={book.book} className="flex items-center gap-2">
                <span className="font-mono text-slate-300">{book.book}</span>
                <span className="font-mono text-white">
                  {book.cash_pct === null ? "—" : `${book.cash_pct.toFixed(1)}% cash`}
                </span>
                {book.breach && <StateChip state="breach" />}
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}

export default function ThesisScoreboard() {
  const { board, loading, error } = useThesisScoreboard();

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="space-y-2 border-b border-slate-900 pb-8">
          <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">
            Thesis Scoreboard
          </h1>
          <p className="max-w-3xl text-sm text-slate-400">
            Claims A, B and C against their frozen falsifier windows — graded counts, hit rates
            with intervals, and the countdowns. Play kinds keep separate ledgers; the whisper and
            the money flow are graded separately and never combined.
          </p>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading scoreboard…
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 py-8 text-red-300">
            <AlertTriangle className="h-4 w-4" /> {error}
          </div>
        ) : !board ? (
          <p className="py-8 text-sm text-slate-400">
            The tracker is not seeded yet — no theses, claims or regime inputs are recorded.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
              <span>
                Governing event-lab unit{" "}
                <span className="font-mono text-white">{usd(board.sizing.governing_unit.unit)}</span>{" "}
                ({board.sizing.governing_unit.source})
              </span>
              <span className="text-slate-500">·</span>
              <span>
                Grader{" "}
                {board.sizing.health.last_grader_ok ? (
                  <span className="text-emerald-300">healthy</span>
                ) : (
                  <span className="text-red-300">not ok</span>
                )}{" "}
                · last run {fmtDay(board.sizing.health.last_grader_run_at)}
              </span>
              <span className="text-slate-500">·</span>
              <span>
                Play kind (c){" "}
                {board.sizing.config.play_kind_c_live ? (
                  <span className="text-white">live</span>
                ) : (
                  <span className="text-slate-300">shadow only</span>
                )}
              </span>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              {board.claims.map((claim) => (
                <ClaimCard key={claim.claim} claim={claim} />
              ))}
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="border-slate-800 bg-slate-900/40">
                <CardHeader>
                  <CardTitle className="text-lg text-white">Play kinds — separate ledgers</CardTitle>
                </CardHeader>
                <CardContent>
                  {Object.keys(board.play_kinds).length === 0 ? (
                    <p className="py-4 text-sm text-slate-400">
                      No linked trades have closed yet.
                    </p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-800 text-left text-slate-500">
                          <th className="py-2 pr-4">Kind</th>
                          <th className="py-2 pr-4">Links</th>
                          <th className="py-2 pr-4">Trades</th>
                          <th className="py-2 pr-4">Hit rate</th>
                          <th className="py-2">Net P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(board.play_kinds).map(([kind, slot]) => (
                          <tr key={kind} className="border-b border-slate-900 last:border-0">
                            <td className="py-2 pr-4 font-mono font-bold text-white">({kind})</td>
                            <td className="py-2 pr-4 text-slate-300">{slot.links}</td>
                            <td className="py-2 pr-4 text-slate-300">{slot.trades}</td>
                            <td className="py-2 pr-4 text-slate-300">
                              {pct(slot.hit_rate)}
                              <span className="text-slate-500">{interval(slot.interval)}</span>
                            </td>
                            <td className="py-2 font-mono text-slate-100">{usd(slot.pnl)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </CardContent>
              </Card>

              <Card className="border-slate-800 bg-slate-900/40">
                <CardHeader>
                  <CardTitle className="text-lg text-white">Pre-print signals — graded separately</CardTitle>
                </CardHeader>
                <CardContent>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-800 text-left text-slate-500">
                        <th className="py-2 pr-4">Signal</th>
                        <th className="py-2 pr-4">Graded</th>
                        <th className="py-2">Hit rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-slate-900">
                        <td className="py-2 pr-4 text-slate-300">Whisper sign</td>
                        <td className="py-2 pr-4 text-slate-300">{board.signals.whisper.graded}</td>
                        <td className="py-2 text-slate-300">
                          {pct(board.signals.whisper.rate)}
                          <span className="text-slate-500">{interval(board.signals.whisper.interval)}</span>
                        </td>
                      </tr>
                      <tr>
                        <td className="py-2 pr-4 text-slate-300">Money flow</td>
                        <td className="py-2 pr-4 text-slate-300">{board.signals.money_flow.graded}</td>
                        <td className="py-2 text-slate-300">
                          {pct(board.signals.money_flow.rate)}
                          <span className="text-slate-500">{interval(board.signals.money_flow.interval)}</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </div>

            <RegimePanel board={board} />

            <Card className="border-slate-800 bg-slate-900/40">
              <CardHeader>
                <CardTitle className="text-lg text-white">Thesis registry</CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800 text-left text-slate-500">
                      <th className="py-2 pr-4">Thesis</th>
                      <th className="py-2 pr-4">Sleeve</th>
                      <th className="py-2 pr-4">Status</th>
                      <th className="py-2">Kill lines</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.theses.map((thesis) => (
                      <tr key={thesis.slug} className="border-b border-slate-900 last:border-0">
                        <td className="py-2 pr-4 text-slate-300">
                          <span className="font-mono text-white">{thesis.slug}</span> — {thesis.title}
                        </td>
                        <td className="py-2 pr-4 text-slate-300">{thesis.sleeve}</td>
                        <td className="py-2 pr-4">
                          <StateChip state={thesis.status} />
                        </td>
                        <td className="py-2 text-slate-300">{thesis.kill_line_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-900/40">
              <CardHeader>
                <CardTitle className="text-lg text-white">Breach log</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                {board.breaches.refusals.length === 0 && board.breaches.stale_files.length === 0 ? (
                  <p className="py-4 text-slate-400">
                    No preflight blocks and no stale research files on record.
                  </p>
                ) : (
                  <>
                    {board.breaches.refusals.length > 0 && (
                      <div>
                        <p className="mb-1 text-slate-400">Preflight blocks (newest first)</p>
                        <ul className="space-y-1">
                          {board.breaches.refusals.map((refusal, i) => (
                            <li key={i} className="text-slate-300">
                              <span className="text-slate-500">{fmtDay(refusal.at)}</span>{" "}
                              <span className="font-mono text-slate-200">{refusal.outcome}</span>{" "}
                              {dash(refusal.detail)}
                              {refusal.cash_floor && (
                                <span className="ml-2 rounded-full bg-red-500/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-red-300">
                                  cash floor
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {board.breaches.stale_files.length > 0 && (
                      <div>
                        <p className="mb-1 text-slate-400">
                          Stale research files — a decision landed after the last amendment
                        </p>
                        <ul className="space-y-1">
                          {board.breaches.stale_files.map((file) => (
                            <li key={file.path} className="text-slate-300">
                              <span className="font-mono text-slate-200">{file.path}</span>
                              {file.thesis_slug && (
                                <span className="text-slate-500"> ({file.thesis_slug})</span>
                              )}{" "}
                              · decided {fmtDay(file.last_decision_at)}, last amended{" "}
                              {fmtDay(file.amended_at)}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
