import { useEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from "react-router-dom";
// Pages
import Home from "@/pages/Home";
import Crypto from "@/pages/Crypto";
import Models from "@/pages/Models";
import Scoreboard from "@/pages/Scoreboard";
import SportsEdges from "@/pages/SportsEdges";
import Macro from "@/pages/Macro";
import JobsNowcast from "@/pages/JobsNowcast";
import Cpi from "@/pages/Cpi";
import Oil from "@/pages/Oil";
import Journal from "@/pages/Journal";
import Health from "@/pages/Health";
import MachineKeys from "@/pages/MachineKeys";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import Weather from "@/pages/Weather";
import { NoOrdersBanner } from "@/components/NoOrdersBanner";
import Portfolio from "@/pages/Portfolio";
import ClosedTrades from "@/pages/ClosedTrades";
import IdeaRecord from "@/pages/IdeaRecord";
import Ideas from "@/pages/Ideas";
import Login, { RecoveryRedirect } from "@/pages/Login";
import Workshop from "@/pages/Workshop";
import WorkshopIdea from "@/pages/WorkshopIdea";
import { RequireAdmin, useAdminSession } from "@/components/RequireAdmin";
import { useApi } from "@/hooks/usePaperPortfolio";
import { fmtUsd, stateLabel, type PortfolioPayload } from "@/lib/paperPortfolio";
import { supabase } from "@/lib/supabase";
import { LayoutDashboard, Activity, Wallet, Cpu, LineChart, Scale, Trophy, Briefcase, BarChart3, BookOpen, HeartPulse, KeyRound, Menu, X, History, Compass, CloudSun, Lock, LogOut, FlaskConical, Lightbulb, Landmark } from "lucide-react";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 px-3 py-2 rounded-lg transition-colors ${isActive ? 'bg-secondary text-foreground font-semibold' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`;

const Group = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div>
    <div className="px-3 pb-1 text-xs font-medium text-slate-500">{label}</div>
    <div className="space-y-1">{children}</div>
  </div>
);

/**
 * The nav itself, written once and shared by the desktop rail and the phone overlay.
 *
 * Four groups (Trading HQ spec §4.1): the public Portfolio, Ideas and Predictions, and the operator
 * pages behind Kevin's login. Moved pages keep their URLs, so the shared global nav's links still work.
 *
 * `onNavigate` is the overlay's way of saying "the reader picked a page": the drawer closes, so a
 * new page is never read through it. The rail passes nothing, because the rail is always there.
 */
const SidebarBody = ({ onNavigate }: { onNavigate?: () => void }) => {
  const { data, loading } = useApi<PortfolioPayload>("/api/portfolio");
  const admin = useAdminSession();
  // A payload without a scoreboard (an older server, a proxy error page) reads as not connected, never as a crash.
  const book = data?.scoreboard && data.state !== "not_connected" ? data : null;

  return (
    <>
      <div className="p-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center border border-border">
            <Activity className="w-5 h-5 text-foreground" />
          </div>
          <span className="font-display text-2xl font-semibold tracking-wide text-foreground uppercase">Algo Trade Hub</span>
        </div>
      </div>

      <nav onClick={onNavigate} className="flex-1 overflow-y-auto px-4 space-y-5 mt-2">
        <Group label="Portfolio">
          <NavLink to="/" end className={linkClass}>
            <LayoutDashboard className="w-5 h-5" /> Portfolio
          </NavLink>
          <NavLink to="/portfolio/closed" className={linkClass}>
            <History className="w-5 h-5 text-muted-foreground" /> Closed trades
          </NavLink>
        </Group>
        <Group label="Ideas">
          <NavLink to="/ideas" className={linkClass}>
            <Lightbulb className="w-5 h-5 text-muted-foreground" /> Ideas
          </NavLink>
        </Group>
        <Group label="Predictions">
          <NavLink to="/journal" className={linkClass}>
            {/* The flagship (v2 spec §11): every forecaster's frozen, settled, scored record. */}
            <BookOpen className="w-5 h-5 text-foreground" /> Journal
          </NavLink>
          <NavLink to="/predictions" className={linkClass}>
            <Compass className="w-5 h-5 text-muted-foreground" /> Overview
          </NavLink>
          <NavLink to="/sports" className={linkClass}>
            <Trophy className="w-5 h-5 text-muted-foreground" /> Sports
          </NavLink>
          {/* Jobs and CPI are detail pages now (phase-3 §1); the nav leads with the Macro
              dashboard. The CPI honesty rule moved with the content: its macro card carries
              the "display, not opportunities" line, so the claim is still never made. */}
          <NavLink to="/macro" className={linkClass}>
            <Landmark className="w-5 h-5 text-muted-foreground" /> Macro predictions
          </NavLink>
          <NavLink to="/weather" className={linkClass}>
            <CloudSun className="w-5 h-5 text-muted-foreground" /> Weather
          </NavLink>
          {/* Phase-3 §5: the page is a research desk now, not a shadow backtester -- the sniper
              worker it graded stopped in June 2026. "Crypto research" cannot be confused with the
              scoreboard's gate status the way the old "Crypto Shadow" label could. */}
          <NavLink to="/crypto" className={linkClass}>
            <LineChart className="w-5 h-5 text-muted-foreground" /> Crypto research
          </NavLink>
        </Group>
        <Group label="Admin">
          {/* Trading HQ step 2: plain-words idea -> drafted test -> verdict. */}
          <NavLink to="/workshop" className={linkClass}>
            <FlaskConical className="w-5 h-5 text-muted-foreground" /> Workshop
          </NavLink>
          {/* "Engine Scoreboard", not "Shadow Scoreboard": the page scores ENGINES against their
              markets, and "shadow" already names two other things here. */}
          <NavLink to="/scoreboard" className={linkClass}>
            <Scale className="w-5 h-5 text-muted-foreground" /> Engine Scoreboard
          </NavLink>
          <NavLink to="/models" className={linkClass}>
            <Cpu className="w-5 h-5 text-muted-foreground" /> Models
          </NavLink>
          {/* Freshness of every timer and forecaster: "is anything running", not "who is winning". */}
          <NavLink to="/health" className={linkClass}>
            <HeartPulse className="w-5 h-5 text-teal-400" /> Health
          </NavLink>
          {/* Phase-2 machine API, step 1: key lifecycle + audit. The routes the keys serve come later. */}
          <NavLink to="/machine-keys" className={linkClass}>
            <KeyRound className="w-5 h-5 text-muted-foreground" /> Machine keys
          </NavLink>
          {admin === "admin" ? (
            <button type="button" onClick={() => void supabase.auth.signOut()} className={`${linkClass({ isActive: false })} w-full`}>
              <LogOut className="w-5 h-5" /> Sign out
            </button>
          ) : (
            <NavLink to="/login" className={linkClass}>
              <Lock className="w-5 h-5" /> Sign in
            </NavLink>
          )}
        </Group>
      </nav>

      <div className="p-4 border-t border-slate-900">
        <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800 shadow-sm">
          <div className="flex items-center gap-2 mb-2 text-slate-400 text-sm font-medium">
            <Wallet className="w-4 h-4" aria-hidden="true" /> Paper account
          </div>
          <div className={`text-2xl font-bold tabular-nums tracking-tight ${book ? "text-white" : "text-slate-400"}`}>
            {book ? fmtUsd(book.scoreboard.equity, { whole: true }) : loading ? "—" : "Not connected"}
          </div>
          {book && <div className="mt-1 text-[11px] text-slate-400">{stateLabel(book.state, book.as_of)}</div>}
        </div>
      </div>
    </>
  );
};

/**
 * The rail: the sidebar as it has always been, from 768px up.
 *
 * Below that it is display:none, because on a 375px phone a 256px rail took two thirds of the
 * screen and left every page squeezed into what was left. `hidden md:flex` is the whole of that
 * decision: the breakpoint is CSS, so there is no width check in JavaScript to fall out of step
 * with the stylesheet, and at 768px and up this is byte-for-byte the sidebar it was.
 */
const SidebarRail = () => (
  <div
    data-testid="sidebar-rail"
    className="hidden md:flex flex-col w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen sticky top-0"
  >
    <SidebarBody />
  </div>
);

/**
 * The shell: the rail beside the page, and -- on a phone -- a menu button that opens the same nav
 * over the page.
 *
 * On a 375px screen the rail was two thirds of the viewport, so every page was cramped. Below
 * 768px the rail is hidden and the button opens the nav as an overlay instead; from 768px up
 * nothing changes at all, and the button is not even on the screen.
 *
 * The overlay closes on a route change (the reader asked for a page, not for a page behind a
 * drawer), on Escape and on a click on the backdrop. It is a real `<button>`, so it is reachable
 * by keyboard, and it carries `aria-expanded`, so a screen reader says whether the menu is open.
 */
export const AppShell = ({ children }: { children: React.ReactNode }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  // A route change closes the menu.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // Escape closes it, and hands the keyboard back to the button that opened it.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // The panel takes focus when it opens, so the next Tab lands on the first link inside it.
  useEffect(() => {
    if (menuOpen) overlayRef.current?.focus();
  }, [menuOpen]);

  const closeMenu = () => setMenuOpen(false);

  return (
    // Column on a phone (the menu bar sits above the page), row from 768px up (the rail sits
    // beside the page, as it always has).
    <div className="flex min-h-screen flex-col bg-slate-950 md:flex-row">
      <SidebarRail />
      {menuOpen && (
        <>
          <div
            data-testid="sidebar-backdrop"
            aria-hidden="true"
            onClick={closeMenu}
            className="md:hidden fixed inset-0 z-40 bg-slate-950/70"
          />
          <div
            id="site-menu"
            data-testid="sidebar-overlay"
            role="dialog"
            aria-label="Site menu"
            tabIndex={-1}
            ref={overlayRef}
            className="md:hidden fixed inset-y-0 left-0 z-50 flex flex-col w-64 bg-slate-950 text-slate-200 border-r border-slate-900 h-screen shadow-2xl"
          >
            <SidebarBody onNavigate={closeMenu} />
          </div>
        </>
      )}
      {/* The phone's way into the nav. md:hidden, so from 768px up the page starts at the top
          exactly as it always did. */}
      <div className="md:hidden sticky top-0 z-30 flex items-center gap-3 border-b border-slate-900 bg-slate-950/95 px-4 py-3">
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-800 text-slate-300 hover:bg-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          {menuOpen ? (
            <X className="w-5 h-5" aria-hidden="true" />
          ) : (
            <Menu className="w-5 h-5" aria-hidden="true" />
          )}
        </button>
        <span className="text-sm font-bold uppercase italic tracking-tight text-white">Algo Trade Hub</span>
      </div>
      <main className="flex-1 min-h-screen overflow-auto bg-slate-950 text-slate-100">
        <NoOrdersBanner />
        {children}
      </main>
    </div>
  );
};

function Guarded({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary resetKey={useLocation().pathname}>{children}</ErrorBoundary>;
}

function App() {
  return (
    <BrowserRouter>
      <RecoveryRedirect />
      <AppShell>
        <Guarded>
        <Routes>
          {/* Trading HQ (spec 2026-10-29): the paper portfolio is the home page; the old home is the
              Predictions overview. */}
          <Route path="/" element={<Portfolio />} />
          <Route path="/portfolio/closed" element={<ClosedTrades />} />
          <Route path="/ideas" element={<Ideas />} />
          <Route path="/ideas/:id" element={<IdeaRecord />} />
          <Route path="/predictions" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/workshop" element={<RequireAdmin><Workshop /></RequireAdmin>} />
          <Route path="/workshop/:id" element={<RequireAdmin><WorkshopIdea /></RequireAdmin>} />
          {/* /lab was the Prediction Lab; the journal replaced it (v2 spec §9). A redirect, not a 404, so
              bookmarks and links keep working. */}
          <Route path="/lab" element={<Navigate to="/journal" replace />} />
          {/* Phase-3 §5: the shadow backtester is deleted (it graded a worker that stopped in
              June 2026 as if it were live). /shadow redirects to the crypto research desk --
              the destination is the crypto successor page, not the scoreboard, so the old
              collision warning does not apply. */}
          <Route path="/shadow" element={<Navigate to="/crypto" replace />} />
          <Route path="/crypto" element={<Crypto />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/models" element={<RequireAdmin><Models /></RequireAdmin>} />
          {/* The engine scoreboard, canonically at /scoreboard.
              `/engines` was the other candidate and was rejected: /models already lists every
              engine one row at a time, so /engines would have been a SECOND route that means "the
              engines", differing only in depth. That is the same collision this branch exists to
              close, one level down. `/scoreboard` names the artifact rather than its contents, so
              it takes a new engine without the name going stale, and it already matches the
              endpoint (/api/scoreboard) and the file (Scoreboard.tsx), so it costs no rename. */}
          <Route path="/scoreboard" element={<RequireAdmin><Scoreboard /></RequireAdmin>} />
          {/* `/shadow-scoreboard` -> `/scoreboard`, permanently.
              The owner's approval for this page was literally called "the shadow scoreboard", so
              that string is a name people will type. A redirect makes the NAME work without making
              it the NAME, which is the whole distinction: "shadow" already means two things in
              this product -- the crypto timeline and the not-promoted gate status -- and the engine
              scoreboard is about neither. An earlier revision of this branch made
              /shadow-scoreboard canonical, which left the ambiguity in a route instead of a nav
              label, where it is expensive to change. It is a redirect here and nothing else.
              Same component, same /api/scoreboard read, address bar updated to the real path. */}
          <Route path="/shadow-scoreboard" element={<Navigate to="/scoreboard" replace />} />
          <Route path="/sports" element={<SportsEdges />} />
          <Route path="/macro" element={<Macro />} />
          <Route path="/jobs" element={<JobsNowcast />} />
          <Route path="/cpi" element={<Cpi />} />
          <Route path="/oil" element={<Oil />} />
          <Route path="/health" element={<RequireAdmin><Health /></RequireAdmin>} />
          <Route path="/machine-keys" element={<RequireAdmin><MachineKeys /></RequireAdmin>} />
          <Route path="/weather" element={<Weather />} />
        </Routes>
        </Guarded>
      </AppShell>
    </BrowserRouter>
  );
}

export default App;
