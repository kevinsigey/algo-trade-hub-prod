import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { interpretText, type InterpretResult } from "@/lib/agent";
import { adminJson, type Idea } from "@/lib/workshop";

/** The one way in for a new idea: paste it, see what the record already says and what the
 * text leaves open, then turn it into a test. Signed-in only; the pages that show it decide. */
export default function NewIdeaBox() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"" | "check" | "test">("");
  const [error, setError] = useState<string | null>(null);
  const [checkFailed, setCheckFailed] = useState<string | null>(null);
  const [check, setCheck] = useState<InterpretResult | null>(null);
  const words = text.trim();
  const checked = check !== null || checkFailed !== null;

  const runCheck = async () => {
    setBusy("check"); setError(null); setCheck(null); setCheckFailed(null);
    try {
      setCheck(await interpretText(words));
    } catch (e) {
      setCheckFailed(e instanceof Error ? e.message : "The check is unavailable");
    }
    setBusy("");
  };

  const startTest = async () => {
    setBusy("test"); setError(null);
    try {
      const title = words.length > 80 ? `${words.slice(0, 77)}…` : words;
      const idea = await adminJson<Idea>("/api/workshop/ideas", {
        method: "POST",
        body: JSON.stringify({ title: title.length < 3 ? `${title}…` : title, plain_words: words }),
      });
      navigate(`/workshop/${idea.id}?draft=1`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the idea");
      setBusy("");
    }
  };

  const ledger = check?.preflight;
  const duplicate = check !== null && check.spec === null;
  const primary = "inline-flex shrink-0 items-center gap-2 self-start rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50";

  return (
    <section aria-label="New idea" className="mt-6">
      <div className="flex gap-2">
        <textarea
          aria-label="Type an idea in plain words"
          value={text}
          onChange={(e) => { setText(e.target.value); setCheck(null); setCheckFailed(null); }}
          rows={2}
          disabled={busy === "check"}
          placeholder="Gold does better than stocks when rates are going up."
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none"
        />
        {checked ? (
          <button type="button" onClick={startTest} disabled={!!busy || !words || duplicate} className={primary}>
            {busy === "test" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Turn into a test
          </button>
        ) : (
          <button type="button" onClick={runCheck} disabled={!!busy || words.length < 3} className={primary}>
            {busy === "check" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Check against the record
          </button>
        )}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-rose-300">{error}</p>}
      {checkFailed && (
        <p className="mt-2 text-sm text-amber-200">The check didn&apos;t run ({checkFailed}). You can still turn it into a test.</p>
      )}
      {check && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-300">
          {ledger?.error && <p className="text-amber-200">The record check failed: {ledger.error}</p>}
          {ledger?.family && (
            <p>
              {ledger.family.size === 0
                ? "A new bet: no tested idea holds these names."
                : `Same bet as ${ledger.family.size} tested ${ledger.family.size === 1 ? "idea" : "ideas"} (${ledger.family.tickers.join(", ")}), ${ledger.prior_attempts} prior ${ledger.prior_attempts === 1 ? "attempt" : "attempts"}.`}
            </p>
          )}
          {ledger?.best_prior && (
            <p className="mt-1">
              Best on these names: <Link to={`/workshop/${ledger.best_prior.idea_id}`} className="text-emerald-300 hover:underline">{ledger.best_prior.title ?? `Idea ${ledger.best_prior.idea_id}`}</Link>
              {" "}· {ledger.best_prior.value.toFixed(2)} on unseen years · {ledger.best_prior.verdict_now} today
            </p>
          )}
          {(ledger?.killed ?? []).filter((k) => !k.exact).map((k) => (
            <p key={k.idea_id} className="mt-1 text-amber-200">Killed before, with a different rule ({k.title}): {k.reason}</p>
          ))}
          {ledger?.expressible === false && <p className="mt-1 text-amber-200">{ledger.note}</p>}
          {check.questions.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {check.questions.map((q) => <li key={q}>{q}</li>)}
            </ul>
          )}
          {ledger?.bar && <p className="mt-2 text-xs text-slate-400">The bar, after {ledger.bar.ideas_tested} ideas tested: {ledger.bar.standard}.</p>}
        </div>
      )}
    </section>
  );
}
