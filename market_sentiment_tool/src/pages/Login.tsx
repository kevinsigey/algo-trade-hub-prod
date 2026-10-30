import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { supabase } from "@/lib/supabase";

const field =
  "mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white focus:border-emerald-400 focus:outline-none";
const primary =
  "w-full rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-60";

/** A reset link signs Kevin in for one purpose: choosing a new password (Supabase fires PASSWORD_RECOVERY). */
function NewPassword({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== again) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    const { error: err } = await supabase.auth.updateUser({ password });
    setBusy(false);
    if (err) return setError(err.message);
    onDone();
  };

  return (
    <form onSubmit={submit} className="mt-6 space-y-4">
      <label className="block text-sm text-slate-300">
        New password
        <input type="password" autoComplete="new-password" minLength={8} required value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
      </label>
      <label className="block text-sm text-slate-300">
        New password again
        <input type="password" autoComplete="new-password" minLength={8} required value={again} onChange={(e) => setAgain(e.target.value)} className={field} />
      </label>
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
      <button type="submit" disabled={busy} className={primary}>{busy ? "Saving…" : "Set password"}</button>
    </form>
  );
}

/** One admin, no sign-up (sign-ups are off in Supabase Auth). Only same-site paths are followed after sign-in. */
export default function Login() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const raw = params.get("next") ?? "/";
  const next = raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") setRecovering(true);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (err) return setError("Wrong email or password.");
    navigate(next, { replace: true });
  };

  const forgot = async () => {
    if (!email) return setError("Type your email first.");
    setError(null);
    const { error: err } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/login` });
    if (err) return setError(err.message);
    setNotice("Check your email for a link to set a new password.");
  };

  if (recovering) {
    return (
      <div className="mx-auto max-w-sm px-4 py-16">
        <h1 className="text-xl font-semibold text-white">Set a new password</h1>
        <NewPassword onDone={() => navigate("/workshop", { replace: true })} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-sm px-4 py-16">
      <h1 className="text-xl font-semibold text-white">Sign in</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm text-slate-300">
          Email
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </label>
        <label className="block text-sm text-slate-300">
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className={field} />
        </label>
        {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
        {notice && <p className="text-sm text-emerald-300">{notice}</p>}
        <button type="submit" disabled={busy} className={primary}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <button type="button" onClick={forgot} className="w-full text-sm text-slate-400 hover:text-white">
          Forgot password?
        </button>
      </form>
    </div>
  );
}
